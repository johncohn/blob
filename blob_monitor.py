#!/usr/bin/env python3
"""
blob_monitor.py — Echo, record, and play back Blob TouchOSC surface controls.

Keys: [R]ec  [P]lay  [Space]Pause  [[]Rewind  [L]oad latest  [Q]uit
Surface: CC39=RECORD toggle, CC40=PLAY toggle (all ch 2)

Usage:
    python3 blob_monitor.py              # auto-detect ports
    python3 blob_monitor.py --list       # list all MIDI ports and exit
    python3 blob_monitor.py --in 1 --out 2   # use specific port indices

Port selection:
    Input  — auto-selects first port matching: touchosc, network session, iac
    Output — auto-selects first port matching: feather, m4, samd, widi, cme
    If auto-detection fails you will be prompted to choose interactively.
"""

import argparse, curses, threading, time

try:
    import mido
except ImportError:
    raise SystemExit("Install mido: pip install mido")
from datetime import datetime
from pathlib import Path

try:
    import rtmidi
except ImportError:
    raise SystemExit("Install python-rtmidi: pip install python-rtmidi")

MIDI_CH   = 1       # 0-based → MIDI channel 2
CC_RECORD = 39
CC_PLAY   = 40
CC_LOOP   = 43

CC_NAMES = {
    16: "Servo 0",   17: "Servo 1",   18: "Servo 2",
    20: "Servo 3",   21: "Servo 4",   22: "Servo 5",
    24: "Servo 6",   25: "Servo 7",   26: "Servo 8",
    32: "Blower Hi", 33: "Breathe",   34: "HB Speed",  35: "HB Bright",
    36: "HALT",      37: "RETRACT",   38: "Shutoff",
    39: "RECORD",    40: "PLAY",
    41: "Blower Lo", 42: "Brth Rate", 43: "LOOP",
}

REC_DIR        = Path("recordings")
TICKS_PER_BEAT = 960
MIDI_TEMPO     = 500000   # 120 BPM → 1920 ticks/sec, ~0.52 ms resolution


def events_to_midi(events):
    mid   = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=MIDI_TEMPO, time=0))
    tps      = TICKS_PER_BEAT * 1_000_000 / MIDI_TEMPO   # 1920.0
    prev_tick = 0
    for ev in sorted(events, key=lambda e: e['t']):
        tick  = round(ev['t'] * tps)
        delta = tick - prev_tick
        track.append(mido.Message('control_change',
                                  channel=MIDI_CH,
                                  control=ev['cc'],
                                  value=ev['val'],
                                  time=delta))
        prev_tick = tick
    return mid


def midi_to_events(mid):
    tempo = next(
        (m.tempo for t in mid.tracks for m in t if m.type == 'set_tempo'),
        MIDI_TEMPO
    )
    tps    = mid.ticks_per_beat * 1_000_000 / tempo
    events = []
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == 'control_change':
                events.append({'t': abs_tick / tps,
                                'cc': msg.control,
                                'val': msg.value})
    events.sort(key=lambda e: e['t'])
    return events


class BlobMonitor:

    def __init__(self, in_port=None, out_port=None):
        self.lock      = threading.Lock()
        self.mode      = "IDLE"    # IDLE RECORDING PLAYING PAUSED
        self.events    = []        # [{'t': float, 'cc': int, 'val': int}, …]
        self.play_pos  = 0.0
        self.rec_start = 0.0
        self.filename  = ""
        self.log       = []        # (t_str, label, cc, val) — cc==0 ⟹ separator
        self.loop_mode = False
        self.stop_evt  = threading.Event()
        self._play_thr = None
        self._open_midi(in_port, out_port)

    # ── MIDI ───────────────────────────────────────────────────────────────

    def _open_midi(self, in_idx=None, out_idx=None):
        self.mid_in   = rtmidi.MidiIn()
        self.mid_out  = rtmidi.MidiOut()
        self.in_name  = self._pick_port(self.mid_in,  is_out=False, explicit=in_idx)
        self.out_name = self._pick_port(self.mid_out, is_out=True,  explicit=out_idx)
        self.mid_in.set_callback(self._on_midi)
        self.mid_in.ignore_types(sysex=True, timing=True, active_sense=True)

    def _pick_port(self, dev, is_out, explicit=None):
        ports = dev.get_ports()
        label = "Output (hardware/Feather)" if is_out else "Input (TouchOSC/IAC)"

        if explicit is not None:
            if explicit >= len(ports):
                raise SystemExit(f"Port index {explicit} out of range (0–{len(ports)-1})")
            dev.open_port(explicit)
            return ports[explicit]

        # Auto-detect: output → hardware; input → TouchOSC routing bus.
        if is_out:
            wanted = ("feather", "m4", "samd", "widi", "cme", "fighter", "twister")
        else:
            wanted = ("touchosc", "network session", "iac")

        for i, p in enumerate(ports):
            if any(k in p.lower() for k in wanted):
                dev.open_port(i)
                return p

        # Interactive fallback — runs before curses, so input() works fine.
        if not ports:
            dev.open_virtual_port("BlobMonitor")
            return "BlobMonitor (virtual)"

        print(f"\nCould not auto-detect {label} port.")
        print("Available ports:")
        for i, p in enumerate(ports):
            print(f"  {i}: {p}")
        try:
            idx = int(input(f"Select {label} port index [0]: ").strip() or "0")
        except (ValueError, EOFError):
            idx = 0
        dev.open_port(idx)
        return ports[idx]

    def _send_cc(self, cc, val):
        try:
            self.mid_out.send_message([0xB0 | MIDI_CH, cc, int(val) & 0x7F])
        except Exception:
            pass

    def _on_midi(self, event, _=None):
        try:
            self._on_midi_inner(event)
        except Exception as e:
            with self.lock:
                self._sep(f"ERR: {e}")

    def _on_midi_inner(self, event):
        msg, _ = event
        if len(msg) < 3:
            return
        if (msg[0] & 0xF0) != 0xB0:   # only CC messages; accept any channel
            return
        cc, val = msg[1], msg[2]
        ch = (msg[0] & 0x0F) + 1      # for logging only

        if cc == CC_RECORD:
            with self.lock:
                self._append_log("  btn  ", f"ch{ch} RECORD {'ON' if val>0 else 'off'}", cc, val)
            (self._start_record if val > 0 else self._stop_record)()
            return
        if cc == CC_PLAY:
            with self.lock:
                self._append_log("  btn  ", f"ch{ch} PLAY {'ON' if val>0 else 'off'}", cc, val)
            (self._start_play if val > 0 else self._stop_play)()
            return
        if cc == CC_LOOP:
            with self.lock:
                self._append_log("  btn  ", f"ch{ch} LOOP {'ON' if val>0 else 'off'}", cc, val)
            (self._start_loop if val > 0 else self._stop_play)()
            return

        name = CC_NAMES.get(cc, f"CC{cc}")
        now  = time.time()
        with self.lock:
            if self.mode == "RECORDING":
                t = now - self.rec_start
                self.events.append({"t": t, "cc": cc, "val": val})
                t_str = f"{t:7.3f}s"
            else:
                t_str = "       s"
            self._append_log(t_str, f"ch{ch} {name}", cc, val)

    # ── Log helpers (must be called while holding self.lock) ───────────────

    def _append_log(self, t_str, label, cc, val):
        self.log.append((t_str, label, cc, val))
        if len(self.log) > 80:
            self.log = self.log[-80:]

    def _sep(self, text):            # separator / status line in log
        self._append_log("        ", text, 0, 0)

    # ── State transitions ──────────────────────────────────────────────────

    def _start_record(self):
        old_thr = None
        with self.lock:
            if self.mode == "RECORDING":
                return
            was_playing = self.mode in ("PLAYING", "PAUSED")
            if was_playing:
                self.stop_evt.set()
                old_thr = self._play_thr
            self.mode      = "RECORDING"
            self.events    = []
            self.play_pos  = 0.0
            self.rec_start = time.time()
            self._sep("─── REC START ───")
        if old_thr:
            old_thr.join(timeout=0.15)
        if was_playing:
            self._send_cc(CC_PLAY, 0)      # deactivate PLAY button on surface

    def _stop_record(self):
        with self.lock:
            if self.mode != "RECORDING":
                return
            self.mode = "IDLE"
            evs = list(self.events)
            self._sep("─── REC STOP  ───")
        self._save(evs)

    def _start_play(self):
        evs_to_save = None
        old_thr     = None
        with self.lock:
            prev_mode = self.mode
            if self.mode == "RECORDING":
                evs_to_save = list(self.events)
                self.mode   = "IDLE"
                self._sep(f"PLAY pressed (was REC, {len(evs_to_save)} events)")
            elif self.mode in ("PLAYING", "PAUSED"):
                self.stop_evt.set()
                self.mode = "IDLE"
                old_thr   = self._play_thr
                self._sep(f"PLAY pressed (was {prev_mode})")
            else:
                self._sep(f"PLAY pressed (was {prev_mode})")
        if old_thr:
            old_thr.join(timeout=0.15)
        if evs_to_save is not None:
            self._save(evs_to_save)
            self._send_cc(CC_RECORD, 0)    # deactivate REC button on surface
        self._launch_play()

    def _start_loop(self):
        with self.lock:
            self.loop_mode = True
        self._start_play()

    def _stop_play(self):
        with self.lock:
            if self.mode not in ("PLAYING", "PAUSED"):
                return
            self.stop_evt.set()
            self.mode      = "IDLE"
            self.play_pos  = 0.0
            self.loop_mode = False

    def toggle_pause(self):
        with self.lock:
            if   self.mode == "PLAYING": self.mode = "PAUSED"
            elif self.mode == "PAUSED":  self.mode = "PLAYING"

    def rewind(self):
        old_thr = None
        with self.lock:
            if self.mode not in ("PLAYING", "PAUSED"):
                return
            self.stop_evt.set()
            self.mode     = "IDLE"
            self.play_pos = 0.0
            old_thr = self._play_thr
        if old_thr:
            old_thr.join(timeout=0.15)
        self._launch_play()

    def _launch_play(self):
        with self.lock:
            if not self.events:
                self._sep("(nothing to play)")
                return
            self.stop_evt.clear()
            self.mode     = "PLAYING"
            self.play_pos = 0.0
            evs = list(self.events)
            self._sep("─── PLAYBACK  ───")
        self._play_thr = threading.Thread(
            target=self._play_fn, args=(evs,), daemon=True)
        self._play_thr.start()

    # ── Playback thread ────────────────────────────────────────────────────

    def _play_fn(self, events):
        while True:
            wall         = time.time()
            paused_total = 0.0
            pause_wall   = None
            i            = 0
            while i < len(events) and not self.stop_evt.is_set():
                with self.lock:
                    m = self.mode
                if m == "PAUSED":
                    if pause_wall is None:
                        pause_wall = time.time()
                    time.sleep(0.02)
                    continue
                if pause_wall is not None:
                    paused_total += time.time() - pause_wall
                    pause_wall    = None
                elapsed = time.time() - wall - paused_total
                with self.lock:
                    self.play_pos = elapsed
                if elapsed >= events[i]["t"]:
                    e = events[i]
                    self._send_cc(e["cc"], e["val"])
                    i += 1
                else:
                    time.sleep(0.002)

            should_loop = False
            with self.lock:
                done = not self.stop_evt.is_set()
                if done and self.loop_mode:
                    should_loop = True
                    self.play_pos = 0.0
                    self._sep("─ LOOP ─")
            if should_loop:
                continue

            with self.lock:
                if done:
                    self.mode      = "IDLE"
                    self.play_pos  = 0.0
                    self.loop_mode = False
                    self._sep("─── PLAY DONE ───")
            if done:
                self._send_cc(CC_PLAY, 0)
                self._send_cc(CC_LOOP, 0)
            break

    # ── File I/O ───────────────────────────────────────────────────────────

    def _save(self, events):
        try:
            REC_DIR.mkdir(exist_ok=True)
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            fn  = REC_DIR / f"blob_{ts}.mid"
            mid = events_to_midi(events)
            mid.save(str(fn))
            mid.save(str(REC_DIR / "latest.mid"))
            with self.lock:
                self.filename = str(fn)
                self._sep(f"Saved {fn.name} ({len(events)} events)")
        except Exception as e:
            with self.lock:
                self._sep(f"SAVE ERR: {e}")

    def load_latest(self):
        files = sorted(REC_DIR.glob("blob_*.mid"))
        if not files:
            with self.lock:
                self._sep("No recordings found in recordings/")
            return
        fn = files[-1]
        try:
            events = midi_to_events(mido.MidiFile(str(fn)))
        except Exception as e:
            with self.lock:
                self._sep(f"LOAD ERR: {e}")
            return
        with self.lock:
            self.events   = events
            self.filename = str(fn)
            self._sep(f"Loaded {fn.name} ({len(events)} events)")

    def close(self):
        self.stop_evt.set()
        self.mid_in.close_port()
        self.mid_out.close_port()


# ── Curses UI ──────────────────────────────────────────────────────────────

def draw_ui(scr, mon, colors):
    GREEN, RED, CYAN, YELLOW, DIM = colors
    h, w = scr.getmaxyx()
    W    = w - 1
    scr.erase()

    def put(row, col, text, attr=0):
        if row < 0 or row >= h or col >= W:
            return
        try:
            scr.addstr(row, col, text[: W - col], attr)
        except curses.error:
            pass

    # header
    title = "BLOB MONITOR  –  TouchOSC Test"
    put(0, max(0, (W - len(title)) // 2), title, curses.A_BOLD | CYAN)
    put(1, 0, f" IN : {mon.in_name}")
    put(2, 0, f" OUT: {mon.out_name}")
    put(3, 0, "─" * W)

    # snapshot shared state once
    with mon.lock:
        mode      = mon.mode
        pos       = mon.play_pos
        events    = mon.events
        filename  = mon.filename
        rec_start = mon.rec_start
        loop_mode = mon.loop_mode

    dur = events[-1]["t"] if events else 0.0
    now = time.time()

    mode_clr = {
        "IDLE":      0,
        "RECORDING": RED   | curses.A_BOLD,
        "PLAYING":   GREEN | curses.A_BOLD,
        "PAUSED":    YELLOW| curses.A_BOLD,
    }.get(mode, 0)

    blink = " ●" if mode == "RECORDING" and int(now * 2) % 2 else "  "
    if mode == "RECORDING":
        status = f" {mode}{blink}  {now - rec_start:.1f}s"
    elif mode in ("PLAYING", "PAUSED"):
        m_p, s_p = divmod(int(pos), 60)
        m_d, s_d = divmod(int(dur), 60)
        loop_tag = "  ↺LOOP" if loop_mode else ""
        status = f" {mode}{loop_tag}   {m_p:02d}:{s_p:02d} / {m_d:02d}:{s_d:02d}"
    else:
        note   = f"  ({dur:.1f}s buffered)" if events else "  (nothing buffered)"
        loop_tag = "  [LOOP ON]" if loop_mode else ""
        status = f" {mode}{loop_tag}{note}"
    put(4, 0, status, mode_clr)

    # timeline bar (row 5)
    bar_w = W - 18
    if bar_w > 5:
        if events:
            frac   = min(pos / dur, 1.0) if dur > 0 else 0.0
            filled = int(frac * bar_w)
            bar    = "█" * filled + "░" * (bar_w - filled)
            m_p, s_p = divmod(int(pos), 60)
            m_d, s_d = divmod(int(dur), 60)
            put(5, 0, f" [{bar}] {m_p:02d}:{s_p:02d}/{m_d:02d}:{s_d:02d}")
        else:
            put(5, 0, f" [{'─' * bar_w}]  (no recording)")

    if filename:
        put(6, 0, f" {Path(filename).name}", YELLOW)

    put(7, 0, "─" * W)

    # event log
    log_top = 8
    log_h   = h - log_top - 2
    with mon.lock:
        log = mon.log[-log_h:]
    for i, (t_str, label, cc, val) in enumerate(log):
        row = log_top + i
        if row >= h - 2:
            break
        if cc == 0:
            put(row, 0, f"   {label}", YELLOW)
        else:
            blen = int(val / 127 * 12)
            vbar = "█" * blen + "░" * (12 - blen)
            put(row, 0, f"  {t_str}  {label:<12}  CC{cc:<3}  {val:3d}  [{vbar}]")

    # footer keys
    put(h - 1, 0,
        " [R]ec  [P]lay  [O]Loop  [Space]Pause  [[]Rewind  [L]oad  [Q]uit",
        DIM)


def run_ui(scr, mon):
    curses.curs_set(0)
    scr.nodelay(True)
    scr.timeout(50)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN,  -1)
    curses.init_pair(2, curses.COLOR_RED,    -1)
    curses.init_pair(3, curses.COLOR_CYAN,   -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    colors = (
        curses.color_pair(1),   # GREEN
        curses.color_pair(2),   # RED
        curses.color_pair(3),   # CYAN
        curses.color_pair(4),   # YELLOW
        curses.A_DIM,           # DIM
    )

    while True:
        key = scr.getch()
        if key in (ord("q"), ord("Q")):
            break
        elif key in (ord("r"), ord("R")):
            if mon.mode == "RECORDING":
                mon._stop_record()
            else:
                mon._start_record()
        elif key in (ord("p"), ord("P")):
            if mon.mode in ("PLAYING", "PAUSED"):
                mon._stop_play()
                mon._send_cc(CC_PLAY, 0)
            else:
                mon._start_play()
        elif key == ord(" "):
            mon.toggle_pause()
        elif key in (ord("["), curses.KEY_HOME):
            mon.rewind()
        elif key in (ord("l"), ord("L")):
            mon.load_latest()
        elif key in (ord("o"), ord("O")):
            with mon.lock:
                mon.loop_mode = not mon.loop_mode
        draw_ui(scr, mon, colors)


def main():
    ap = argparse.ArgumentParser(description="Blob MIDI Monitor")
    ap.add_argument("--list", action="store_true",
                    help="List all MIDI ports and exit")
    ap.add_argument("--in",  dest="in_port",  type=int, default=None,
                    help="Input port index (overrides auto-detect)")
    ap.add_argument("--out", dest="out_port", type=int, default=None,
                    help="Output port index (overrides auto-detect)")
    args = ap.parse_args()

    if args.list:
        ins  = rtmidi.MidiIn().get_ports()
        outs = rtmidi.MidiOut().get_ports()
        print("MIDI Input ports:")
        for i, p in enumerate(ins):
            print(f"  {i}: {p}")
        print("MIDI Output ports:")
        for i, p in enumerate(outs):
            print(f"  {i}: {p}")
        return

    REC_DIR.mkdir(exist_ok=True)
    mon = BlobMonitor(in_port=args.in_port, out_port=args.out_port)
    print(f"\n IN : {mon.in_name}")
    print(f" OUT: {mon.out_name}")
    print()
    print(" NOTE: TouchOSC must send MIDI to the IN port above.")
    print("       Loop playback goes to the OUT port above.")
    time.sleep(2)      # let user read port names before curses takes over
    try:
        curses.wrapper(run_ui, mon)
    finally:
        mon.close()
    print(f"\nRecordings saved in: {REC_DIR}/")


if __name__ == "__main__":
    main()

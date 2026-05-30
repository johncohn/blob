#!/usr/bin/env python3
"""
blob_monitor.py — Echo, record, and play back Blob TouchOSC surface controls.

Recordings are saved as Standard MIDI Files (.mid, Type 0, 960 PPQ) in the
recordings/ directory, directly editable in any DAW. CC numbers match the
TouchOSC layout (servos CC16-18, 20-22, 24-26; blower/HB/etc on higher CCs).

Keyboard: [R]ec  [P]lay  [O]Loop-toggle  [Space]Pause  [[]Rewind  [L]oad  [Q]uit
Surface:  CC39=RECORD toggle, CC40=PLAY toggle (MIDI ch 2)
          PLAY always loops until clicked again.
          Pressing PLAY while recording stops recording and starts playback.
          Pressing RECORD while playing stops playback and starts recording.

Usage:
    python3 blob_monitor.py                          # auto-detect all ports
    python3 blob_monitor.py --list                   # list MIDI ports and exit
    python3 blob_monitor.py --in 1 --out 2           # specific port indices
    python3 blob_monitor.py --in-name "Network blob" --out-name "feather,iac"

Port selection (auto-detect order):
    Input    — network blob → touchosc → network session → iac
    Output   — feather → m4 → samd → widi → cme → fighter → twister
    Feedback — network blob → network session → touchosc  (sends playback
               CCs back to the surface so sliders track and buttons stay in sync)
    If auto-detection fails you will be prompted to choose interactively.

Raspberry Pi setup:
    pip install mido python-rtmidi
    Run via monitor.sh for name-based port matching across reboots.
"""

import argparse, curses, re, shutil, socket, subprocess, sys, threading, time

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

# Optional OLED display (Adafruit PiOLED 128×32, I2C)
try:
    from luma.core.interface.serial import i2c as luma_i2c
    from luma.oled.device import ssd1306
    from PIL import Image, ImageDraw, ImageFont
    _OLED_AVAIL = True
except ImportError:
    _OLED_AVAIL = False

MIDI_CH      = 0    # 0-based → MIDI channel 1 (0xB0); M4 expects ch1 for servo CCs
MIDI_CH_FB   = 1    # 0-based → MIDI channel 2 (0xB1); TouchOSC listens on ch2
OSC_IN_PORT  = 8000 # Pi listens for OSC from iPads (no mDNS needed, pure unicast)
OSC_OUT_PORT = 9000 # Pi sends OSC feedback back to iPads
CC_HALT      = 36
CC_RETRACT   = 37
CC_RECORD    = 39
CC_PLAY      = 40
CC_LOOP      = 43
CC_CONNECTED = 63   # Pi heartbeat: 127=online, 0=offline; fb_only, never sent to M4

SERVO_CCS  = [16, 17, 18, 20, 21, 22, 24, 25, 26]  # all 9 servo CC numbers

CC_NAMES = {
    16: "Servo 0",   17: "Servo 1",   18: "Servo 2",
    20: "Servo 3",   21: "Servo 4",   22: "Servo 5",
    24: "Servo 6",   25: "Servo 7",   26: "Servo 8",
    32: "Blower Hi", 33: "Breathe",   34: "HB Speed",  35: "HB Bright",
    36: "HALT",      37: "RETRACT",   38: "Shutoff",
    39: "RECORD",    40: "PLAY",
    41: "Blower Lo", 42: "Brth Rate", 43: "LOOP",
    63: "Pi-Conn",
}

REC_DIR        = Path("recordings")
TICKS_PER_BEAT = 960
MIDI_TEMPO     = 500000   # 120 BPM → 1920 ticks/sec, ~0.52 ms resolution


def events_to_midi(events, duration=None):
    mid   = mido.MidiFile(type=0, ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=MIDI_TEMPO, time=0))
    tps       = TICKS_PER_BEAT * 1_000_000 / MIDI_TEMPO   # 1920.0
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
    if duration is not None and duration > 0:
        end_tick = round(duration * tps)
        track.append(mido.MetaMessage('end_of_track',
                                      time=max(0, end_tick - prev_tick)))
    return mid


def midi_to_events(mid):
    """Returns (events, duration).  duration comes from end_of_track timing."""
    tempo = next(
        (m.tempo for t in mid.tracks for m in t if m.type == 'set_tempo'),
        MIDI_TEMPO
    )
    tps      = mid.ticks_per_beat * 1_000_000 / tempo
    events   = []
    duration = 0.0
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == 'control_change':
                events.append({'t': abs_tick / tps,
                               'cc': msg.control,
                               'val': msg.value})
            elif msg.type == 'end_of_track':
                duration = max(duration, abs_tick / tps)
    events.sort(key=lambda e: e['t'])
    return events, duration


def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "no network"


class OledDisplay:
    """128×32 SSD1306 OLED updater. Silently does nothing if hardware absent."""

    W, H = 128, 32

    def __init__(self, mon):
        self.mon  = mon
        self.dev  = None
        self.font = None
        if not _OLED_AVAIL:
            return
        try:
            serial   = luma_i2c(port=1, address=0x3C)
            self.dev = ssd1306(serial, width=self.W, height=self.H)
            self.font = ImageFont.load_default()
        except Exception:
            self.dev = None

    def _render(self):
        img  = Image.new("1", (self.W, self.H), 0)
        draw = ImageDraw.Draw(img)
        f    = self.font

        with self.mon.lock:
            mode      = self.mon.mode
            pos       = self.mon.play_pos
            events    = self.mon.events
            last_scc  = self.mon._last_servo_cc
            last_sval = self.mon._last_servo_val
            wired_cnt = self.mon._wired_count

        dur = events[-1]["t"] if events else 0.0

        # 3 rows at y=0,11,22 — safe for both 8px and 10px default fonts
        dot = "●" if wired_cnt > 0 else "○"   # ● connected  ○ idle
        draw.text((0,  0), f"{dot} {_local_ip()}", font=f, fill=1)

        if mode == "RECORDING":
            draw.text((0, 11), "REC", font=f, fill=1)
        elif mode in ("PLAYING", "PAUSED"):
            m_p, s_p = divmod(int(pos), 60)
            m_d, s_d = divmod(int(dur), 60)
            draw.text((0, 11), f"{mode} {m_p:02d}:{s_p:02d}/{m_d:02d}:{s_d:02d}", font=f, fill=1)
        else:
            draw.text((0, 11), "IDLE", font=f, fill=1)

        # Row 3: last servo activity — index (0-8), value, mini bar
        _CC_SERVO_IDX = {16:0,17:1,18:2,20:3,21:4,22:5,24:6,25:7,26:8}
        if last_scc is not None:
            idx  = _CC_SERVO_IDX.get(last_scc, last_scc)
            blen = int(last_sval / 127 * 8)
            bar  = "█" * blen + "░" * (8 - blen)
            draw.text((0, 22), f"S{idx} {last_sval:3d} [{bar}]", font=f, fill=1)
        else:
            draw.text((0, 22), "no servo", font=f, fill=1)

        self.dev.display(img)

    def start(self):
        if not self.dev:
            return
        def _loop():
            while True:
                try:
                    self._render()
                except Exception:
                    pass
                time.sleep(0.1)
        threading.Thread(target=_loop, daemon=True).start()

    def show_message(self, line1, line2=""):
        if not self.dev:
            return
        img  = Image.new("1", (self.W, self.H), 0)
        draw = ImageDraw.Draw(img)
        draw.text((0,  0), line1, font=self.font, fill=1)
        draw.text((0, 10), line2, font=self.font, fill=1)
        self.dev.display(img)


class BlobMonitor:

    def __init__(self, in_port=None, out_port=None, in_name=None, out_name=None):
        self.lock      = threading.Lock()
        self.mode      = "IDLE"    # IDLE RECORDING PLAYING PAUSED
        self.events    = []        # [{'t': float, 'cc': int, 'val': int}, …]
        self.play_pos  = 0.0
        self.rec_start = 0.0
        self.filename  = ""
        self.log       = []        # (t_str, label, cc, val) — cc==0 ⟹ separator
        self.loop_mode = False
        self._last_servo_cc  = None   # last servo CC received (16-26)
        self._last_servo_val = 0
        self.rec_duration    = 0.0    # wall-clock length of the current recording
        self._wired_count    = 0      # number of iPad/device ports currently wired
        self._osc_peers      = {}     # ip → last-seen time; for OSC feedback
        self._osc_sock       = None
        self.stop_evt  = threading.Event()
        self._play_thr = None
        self._open_midi(in_port, out_port, in_name, out_name)
        self._start_osc_server()
        # Clear button states on the surface at startup
        self._send_cc(CC_RECORD, 0, fb_only=True)
        self._send_cc(CC_PLAY,   0, fb_only=True)
        if shutil.which("rclone"):
            threading.Thread(target=self._gdrive_startup_sync, daemon=True).start()

    # ── OSC (unicast UDP — works without mDNS, just enter Pi IP in TouchOSC) ─

    def _start_osc_server(self):
        import socket as _socket
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            s.bind(("0.0.0.0", OSC_IN_PORT))
            self._osc_sock = s
            threading.Thread(target=self._osc_recv_loop, daemon=True).start()
            with self.lock:
                self._sep(f"OSC in  :{OSC_IN_PORT}  out:{OSC_OUT_PORT}")
        except Exception as e:
            with self.lock:
                self._sep(f"OSC server err: {e}")

    def _osc_recv_loop(self):
        while True:
            try:
                data, addr = self._osc_sock.recvfrom(1024)
                self._osc_handle(data, addr[0])
            except Exception:
                pass

    def _osc_handle(self, data, ip):
        try:
            path, val = self._parse_osc_float(data)
        except Exception:
            return
        if not path.startswith('/blob/cc/'):
            return
        try:
            cc = int(path[len('/blob/cc/'):])
        except ValueError:
            return
        midi_val = max(0, min(127, round(val * 127)))
        with self.lock:
            self._osc_peers[ip] = time.time()
        self._on_midi_inner(([0xB0 | MIDI_CH_FB, cc, midi_val], 0))

    @staticmethod
    def _parse_osc_float(data):
        """Parse a minimal OSC message; return (path, float_0_to_1)."""
        import struct
        def next_osc(d, pos):
            end = d.index(b'\x00', pos)
            s = d[pos:end].decode('utf-8', errors='ignore')
            return s, (end + 4) // 4 * 4
        path, pos = next_osc(data, 0)
        tag,  pos = next_osc(data, pos)
        if 'f' in tag:
            return path, float(struct.unpack('>f', data[pos:pos+4])[0])
        if 'i' in tag:
            return path, float(struct.unpack('>i', data[pos:pos+4])[0])
        return path, 0.0

    def _send_osc_feedback(self, cc, val):
        if not self._osc_peers or not self._osc_sock:
            return
        import struct
        pb = f'/blob/cc/{cc}'.encode()
        n  = len(pb) + 1
        pb = pb + b'\x00' * ((4 - n % 4) % 4 + 1)
        tb = b',f\x00\x00'
        vb = struct.pack('>f', val / 127.0)
        msg = pb + tb + vb
        for ip in list(self._osc_peers):
            try:
                self._osc_sock.sendto(msg, (ip, OSC_OUT_PORT))
            except Exception:
                pass

    # ── MIDI ───────────────────────────────────────────────────────────────

    def _open_midi(self, in_idx=None, out_idx=None, in_name=None, out_name=None):
        self.mid_in   = rtmidi.MidiIn()
        self.mid_out  = rtmidi.MidiOut()
        self.in_name  = self._pick_port(self.mid_in,  is_out=False, explicit=in_idx,  name_hint=in_name)
        self.out_name = self._pick_port(self.mid_out, is_out=True,  explicit=out_idx, name_hint=out_name)
        self.mid_in.set_callback(self._on_midi)
        self.mid_in.ignore_types(sysex=True, timing=True, active_sense=True)
        # Keywords used to reopen mid_out if M4 disconnects (USB power cycle)
        if out_name is not None:
            self._out_keywords = [k.strip().lower() for k in out_name.split(",")]
        else:
            self._out_keywords = ["feather", "m4", "samd", "widi", "cme", "fighter", "twister"]
        self._out_needs_reconnect = False
        threading.Thread(target=self._reconnect_out_loop, daemon=True).start()
        if shutil.which("aconnect"):
            threading.Thread(target=self._wire_ipad,     daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        # Feedback port: sends CCs back to control surface (iPad) so its
        # sliders track playback and button states stay in sync.
        # Use a virtual port so _wire_ipad() wires it via aconnect — avoids
        # routing through Network Export which would echo back to blob_in.
        fb_dev = rtmidi.MidiOut(name="BlobFeedback")
        fb_dev.open_virtual_port("BlobFeedback")
        self.mid_fb  = fb_dev
        self.fb_name = "BlobFeedback"

    def _wire_ipad(self):
        """Background: wire every rtpmidid device port → blob_monitor and back.
        Handles any number of iPads; re-wires automatically on reconnect."""
        wired = set()   # ALSA addresses currently wired, e.g. {"128:5"}
        while True:
            time.sleep(2)
            try:
                r = subprocess.run(["aconnect", "-l"], capture_output=True, text=True, timeout=5)
                if r.returncode != 0:
                    continue
                cur_client, cur_cname = None, None
                portmap = {}
                for line in r.stdout.splitlines():
                    cm = re.match(r"^client (\d+): '([^']+)'", line)
                    if cm:
                        cur_client, cur_cname = cm.group(1), cm.group(2).strip()
                        continue
                    pm = re.match(r"^\s+(\d+) '([^']+)'", line)
                    if pm and cur_client:
                        portmap[f"{cur_cname}:{pm.group(2).strip()}"] = f"{cur_client}:{pm.group(1)}"
                lportmap = {k.lower(): v for k, v in portmap.items()}
                blob_in = next((v for k, v in lportmap.items()
                                if k.startswith("rtmidiin client:")), None)
                blob_fb = next((v for k, v in lportmap.items()
                                if k.startswith("blobfeedback:")), None)
                if not blob_in or not blob_fb:
                    continue

                # All rtpmidid ports except "Network Export" are connected devices
                devices = {k: v for k, v in lportmap.items()
                           if k.startswith("rtpmidid:") and "network export" not in k}

                for name, addr in devices.items():
                    if addr not in wired:
                        subprocess.run(["aconnect", addr, blob_in],
                                       capture_output=True, timeout=5)
                        subprocess.run(["aconnect", blob_fb, addr],
                                       capture_output=True, timeout=5)
                        label = name.split(":", 1)[1]
                        with self.lock:
                            self._sep(f"device wired: {label}")
                            is_rec  = (self.mode == "RECORDING")
                            is_play = (self.mode in ("PLAYING", "PAUSED"))
                        with self.lock:
                            is_loop = self.loop_mode
                        self._send_cc(CC_RECORD,    127 if is_rec  else 0, fb_only=True)
                        self._send_cc(CC_PLAY,      127 if is_play else 0, fb_only=True)
                        self._send_cc(CC_LOOP,      127 if is_loop else 0, fb_only=True)
                        self._send_cc(CC_CONNECTED, 127, fb_only=True)
                        wired.add(addr)

                # Forget ports that have disappeared
                current = set(devices.values())
                gone    = wired - current
                for addr in gone:
                    with self.lock:
                        self._sep(f"device disconnected: {addr}")
                wired -= gone

                with self.lock:
                    self._wired_count = len(current & wired)
            except Exception:
                pass

    def _heartbeat_loop(self):
        """Send CC_CONNECTED=127 every 3 s while devices are wired; lets TouchOSC
        show a live green indicator.  The indicator goes grey if the Pi drops."""
        while True:
            time.sleep(3)
            with self.lock:
                cnt = self._wired_count
            if cnt > 0:
                self._send_cc(CC_CONNECTED, 127, fb_only=True)

    def _reconnect_out_loop(self):
        """Background: reopen mid_out when M4 disconnects (USB power cycle)."""
        while True:
            time.sleep(2)
            if not self._out_needs_reconnect:
                continue
            try:
                new_dev = rtmidi.MidiOut()
                ports   = new_dev.get_ports()
                for kw in self._out_keywords:
                    for i, p in enumerate(ports):
                        if kw in p.lower():
                            new_dev.open_port(i)
                            old = self.mid_out
                            self.mid_out  = new_dev
                            self.out_name = p
                            self._out_needs_reconnect = False
                            with self.lock:
                                self._sep(f"OUT reconnected: {p}")
                            try:
                                old.close_port()
                            except Exception:
                                pass
                            raise StopIteration   # break both loops
                        continue
            except StopIteration:
                pass
            except Exception:
                pass

    def _pick_port(self, dev, is_out, explicit=None, name_hint=None):
        ports = dev.get_ports()
        label = "Output (hardware/Feather)" if is_out else "Input (TouchOSC/IAC)"

        if explicit is not None:
            if explicit >= len(ports):
                raise SystemExit(f"Port index {explicit} out of range (0–{len(ports)-1})")
            dev.open_port(explicit)
            return ports[explicit]

        if name_hint is not None:
            keywords = [k.strip().lower() for k in name_hint.split(",")]
            # Try keywords in priority order: first keyword that matches any port wins.
            # This prevents a low-priority fallback (e.g. "midi through") from
            # shadowing a higher-priority device that appears later in the port list.
            for kw in keywords:
                for i, p in enumerate(ports):
                    if kw in p.lower():
                        dev.open_port(i)
                        return p
            raise SystemExit(f"No port matching '{name_hint}' found in: {ports}")

        # Auto-detect: output → hardware; input → TouchOSC/rtpmidid routing bus.
        if is_out:
            wanted = ("feather", "m4", "samd", "widi", "cme", "fighter", "twister")
        else:
            wanted = ("network export", "network blob", "touchosc", "network session", "iac")

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

    def _send_cc(self, cc, val, fb_only=False):
        val = int(val) & 0x7F
        if not fb_only:
            try:
                self.mid_out.send_message([0xB0 | MIDI_CH, cc, val])
            except Exception:
                self._out_needs_reconnect = True
        if self.mid_fb:
            try:
                self.mid_fb.send_message([0xB0 | MIDI_CH_FB, cc, val])
            except Exception:
                pass
        self._send_osc_feedback(cc, val)

    def _halt_all(self):
        """Send center-value (64) to every servo CC 4× with 50 ms gaps.
        Value 64 = midpoint = zero speed on M4; repeated sends overcome any
        lost packets and ensure all 9 servos actually stop."""
        for _ in range(4):
            for scc in SERVO_CCS:
                try:
                    self.mid_out.send_message([0xB0 | MIDI_CH,    scc, 64])
                except Exception:
                    self._out_needs_reconnect = True
                if self.mid_fb:
                    try:
                        self.mid_fb.send_message([0xB0 | MIDI_CH_FB, scc, 64])
                    except Exception:
                        pass
            time.sleep(0.05)

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
        if cc == CC_HALT and val > 0:
            with self.lock:
                self._append_log("  btn  ", f"ch{ch} HALT ALL", cc, val)
            threading.Thread(target=self._halt_all, daemon=True).start()
            return

        name = CC_NAMES.get(cc, f"CC{cc}")
        now  = time.time()
        # Live passthrough: forward to M4 normalized to MIDI_CH (M4 expects ch1 for servos)
        try:
            fwd    = list(msg[:3])
            fwd[0] = 0xB0 | MIDI_CH   # normalize channel; iPad may send ch2
            self.mid_out.send_message(fwd)
        except Exception:
            self._out_needs_reconnect = True
        with self.lock:
            if self.mode == "RECORDING":
                t = now - self.rec_start
                self.events.append({"t": t, "cc": cc, "val": val})
                t_str = f"{t:7.3f}s"
            else:
                t_str = "       s"
            self._append_log(t_str, f"ch{ch} {name}", cc, val)
            if cc in (16, 17, 18, 20, 21, 22, 24, 25, 26):
                self._last_servo_cc  = cc
                self._last_servo_val = val

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
        self._send_cc(CC_RECORD, 127, fb_only=True)   # confirm REC on
        self._send_cc(CC_PLAY,   0,   fb_only=True)   # mutual exclusion: PLAY off

    def _stop_record(self):
        with self.lock:
            if self.mode != "RECORDING":
                return
            self.mode         = "IDLE"
            self.rec_duration = time.time() - self.rec_start
            evs = list(self.events)
            self._sep("─── REC STOP  ───")
        self._save(evs)

    def _start_play(self):
        evs_to_save = None
        old_thr     = None
        with self.lock:
            prev_mode = self.mode
            if self.mode == "RECORDING":
                evs_to_save       = list(self.events)
                self.rec_duration = time.time() - self.rec_start
                self.mode         = "IDLE"
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
        self._send_cc(CC_RECORD, 0,   fb_only=True)   # mutual exclusion: REC off
        self._send_cc(CC_PLAY,   127, fb_only=True)   # confirm PLAY on
        with self.lock:
            self.loop_mode = True
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
            has_events = bool(self.events)
        if not has_events:
            if shutil.which("rclone"):
                threading.Thread(target=self._gdrive_sync_and_play,
                                 daemon=True).start()
                return
            self.load_latest()
        self._do_launch_play()

    def _gdrive_sync_and_play(self):
        with self.lock:
            self._sep("Syncing Drive...")
        try:
            r = subprocess.run(["rclone", "copy", "gdrive:", str(REC_DIR)],
                               capture_output=True, text=True, timeout=30)
            with self.lock:
                if r.returncode == 0:
                    self._sep("← Drive: synced")
                else:
                    self._sep(f"Drive err: {r.stderr.strip()[:50]}")
        except Exception as e:
            with self.lock:
                self._sep(f"Drive err: {e}")
        self.load_latest()
        self._do_launch_play()

    def _do_launch_play(self):
        with self.lock:
            if not self.events:
                self._sep("(nothing to play)")
                return
            self.stop_evt.clear()
            self.mode     = "PLAYING"
            self.play_pos = 0.0
            evs = list(self.events)
            dur = self.rec_duration
            self._sep("─── PLAYBACK  ───")
        self._play_thr = threading.Thread(
            target=self._play_fn, args=(evs, dur), daemon=True)
        self._play_thr.start()

    # ── Playback thread ────────────────────────────────────────────────────

    def _play_fn(self, events, duration):
        while True:
            wall         = time.time()
            paused_total = 0.0
            pause_wall   = None
            i            = 0
            while not self.stop_evt.is_set():
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
                if i < len(events) and elapsed >= events[i]["t"]:
                    e = events[i]
                    self._send_cc(e["cc"], e["val"])
                    i += 1
                elif i >= len(events) and elapsed >= duration:
                    break   # all events fired and full duration elapsed
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
                self._send_cc(CC_PLAY, 0, fb_only=True)
                self._send_cc(CC_LOOP, 0, fb_only=True)
            break

    # ── File I/O ───────────────────────────────────────────────────────────

    def _save(self, events):
        try:
            REC_DIR.mkdir(exist_ok=True)
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            fn  = REC_DIR / f"blob_{ts}.mid"
            mid = events_to_midi(events, self.rec_duration)
            mid.save(str(fn))
            mid.save(str(REC_DIR / "latest.mid"))
            with self.lock:
                self.filename = str(fn)
                self._sep(f"Saved {fn.name} ({len(events)} events)")
            import shutil
            if shutil.which("rclone"):
                threading.Thread(target=self._gdrive_upload, args=(fn,),
                                 daemon=True).start()
        except Exception as e:
            with self.lock:
                self._sep(f"SAVE ERR: {e}")

    def _gdrive_startup_sync(self):
        try:
            r = subprocess.run(["rclone", "copy", "gdrive:", str(REC_DIR)],
                               capture_output=True, text=True, timeout=60)
            with self.lock:
                if r.returncode == 0:
                    self._sep("← Drive: startup sync done")
                else:
                    self._sep(f"Drive sync err: {r.stderr.strip()[:50]}")
        except Exception as e:
            with self.lock:
                self._sep(f"Drive sync err: {e}")

    def _gdrive_upload(self, path):
        try:
            r = subprocess.run(["rclone", "copy", str(path), "gdrive:"],
                               capture_output=True, text=True, timeout=60)
            with self.lock:
                if r.returncode == 0:
                    self._sep(f"→ Drive: {Path(path).name}")
                else:
                    self._sep(f"Drive err: {r.stderr.strip()[:50]}")
        except Exception as e:
            with self.lock:
                self._sep(f"Drive err: {e}")

    def load_latest(self):
        files = sorted(REC_DIR.glob("blob_*.mid"))
        if not files:
            with self.lock:
                self._sep("No recordings found in recordings/")
            return
        fn = files[-1]
        try:
            events, dur = midi_to_events(mido.MidiFile(str(fn)))
        except Exception as e:
            with self.lock:
                self._sep(f"LOAD ERR: {e}")
            return
        with self.lock:
            self.events       = events
            self.rec_duration = dur
            self.filename     = str(fn)
            self._sep(f"Loaded {fn.name} ({len(events)} events)")

    def close(self):
        self.stop_evt.set()
        self._send_cc(CC_CONNECTED, 0, fb_only=True)   # tell iPad Pi is offline
        time.sleep(0.05)
        self.mid_in.close_port()
        self.mid_out.close_port()
        if self.mid_fb:
            self.mid_fb.close_port()


def _gdrive_periodic_sync(mon):
    """Background Drive → Pi sync every 5 minutes (headless mode)."""
    while True:
        time.sleep(300)
        try:
            r = subprocess.run(["rclone", "copy", "gdrive:", str(REC_DIR)],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                with mon.lock:
                    mon._sep("← Drive: periodic sync")
        except Exception:
            pass


def pick_file_ui(scr, rec_dir):
    """Modal curses file browser. Syncs Drive first, returns selected Path or None."""
    curses.curs_set(0)
    h, w = scr.getmaxyx()

    # Sync Drive before showing list
    if shutil.which("rclone"):
        scr.erase()
        try:
            scr.addstr(0, 0, "Syncing from Drive...", curses.A_BOLD)
        except curses.error:
            pass
        scr.refresh()
        try:
            subprocess.run(["rclone", "copy", "gdrive:", str(rec_dir)],
                           capture_output=True, timeout=20)
        except Exception:
            pass

    files = sorted(rec_dir.glob("blob_*.mid"), reverse=True)
    if not files:
        scr.erase()
        try:
            scr.addstr(0, 0, "No recordings found.  Press any key.", curses.A_BOLD)
        except curses.error:
            pass
        scr.refresh()
        scr.getch()
        return None

    sel = 0
    while True:
        scr.erase()
        h, w = scr.getmaxyx()
        try:
            scr.addstr(0, 0,
                       "LOAD FILE   ↑↓ navigate   Enter select   Esc cancel",
                       curses.A_BOLD)
            scr.addstr(1, 0, "─" * min(w - 1, 60))
        except curses.error:
            pass

        vis_h  = h - 4
        start  = max(0, sel - vis_h + 1)
        for i, f in enumerate(files[start:start + vis_h]):
            row = i + 2
            if row >= h - 1:
                break
            idx = start + i
            try:
                dt    = datetime.strptime(f.stem, "blob_%Y%m%d_%H%M%S")
                label = dt.strftime("%Y-%m-%d  %H:%M:%S")
            except ValueError:
                label = f.stem
            kb   = f.stat().st_size // 1024
            line = f"  {label}   {kb} KB"
            attr = curses.A_REVERSE if idx == sel else 0
            try:
                scr.addstr(row, 0, line[:w - 1], attr)
            except curses.error:
                pass

        try:
            scr.addstr(h - 1, 0, f"  {sel + 1} / {len(files)}")
        except curses.error:
            pass
        scr.refresh()

        key = scr.getch()
        if key == curses.KEY_UP and sel > 0:
            sel -= 1
        elif key == curses.KEY_DOWN and sel < len(files) - 1:
            sel += 1
        elif key == curses.KEY_PPAGE:
            sel = max(0, sel - vis_h)
        elif key == curses.KEY_NPAGE:
            sel = min(len(files) - 1, sel + vis_h)
        elif key in (10, 13, curses.KEY_ENTER):
            return files[sel]
        elif key == 27:   # Escape
            return None


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
    put(3, 0, f" FB : {mon.fb_name or '(none)'}")
    put(4, 0, "─" * W)

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
    put(5, 0, status, mode_clr)

    # timeline bar (row 6)
    bar_w = W - 18
    if bar_w > 5:
        if events:
            frac   = min(pos / dur, 1.0) if dur > 0 else 0.0
            filled = int(frac * bar_w)
            bar    = "█" * filled + "░" * (bar_w - filled)
            m_p, s_p = divmod(int(pos), 60)
            m_d, s_d = divmod(int(dur), 60)
            put(6, 0, f" [{bar}] {m_p:02d}:{s_p:02d}/{m_d:02d}:{s_d:02d}")
        else:
            put(6, 0, f" [{'─' * bar_w}]  (no recording)")

    if filename:
        put(7, 0, f" {Path(filename).name}", YELLOW)

    put(8, 0, "─" * W)

    # event log
    log_top = 9
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
            selected = pick_file_ui(scr, REC_DIR)
            if selected:
                try:
                    events, dur = midi_to_events(mido.MidiFile(str(selected)))
                    with mon.lock:
                        mon.events       = events
                        mon.rec_duration = dur
                        mon.filename     = str(selected)
                        mon._sep(f"Loaded {selected.name} ({len(events)} events)")
                except Exception as e:
                    with mon.lock:
                        mon._sep(f"LOAD ERR: {e}")
        elif key in (ord("o"), ord("O")):
            with mon.lock:
                mon.loop_mode = not mon.loop_mode
        draw_ui(scr, mon, colors)


def main():
    ap = argparse.ArgumentParser(description="Blob MIDI Monitor")
    ap.add_argument("--list", action="store_true",
                    help="List all MIDI ports and exit")
    ap.add_argument("--in",       dest="in_port",  type=int, default=None,
                    help="Input port index (overrides auto-detect)")
    ap.add_argument("--out",      dest="out_port", type=int, default=None,
                    help="Output port index (overrides auto-detect)")
    ap.add_argument("--in-name",  dest="in_name",  default=None,
                    help="Input port name substring (comma-separated, first match wins)")
    ap.add_argument("--out-name", dest="out_name", default=None,
                    help="Output port name substring (comma-separated, first match wins)")
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
    mon  = BlobMonitor(in_port=args.in_port, out_port=args.out_port,
                       in_name=args.in_name, out_name=args.out_name)
    oled = OledDisplay(mon)

    print(f"\n IN : {mon.in_name}")
    print(f" OUT: {mon.out_name}")
    print(f" FB : {mon.fb_name or '(none)'}")
    print(f" OLED: {'yes' if oled.dev else 'not found'}")

    headless = not sys.stdin.isatty()
    if headless:
        print("Running headless (no TTY) — OLED + MIDI only.")
        if shutil.which("rclone"):
            threading.Thread(target=_gdrive_periodic_sync, args=(mon,),
                             daemon=True).start()
        oled.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            oled.show_message("BLOB MONITOR", "stopped")
            mon.close()
    else:
        print()
        print(" NOTE: TouchOSC must send MIDI to the IN port above.")
        time.sleep(2)
        oled.start()
        try:
            curses.wrapper(run_ui, mon)
        finally:
            oled.show_message("BLOB MONITOR", "stopped")
            mon.close()
        print(f"\nRecordings saved in: {REC_DIR}/")


if __name__ == "__main__":
    main()

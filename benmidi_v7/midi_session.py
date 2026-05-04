#!/usr/bin/env python3
"""
midi_session.py  —  record and play back MIDI for the servo art piece

  capture: records from any single MIDI device — use this when only the
           Feather (test sketch) is connected, no Twister needed

  record:  captures knob movements from the Twister, forwards live to the
           Feather for real-time servo control, routes LED feedback
           Feather → Twister, saves everything to a .mid file

  play:    reads a .mid file, sends it to the Feather with correct timing,
           routes LED feedback Feather → Twister throughout

The saved .mid file can be opened in GarageBand or any DAW for graphical
editing. Export back to .mid and play with this script.

Usage:
    python3 midi_session.py capture [output.mid]
    python3 midi_session.py record [output.mid]
    python3 midi_session.py play <file.mid> [--loop] [--slow <N>] [--speed <multiplier>]

Examples:
    python3 midi_session.py capture test.mid           # Feather only
    python3 midi_session.py record session1.mid        # Twister + Feather
    python3 midi_session.py play session1.mid
    python3 midi_session.py play session1.mid --loop
    python3 midi_session.py play session1.mid --slow 10     # 10x slower
    python3 midi_session.py play session1.mid --slow 50     # 50x slower
    python3 midi_session.py play session1.mid --slow 20 --loop
"""

import sys
import time
import threading
import rtmidi
import mido

TICKS_PER_BEAT = 480
DEFAULT_TEMPO  = 500000   # 120 BPM
NOTE_DURATION  = 120      # ticks — short staccato note for audio preview


# ── port detection ────────────────────────────────────────────────────────────

def list_ports():
    ins  = rtmidi.MidiIn().get_ports()
    outs = rtmidi.MidiOut().get_ports()
    return ins, outs

def find_port(ports, keywords):
    for i, name in enumerate(ports):
        if any(k.lower() in name.lower() for k in keywords):
            return i, name
    return None, None

def pick(ports, keywords, label):
    idx, name = find_port(ports, keywords)
    if idx is None:
        for i, p in enumerate(ports):
            print(f"    {i}: {p}")
        idx  = int(input(f"  {label} port index: "))
        name = ports[idx]
    print(f"  {label:12s}: {name}")
    return idx

def open_in(idx):
    m = rtmidi.MidiIn()
    m.open_port(idx)
    m.ignore_types(sysex=False, timing=False, active_sense=True)
    return m

def open_out(idx):
    m = rtmidi.MidiOut()
    m.open_port(idx)
    return m

def save_midi(filename, captured):
    """
    Save captured events to a type-1 .mid file:
      Track 0: tempo map
      Track 1: CC data — used by run_session.sh play for servo control
      Tracks 2-10: one note track per knob (CC 0-8) for GarageBand audio preview
        - note pitch  = CC value (0-127) → shows servo position in piano roll
        - note velocity = 100 (fixed)
        - separate track per knob so GarageBand creates one instrument track each
    """
    from collections import defaultdict

    mid           = mido.MidiFile(type=1, ticks_per_beat=TICKS_PER_BEAT)
    secs_per_tick = DEFAULT_TEMPO / 1_000_000 / TICKS_PER_BEAT

    # ── track 0: tempo map (required for type-1) ──
    tempo_track = mido.MidiTrack()
    mid.tracks.append(tempo_track)
    tempo_track.append(mido.MetaMessage('set_tempo', tempo=DEFAULT_TEMPO, time=0))

    # ── track 1: CC data ──
    cc_track = mido.MidiTrack()
    mid.tracks.append(cc_track)
    cc_track.append(mido.MetaMessage('track_name', name='Servo CC', time=0))
    prev_tick = 0
    for t, msg in captured:
        tick  = int(t / secs_per_tick)
        delta = max(0, tick - prev_tick)
        prev_tick = tick
        status = msg[0] & 0xF0
        ch     = msg[0] & 0x0F
        if status == 0xB0:
            cc_track.append(mido.Message('control_change', channel=ch,
                                         control=msg[1], value=msg[2], time=delta))
        elif status == 0x90:
            cc_track.append(mido.Message('note_on',  channel=ch,
                                         note=msg[1], velocity=msg[2], time=delta))
        elif status == 0x80:
            cc_track.append(mido.Message('note_off', channel=ch,
                                         note=msg[1], velocity=msg[2], time=delta))

    # ── tracks 2-10: one note track per knob ──
    # Collect (abs_tick, note_on), (abs_tick + NOTE_DURATION, note_off) per knob
    knob_events = defaultdict(list)
    for t, msg in captured:
        if (msg[0] & 0xF0) != 0xB0:
            continue
        cc, val = msg[1], msg[2]
        if cc > 8 or val == 0:
            continue
        abs_tick = int(t / secs_per_tick)
        note     = max(1, val)   # pitch = servo value so height = speed
        knob_events[cc].append((abs_tick,                'on',  note))
        knob_events[cc].append((abs_tick + NOTE_DURATION,'off', note))

    for cc in range(9):
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.MetaMessage('track_name', name=f'Knob {cc + 1}', time=0))
        events = sorted(knob_events.get(cc, []), key=lambda e: e[0])
        prev_tick = 0
        for abs_tick, kind, note in events:
            delta = max(0, abs_tick - prev_tick)
            prev_tick = abs_tick
            if kind == 'on':
                track.append(mido.Message('note_on',  channel=cc, note=note,
                                          velocity=100, time=delta))
            else:
                track.append(mido.Message('note_off', channel=cc, note=note,
                                          velocity=0,   time=delta))

    mid.save(filename)
    print(f"\nSaved {len(captured)} messages → {filename}")
    print(f"  Track 1 : Servo CC data (playback)")
    print(f"  Tracks 2-10: Knob 1-9 audio preview (note height = servo position)")


def close_all(*ports):
    for p in ports:
        try:
            p.close_port()
        except Exception:
            pass


# ── LED router ────────────────────────────────────────────────────────────────

def start_led_router(feather_in, twister_out):
    """Route LED feedback from Feather → Twister in background."""
    def on_led(event, _):
        msg, _ = event
        twister_out.send_message(msg)
        if (msg[0] & 0xF0) == 0xB0:
            print(f"  [LED ] Ch{(msg[0] & 0x0F) + 1}  CC{msg[1]:3d} = {msg[2]:3d}  → Twister")
    feather_in.set_callback(on_led)


# ── capture ───────────────────────────────────────────────────────────────────

def choose_port(ports, keywords, label):
    """Auto-detect by keyword or show a numbered list to pick from."""
    idx, name = find_port(ports, keywords)
    if idx is not None:
        return idx, name
    print(f"\n  Could not auto-detect {label}. Available options:")
    for i, p in enumerate(ports):
        print(f"    {i}: {p}")
    idx  = int(input(f"  Pick {label} port number: "))
    return idx, ports[idx]


def capture(filename):
    """
    Smart capture — auto-detects what's connected:
      Twister/WIDI + Feather: records from Twister (or WIDI), forwards live
                              to Feather for servo control, routes LED
                              feedback Feather → Twister/WIDI
      Feather only:           records directly from Feather (test sketch mode)

    WIDI is detected automatically. If a device isn't found by name you'll
    be shown a numbered list to pick from.
    """
    ins, outs = list_ports()

    # Twister can arrive directly (USB) or via WIDI/CME (wireless)
    TWISTER_KEYS = ["twister", "fighter", "widi", "cme"]
    FEATHER_KEYS = ["feather", "m4", "samd"]

    print("\nDetecting MIDI ports...")
    print("  Inputs:  " + ", ".join(f"{i}:{p}" for i, p in enumerate(ins)))
    print("  Outputs: " + ", ".join(f"{i}:{p}" for i, p in enumerate(outs)))
    print()

    feather_in_idx,  feather_in_name  = find_port(ins,  FEATHER_KEYS)
    feather_out_idx, feather_out_name = find_port(outs, FEATHER_KEYS)
    twister_in_idx,  twister_in_name  = find_port(ins,  TWISTER_KEYS)
    twister_out_idx, twister_out_name = find_port(outs, TWISTER_KEYS)

    feather_present = feather_in_idx is not None and feather_out_idx is not None
    twister_present = twister_in_idx is not None

    if feather_present and twister_present:
        # Full pipeline — but confirm or let user override
        print(f"  Twister/WIDI in : {twister_in_name}")
        print(f"  Feather out     : {feather_out_name}  (servo control)")
        print(f"  Feather in      : {feather_in_name}   (LED feedback)")
        if twister_out_idx is not None:
            print(f"  Twister/WIDI out: {twister_out_name}  (LED rings)")
        else:
            print(f"  Twister/WIDI out: not found — LED rings will not update")
            twister_out_idx, twister_out_name = choose_port(outs, TWISTER_KEYS,
                                                             "Twister/WIDI output")

        source      = open_in (twister_in_idx)
        feather_out = open_out(feather_out_idx)
        feather_in  = open_in (feather_in_idx)
        twister_out = open_out(twister_out_idx)
        start_led_router(feather_in, twister_out)
        extra_ports = [feather_out, feather_in, twister_out]

    elif feather_present:
        # Feather only — test sketch mode
        print(f"  No Twister/WIDI found — capturing from Feather only")
        print(f"  Feather in: {feather_in_name}")
        source      = open_in(feather_in_idx)
        feather_out = None
        extra_ports = []

    else:
        # Nothing auto-detected — ask for everything
        print("  Nothing auto-detected. Please select ports manually:")
        src_idx, src_name = choose_port(ins, [], "recording source (Twister or WIDI)")
        dst_idx, dst_name = choose_port(outs, [], "Feather output")
        fb_idx,  fb_name  = choose_port(ins,  [], "Feather input (LED feedback)")
        led_idx, led_name = choose_port(outs, [], "Twister/WIDI output (LED rings)")
        print()
        source      = open_in (src_idx)
        feather_out = open_out(dst_idx)
        feather_in  = open_in (fb_idx)
        twister_out = open_out(led_idx)
        start_led_router(feather_in, twister_out)
        extra_ports = [feather_out, feather_in, twister_out]

    captured   = []
    start_time = [None]
    lock       = threading.Lock()

    def on_msg(event, _):
        msg, _ = event
        now = time.time()
        if start_time[0] is None:
            start_time[0] = now
        elapsed = now - start_time[0]
        with lock:
            captured.append((elapsed, list(msg)))
        if feather_out:
            feather_out.send_message(msg)
        if (msg[0] & 0xF0) == 0xB0:
            print(f"  [CAP ] Ch{(msg[0] & 0x0F) + 1}  CC{msg[1]:3d} = {msg[2]:3d}")

    source.set_callback(on_msg)

    print(f"\nRecording to {filename}")
    print("Ctrl+C to stop and save.\n")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    with lock:
        save_midi(filename, captured)
    close_all(source, *extra_ports)


# ── record ────────────────────────────────────────────────────────────────────

def record(filename):
    ins, outs = list_ports()

    print("\nDetecting MIDI ports...")
    twister_in_idx  = pick(ins,  ["twister", "fighter"],   "Twister in ")
    twister_out_idx = pick(outs, ["twister", "fighter"],   "Twister out")
    feather_out_idx = pick(outs, ["feather", "m4", "samd"],"Feather out")
    feather_in_idx  = pick(ins,  ["feather", "m4", "samd"],"Feather in ")
    print()

    twister_in  = open_in (twister_in_idx)
    twister_out = open_out(twister_out_idx)
    feather_out = open_out(feather_out_idx)
    feather_in  = open_in (feather_in_idx)

    start_led_router(feather_in, twister_out)

    captured   = []   # [(abs_time_secs, [status, b1, b2])]
    start_time = [None]
    lock       = threading.Lock()

    def on_twister(event, _):
        msg, _ = event
        now = time.time()
        if start_time[0] is None:
            start_time[0] = now
        elapsed = now - start_time[0]
        with lock:
            captured.append((elapsed, list(msg)))
        feather_out.send_message(msg)
        if (msg[0] & 0xF0) == 0xB0:
            print(f"  [REC ] Ch{(msg[0] & 0x0F) + 1}  CC{msg[1]:3d} = {msg[2]:3d}")

    twister_in.set_callback(on_twister)

    print(f"Recording to {filename}")
    print("Turn knobs... Ctrl+C to stop and save.\n")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    with lock:
        save_midi(filename, captured)
    close_all(twister_in, twister_out, feather_out, feather_in)


# ── play ──────────────────────────────────────────────────────────────────────

def play(filename, loop=False, speed=1.0):
    ins, outs = list_ports()

    TWISTER_KEYS = ["twister", "fighter", "widi", "cme"]
    FEATHER_KEYS = ["feather", "m4", "samd"]

    print("\nDetecting MIDI ports...")
    print("  Inputs:  " + ", ".join(f"{i}:{p}" for i, p in enumerate(ins)))
    print("  Outputs: " + ", ".join(f"{i}:{p}" for i, p in enumerate(outs)))
    print()

    feather_out_idx, feather_out_name = choose_port(outs, FEATHER_KEYS, "Feather output")
    feather_in_idx,  feather_in_name  = choose_port(ins,  FEATHER_KEYS, "Feather input")
    print(f"  Feather out : {feather_out_name}")
    print(f"  Feather in  : {feather_in_name}")

    twister_out_idx, twister_out_name = find_port(outs, TWISTER_KEYS)
    if twister_out_idx is not None:
        print(f"  Twister/WIDI: {twister_out_name}  (LED rings)")
    else:
        print(f"  Twister/WIDI: not found — LED rings will not update")
    print()

    feather_out = open_out(feather_out_idx)
    feather_in  = open_in (feather_in_idx)

    if twister_out_idx is not None:
        twister_out = open_out(twister_out_idx)
        start_led_router(feather_in, twister_out)
    else:
        twister_out = None

    mid    = mido.MidiFile(filename)
    n_msgs = sum(1 for t in mid.tracks for m in t if not m.is_meta)
    if speed == 1.0:
        speed_str = ""
    elif speed < 1.0:
        speed_str = f"  [{1/speed:.4g}x slower]"
    else:
        speed_str = f"  [{speed:.4g}x faster]"
    print(f"Playing {filename}  ({n_msgs} messages){'  [loop]' if loop else ''}{speed_str}")
    print("Ctrl+C to stop.\n")

    try:
        while True:
            for msg in mid:
                if msg.is_meta:
                    continue
                if msg.time > 0:
                    time.sleep(msg.time / speed)
                raw    = msg.bytes()
                status = raw[0] & 0xF0
                if status in (0xB0, 0xB1):   # CC only — note events stay in file for GarageBand, never sent to Feather
                    feather_out.send_message(raw)
                    print(f"  [PLAY] Ch{(raw[0] & 0x0F) + 1}  CC{raw[1]:3d} = {raw[2]:3d}  → Feather")
            if not loop:
                break
            print("  [loop]\n")
    except KeyboardInterrupt:
        pass

    print("\nDone.")
    ports_to_close = [feather_out, feather_in]
    if twister_out:
        ports_to_close.append(twister_out)
    close_all(*ports_to_close)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('capture', 'record', 'play'):
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'capture':
        filename = sys.argv[2] if len(sys.argv) > 2 else 'session.mid'
        capture(filename)

    elif cmd == 'record':
        filename = sys.argv[2] if len(sys.argv) > 2 else 'session.mid'
        record(filename)

    elif cmd == 'play':
        if len(sys.argv) < 3:
            print("Usage: python3 midi_session.py play <file.mid> [--loop] [--speed 0.5]")
            sys.exit(1)
        speed = 1.0
        if '--slow' in sys.argv:
            speed = 1.0 / float(sys.argv[sys.argv.index('--slow') + 1])
        elif '--speed' in sys.argv:
            speed = float(sys.argv[sys.argv.index('--speed') + 1])
        play(sys.argv[2], loop='--loop' in sys.argv, speed=speed)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
midi_session.py  —  record and play back MIDI for the servo art piece

  record:  captures knob movements from the Twister, forwards live to the
           Feather for real-time servo control, routes LED feedback
           Feather → Twister, saves everything to a .mid file

  play:    reads a .mid file, sends it to the Feather with correct timing,
           routes LED feedback Feather → Twister throughout

The saved .mid file can be opened in GarageBand, Logic Pro, Reaper, or any
DAW for graphical editing. Export back to .mid and play with this script.

Usage:
    python3 midi_session.py record [output.mid]
    python3 midi_session.py play <file.mid> [--loop]

Examples:
    python3 midi_session.py record session1.mid
    python3 midi_session.py play session1.mid
    python3 midi_session.py play session1.mid --loop
"""

import sys
import time
import threading
import rtmidi
import mido

TICKS_PER_BEAT = 480
DEFAULT_TEMPO  = 500000   # 120 BPM


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

    # ── write .mid file ──
    mid   = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=DEFAULT_TEMPO, time=0))

    secs_per_tick = DEFAULT_TEMPO / 1_000_000 / TICKS_PER_BEAT
    prev_tick = 0

    with lock:
        for t, msg in captured:
            tick  = int(t / secs_per_tick)
            delta = max(0, tick - prev_tick)
            prev_tick = tick
            status = msg[0] & 0xF0
            ch     = msg[0] & 0x0F
            if status == 0xB0:
                track.append(mido.Message('control_change', channel=ch,
                                          control=msg[1], value=msg[2], time=delta))
            elif status == 0x90:
                track.append(mido.Message('note_on', channel=ch,
                                          note=msg[1], velocity=msg[2], time=delta))
            elif status == 0x80:
                track.append(mido.Message('note_off', channel=ch,
                                          note=msg[1], velocity=msg[2], time=delta))

    mid.save(filename)
    print(f"\nSaved {len(captured)} messages → {filename}")
    close_all(twister_in, twister_out, feather_out, feather_in)


# ── play ──────────────────────────────────────────────────────────────────────

def play(filename, loop=False):
    ins, outs = list_ports()

    print("\nDetecting MIDI ports...")
    twister_out_idx = pick(outs, ["twister", "fighter"],   "Twister out")
    feather_out_idx = pick(outs, ["feather", "m4", "samd"],"Feather out")
    feather_in_idx  = pick(ins,  ["feather", "m4", "samd"],"Feather in ")
    print()

    twister_out = open_out(twister_out_idx)
    feather_out = open_out(feather_out_idx)
    feather_in  = open_in (feather_in_idx)

    start_led_router(feather_in, twister_out)

    mid    = mido.MidiFile(filename)
    n_msgs = sum(1 for t in mid.tracks for m in t if not m.is_meta)
    print(f"Playing {filename}  ({n_msgs} messages){'  [loop]' if loop else ''}")
    print("Ctrl+C to stop.\n")

    try:
        while True:
            for msg in mid.play():
                if msg.is_meta:
                    continue
                raw = msg.bytes()
                feather_out.send_message(raw)
                if (raw[0] & 0xF0) == 0xB0:
                    print(f"  [PLAY] Ch{(raw[0] & 0x0F) + 1}  CC{raw[1]:3d} = {raw[2]:3d}  → Feather")
            if not loop:
                break
            print("  [loop]\n")
    except KeyboardInterrupt:
        pass

    print("\nDone.")
    close_all(twister_out, feather_out, feather_in)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('record', 'play'):
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'record':
        filename = sys.argv[2] if len(sys.argv) > 2 else 'session.mid'
        record(filename)

    elif cmd == 'play':
        if len(sys.argv) < 3:
            print("Usage: python3 midi_session.py play <file.mid> [--loop]")
            sys.exit(1)
        play(sys.argv[2], loop='--loop' in sys.argv)


if __name__ == '__main__':
    main()

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
    python3 midi_session.py play <file.mid> [--loop]

Examples:
    python3 midi_session.py capture test.mid        # Feather only
    python3 midi_session.py record session1.mid     # Twister + Feather
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
NOTE_DURATION  = 120      # ticks — short staccato note for audio preview

# CC 0-8 → musical notes C4 through D5 so each knob has a distinct pitch
CC_TO_NOTE = {0:60, 1:62, 2:64, 3:65, 4:67, 5:69, 6:71, 7:72, 8:74}


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
    Save captured events to a .mid file with two tracks:
      Track 0 (CC data)    — used by run_session.sh play for servo control
      Track 1 (note data)  — used by GarageBand for audio preview
    """
    mid   = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    secs_per_tick = DEFAULT_TEMPO / 1_000_000 / TICKS_PER_BEAT

    # ── track 0: CC messages ──
    cc_track = mido.MidiTrack()
    mid.tracks.append(cc_track)
    cc_track.append(mido.MetaMessage('set_tempo', tempo=DEFAULT_TEMPO, time=0))
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
            cc_track.append(mido.Message('note_on', channel=ch,
                                         note=msg[1], velocity=msg[2], time=delta))
        elif status == 0x80:
            cc_track.append(mido.Message('note_off', channel=ch,
                                         note=msg[1], velocity=msg[2], time=delta))

    # ── track 1: note preview (so GarageBand has audio to play) ──
    note_track = mido.MidiTrack()
    mid.tracks.append(note_track)
    note_track.append(mido.MetaMessage('set_tempo', tempo=DEFAULT_TEMPO, time=0))
    note_track.append(mido.MetaMessage('track_name', name='Preview (audio)', time=0))
    prev_tick = 0
    for t, msg in captured:
        if (msg[0] & 0xF0) != 0xB0:
            continue
        cc  = msg[1]
        val = msg[2]
        if cc not in CC_TO_NOTE or val == 0:
            continue
        note     = CC_TO_NOTE[cc]
        velocity = max(1, val)
        tick     = int(t / secs_per_tick)
        on_delta = max(0, tick - prev_tick)
        note_track.append(mido.Message('note_on',  note=note, velocity=velocity, time=on_delta))
        note_track.append(mido.Message('note_off', note=note, velocity=0,        time=NOTE_DURATION))
        prev_tick = tick + NOTE_DURATION

    mid.save(filename)
    print(f"\nSaved {len(captured)} messages → {filename}")
    print(f"  Track 0: CC data (servo playback)")
    print(f"  Track 1: Note preview (open in GarageBand to hear)")


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


# ── capture (single device, no routing) ──────────────────────────────────────

def capture(filename):
    """Record from any single MIDI device — no Twister or routing needed."""
    ins, _ = list_ports()

    print("\nAvailable MIDI inputs:")
    for i, p in enumerate(ins):
        print(f"  {i}: {p}")
    idx, name = find_port(ins, ["feather", "m4", "samd", "twister", "fighter"])
    if idx is None:
        idx  = int(input("\nPick input port index: "))
        name = ins[idx]
    print(f"\nCapturing from: {name}")

    source = open_in(idx)

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
        if (msg[0] & 0xF0) == 0xB0:
            print(f"  [CAP ] Ch{(msg[0] & 0x0F) + 1}  CC{msg[1]:3d} = {msg[2]:3d}")

    source.set_callback(on_msg)

    print(f"Recording to {filename}")
    print("Ctrl+C to stop and save.\n")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    with lock:
        save_midi(filename, captured)
    source.close_port()


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
            print("Usage: python3 midi_session.py play <file.mid> [--loop]")
            sys.exit(1)
        play(sys.argv[2], loop='--loop' in sys.argv)


if __name__ == '__main__':
    main()

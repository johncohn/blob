#!/usr/bin/env python3
"""
midi_preview.py — make a Blob recording audible in GarageBand (or any DAW).

Recordings from blob_monitor.py hold only servo CC data, which no instrument
plays. This writes a copy with one note track per servo: each servo's position
becomes a pitch (low = one end of travel, high = the other), held until the
position changes. GarageBand opens each track as its own instrument, so you
can hear and see every servo's motion.

The preview is for listening/viewing only — play the original file on the Pi.

Usage:
    python3 midi_preview.py recordings/bensong1.mid     # → bensong1_preview.mid
    python3 midi_preview.py in.mid -o out.mid
"""
import argparse
from pathlib import Path

import mido

# Servo CCs in user order 1–9 (NW, N, NE, W, CTR, E, SW, S, SE)
SERVO_CCS = [16, 17, 18, 20, 21, 22, 24, 25, 26]
LOW_NOTE  = 36   # C2 — CC value 0
HIGH_NOTE = 84   # C6 — CC value 127
MAX_HOLD  = 1.0  # beats — longest a single note rings before a repeat


def cc_to_note(value):
    return LOW_NOTE + round(value * (HIGH_NOTE - LOW_NOTE) / 127)


def build_preview(src):
    tpb      = src.ticks_per_beat
    max_hold = int(MAX_HOLD * tpb)

    # Flatten every track to absolute ticks
    tempo_events = []
    cc_events    = {cc: [] for cc in SERVO_CCS}
    src_end      = 0
    for track in src.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            src_end = max(src_end, tick)
            if msg.type == 'set_tempo':
                tempo_events.append((tick, msg.tempo))
            elif msg.type == 'control_change' and msg.control in cc_events:
                cc_events[msg.control].append((tick, msg.value))
    end_tick = max((t for evs in cc_events.values() for t, _ in evs), default=0)

    out = mido.MidiFile(type=1, ticks_per_beat=tpb)
    meta = mido.MidiTrack()
    out.tracks.append(meta)
    meta.append(mido.MetaMessage('track_name', name='Blob preview', time=0))
    prev = 0
    for tick, tempo in sorted(tempo_events) or [(0, 500000)]:
        meta.append(mido.MetaMessage('set_tempo', tempo=tempo, time=tick - prev))
        prev = tick
    # Keep the original's full length (recordings include trailing stillness)
    meta.append(mido.MetaMessage('end_of_track', time=max(0, src_end - prev)))

    for servo, cc in enumerate(SERVO_CCS, start=1):
        events = cc_events[cc]
        if not events:
            continue
        ch = servo - 1                      # channels 0–8 (skips drum channel 9)
        notes = []                          # (start, end, pitch)
        for i, (tick, value) in enumerate(events):
            pitch = cc_to_note(value)
            if notes and notes[-1][2] == pitch:
                continue                    # same pitch: keep the current note ringing
            if notes:
                s, e, p = notes[-1]
                notes[-1] = (s, min(e, tick), p)
            notes.append((tick, tick + max_hold, pitch))
        if notes:
            s, e, p = notes[-1]
            notes[-1] = (s, max(min(e, end_tick + tpb // 4), s + 1), p)

        track = mido.MidiTrack()
        out.tracks.append(track)
        track.append(mido.MetaMessage('track_name', name=f'Servo {servo} (CC {cc})', time=0))
        timeline = []
        for s, e, p in notes:
            if e > s:
                timeline.append((s, 1, mido.Message('note_on',  channel=ch, note=p, velocity=100)))
                timeline.append((e, 0, mido.Message('note_off', channel=ch, note=p, velocity=0)))
        for tick, value in events:
            timeline.append((tick, 2, mido.Message('control_change', channel=ch, control=cc, value=value)))
        prev = 0
        for tick, _, msg in sorted(timeline, key=lambda x: (x[0], x[1])):
            track.append(msg.copy(time=tick - prev))
            prev = tick
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input')
    ap.add_argument('-o', '--output')
    args = ap.parse_args()

    src = Path(args.input)
    dst = Path(args.output) if args.output else src.with_name(f'{src.stem}_preview.mid')
    out = build_preview(mido.MidiFile(src))
    out.save(dst)
    servos = len(out.tracks) - 1
    print(f'{dst}  ({servos} servo track{"s" if servos != 1 else ""}, {out.length:.1f} s)')


if __name__ == '__main__':
    main()

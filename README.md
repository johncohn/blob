# blob

An interactive art piece: 9 linear servo actuators controlled in real time by a MIDI Fighter Twister controller. Each knob drives one servo — speed and direction are relative to a dynamic midpoint so the knobs feel like joysticks. Buttons reset positions or trigger full retraction.

---

## Repo Contents

```
benmidi_v7/
  benmidi_v7.ino                 production firmware — flash this for the art piece
  midi_test_pattern/
    midi_test_pattern.ino        test firmware — generates simulated knob data
  midi_session.py                record, capture, and play back MIDI sessions
  run_session.sh                 launcher for midi_session.py
  requirements.txt               Python dependencies
  README.md                      firmware and hardware reference
  RECORDING_SETUP.md             full setup walkthrough
archive/
```

---

## Three Commands

```bash
cd /Users/jcohn/blob/benmidi_v7

./run_session.sh capture test.mid        # record from Feather test sketch
./run_session.sh record session.mid      # record from Twister (full setup)
./run_session.sh play session.mid        # play back to Feather
./run_session.sh play session.mid --loop # loop playback
```

---

## Tonight: Test Run (Feather only, test firmware)

### Hardware
1. Unplug WIDI from Feather — set aside
2. Flash `midi_test_pattern/midi_test_pattern.ino` to Feather
3. Plug Feather into Mac via USB

### Record the simulated pattern
```bash
cd /Users/jcohn/blob/benmidi_v7
./run_session.sh capture test.mid
```
First run installs dependencies (~30 seconds). Then CC messages scroll as the Feather sweeps through all 9 knobs. Press **Ctrl+C** to stop and save.

### View and edit in GarageBand
1. Open GarageBand → Empty Project
2. **File → Open** → select `test.mid`
3. Edit graphically in the piano roll
4. **File → Export → Export Song to MIDI** → save as `edited.mid`

### Play back
```bash
./run_session.sh play test.mid
./run_session.sh play edited.mid
```

---

## Full Setup (Twister + Feather, production firmware)

### Hardware
1. Flash `benmidi_v7.ino` to Feather
2. Plug Twister into Mac via USB
3. Plug Feather into Mac via USB

### Record
```bash
./run_session.sh record session.mid
```
Turn knobs — servos respond live, LED rings update, everything is captured. **Ctrl+C** to save.

### Play back
```bash
./run_session.sh play session.mid
```
Feather receives the MIDI, servos and LED rings respond exactly as during recording.

---

## Console Output

```
  [CAP ] Ch1  CC 3 = 87          ← test sketch capture
  [REC ] Ch1  CC 3 = 87          ← live Twister recording
  [LED ] Ch1  CC 3 = 112         ← LED feedback routed to Twister
  [PLAY] Ch1  CC 3 = 87          ← playback sent to Feather
```

---

## Troubleshooting

**Feather not detected** — try a different USB cable; make sure firmware is flashed

**Port not found by name** — script prints a numbered list, just type the number

**Install failed** — run the script again, it rebuilds the venv automatically

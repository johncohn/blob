# MIDI Recording Setup Guide

---

## Two Scenarios

| Scenario | Firmware | Command | When to use |
|---|---|---|---|
| Test only | `midi_test_pattern.ino` | `capture` | Feather only, no Twister needed |
| Full setup | `benmidi_v7.ino` | `record` | Twister + Feather, production use |

---

## Scenario 1: Test Run (Feather only)

Use this to verify the pipeline works before the full setup.

### Hardware
1. Unplug the WIDI receiver from the Feather and set it aside
2. Flash `midi_test_pattern/midi_test_pattern.ino` to the Feather using Arduino IDE
3. Plug the Feather into the Mac via USB
4. Open **Audio MIDI Setup** (Applications → Utilities) → **Window → Show MIDI Studio** — confirm the Feather appears

### Record the test pattern
```bash
cd /Users/jcohn/blob/benmidi_v7
./run_session.sh capture test.mid
```

**First time only** — creates a virtual environment and installs dependencies (~30 seconds):
```
Setting up virtual environment...
Installing dependencies...
Ready.
```

The Feather test sketch runs automatically through two phases:
- **Phase 1**: sweeps each of the 9 knobs from center → max → min → center, sending CC messages and LED feedback
- **Phase 2**: listens for incoming MIDI and responds (used during playback)

You'll see CC messages scrolling:
```
  [CAP ] Ch1  CC 0 = 68
  [CAP ] Ch1  CC 0 = 72
  [CAP ] Ch1  CC 0 = 76
```

Press **Ctrl+C** when Phase 1 is done (about 30 seconds) or whenever you want to stop. File is saved automatically.

### View and edit in GarageBand
1. Open **GarageBand → Empty Project**
2. **File → Open** → select `test.mid`
3. The CC data appears graphically in the piano roll
4. Copy, move, loop regions as needed
5. **File → Export → Export Song to MIDI** → save as `edited.mid`

### Play back
```bash
./run_session.sh play test.mid
./run_session.sh play edited.mid
./run_session.sh play test.mid --loop
```

---

## Scenario 2: Full Setup (Twister + Feather)

### Hardware
1. Flash `benmidi_v7.ino` to the Feather using Arduino IDE
2. Unplug WIDI — set aside
3. Plug **Twister** into Mac via USB
4. Plug **Feather** into Mac via USB
5. Confirm both appear in **Audio MIDI Setup → MIDI Studio**

### Record
```bash
cd /Users/jcohn/blob/benmidi_v7
./run_session.sh record session.mid
```

Turn knobs on the Twister:
- Servos respond live
- LED rings on the Twister update in real time
- Everything is captured

Press **Ctrl+C** to stop and save.

### Play back
```bash
./run_session.sh play session.mid
```

The Feather receives the recorded MIDI. Servos and LED rings respond exactly as during recording.

### Loop
```bash
./run_session.sh play session.mid --loop
```

---

## Console Output Reference

```
  [CAP ] Ch1  CC 3 = 87     ← captured from test sketch
  [REC ] Ch1  CC 3 = 87     ← recorded from Twister, forwarded to Feather
  [LED ] Ch1  CC 3 = 112    ← LED feedback from Feather routed to Twister
  [PLAY] Ch1  CC 3 = 87     ← playback sent to Feather
```

---

## Troubleshooting

**Feather doesn't appear in Audio MIDI Setup**
- Make sure firmware is flashed
- Try a different USB cable (some are charge-only)
- Unplug, replug, reopen Audio MIDI Setup

**Script can't find a port by name**
- It prints a numbered list and asks you to type the number

**Install failed**
- Run the script again — it detects a broken venv and rebuilds automatically
- If Python 3 isn't installed: `brew install python`

**No LED lines in console during full setup**
- Check the Feather firmware is `benmidi_v7.ino` (not the test sketch)
- Verify the Feather is powered and PCA9685 board is connected

# MIDI Recording Setup Guide

This guide covers recording, playing back, and editing MIDI sessions for the servo art piece.

---

## Overview

```
MIDI Fighter Twister ──USB──► Mac (midi_session.py) ──USB──► Feather M4
                                                                   │
                         Twister LED rings ◄── midi_session.py ◄──┘
```

`midi_session.py` handles everything in one script:
- Captures knob movements from the Twister
- Forwards them live to the Feather so servos run while you record
- Routes LED feedback from the Feather back to the Twister throughout
- Saves to a standard `.mid` file you can open in any DAW for editing

---

## What You Need

- Mac with Apple Silicon (M1/M2/M3)
- Two USB cables (one for Twister, one for Feather)
- Python 3 — check with `python3 --version` in Terminal
- GarageBand (free, for graphical editing) — or any DAW

---

## Part 1: Hardware Setup

1. **Unplug the WIDI receiver** from the Feather M4 and set it aside
2. **Plug the Twister** into the Mac via USB
3. **Plug the Feather** into the Mac via USB
4. **Verify both appear on Mac:**
   - Open **Audio MIDI Setup** (Applications → Utilities)
   - Click **Window → Show MIDI Studio**
   - Both Twister and Feather should appear as icons
   - If Feather is missing: try a different USB cable or reflash the firmware

---

## Part 2: Record a Session

Open **Terminal** and run:

```bash
cd /Users/jcohn/blob/benmidi_v7
./run_session.sh record mysession.mid
```

**First time only:** creates a virtual environment and installs dependencies from public PyPI (~30 seconds):

```
Setting up virtual environment...
Installing dependencies...
Ready.
```

Once running you'll see the port detection, then:

```
Recording to mysession.mid
Turn knobs... Ctrl+C to stop and save.

  [REC ] Ch1  CC 0 = 87
  [LED ] Ch1  CC 0 = 112  → Twister
  [REC ] Ch1  CC 1 = 43
  [LED ] Ch1  CC 1 = 34   → Twister
```

- **`[REC]`** — knob movement captured and forwarded to Feather
- **`[LED]`** — LED feedback from Feather routed back to Twister

Press **Ctrl+C** to stop. The file is saved automatically.

---

## Part 3: Play Back

```bash
./run_session.sh play mysession.mid
```

Sends the recorded session to the Feather with correct timing. LED rings respond throughout.

### Loop playback

```bash
./run_session.sh play mysession.mid --loop
```

Press **Ctrl+C** to stop.

---

## Part 4: Edit in GarageBand

The `.mid` file saved by `midi_session.py` opens directly in GarageBand.

1. Open **GarageBand → Empty Project**
2. **File → Open** — select your `.mid` file
3. GarageBand shows the MIDI data graphically in the piano roll
4. Edit as needed — copy regions, move them, loop them, delete sections
5. **File → Export → Export Song to MIDI** — save as a new `.mid` file
6. Play back the edited file:
   ```bash
   ./run_session.sh play edited.mid
   ```

### Does editing in GarageBand break the LED control?

No. The LED feedback is computed by the Feather in response to incoming CC messages — it's not stored in the `.mid` file. When you play back any `.mid` file to the Feather, the Feather generates the correct LED responses and `midi_session.py` routes them to the Twister automatically.

---

## Part 5: File Management

Sessions are saved as standard `.mid` files in whatever directory you run the script from. It's a good idea to keep them in one place:

```bash
mkdir -p /Users/jcohn/blob/sessions
./run_session.sh record /Users/jcohn/blob/sessions/take1.mid
./run_session.sh play   /Users/jcohn/blob/sessions/take1.mid
```

---

## Troubleshooting

**Feather doesn't appear in Audio MIDI Setup**
- Make sure the production firmware (`benmidi_v7.ino`) is flashed — the `MIDIUSB.h` library is what makes it appear as a MIDI device
- Try a different USB cable (some are charge-only with no data)
- Unplug, replug, reopen Audio MIDI Setup

**Script can't find Twister or Feather by name**
- It prints all available ports and asks you to type the number
- Check that both devices are plugged in before running the script

**Install failed (corporate package registry error)**
- Run the script again — it detects the broken venv and rebuilds with `--index-url https://pypi.org/simple` to bypass any managed registry
- If Python 3 itself isn't installed:
  ```bash
  brew install python
  ```

**No `[LED]` lines in console during recording**
- The Feather isn't sending LED feedback — check the firmware is flashed correctly
- Verify the Feather appears in Audio MIDI Setup

**Servos don't respond during playback**
- Check the track output port is set to the Feather
- Verify the Feather is powered and the PCA9685 servo board is connected via I2C

---

## Quick Reference

| Action | Command |
|---|---|
| Record | `./run_session.sh record filename.mid` |
| Play back | `./run_session.sh play filename.mid` |
| Loop playback | `./run_session.sh play filename.mid --loop` |
| Stop anything | **Ctrl+C** |

# blob

An interactive art piece: 9 linear servo actuators controlled in real time by a MIDI Fighter Twister controller. Each knob drives one servo — speed and direction are relative to a dynamic midpoint so the knobs feel like joysticks. Buttons reset positions or trigger full retraction.

The Feather M4 runs the servo logic. A Mac sits in the middle to record, edit, and replay MIDI sequences during testing and performance.

---

## Repo Contents

```
benmidi_v7/
  benmidi_v7.ino                       firmware — flash this to the Feather
  midi_session.py                      record and play back MIDI sessions
  midi_led_router.py                   LED-only router (standalone, see below)
  run_session.sh                       launcher for midi_session.py
  run_router.sh                        launcher for midi_led_router.py
  requirements.txt                     Python dependencies
  midi_test_pattern/
    midi_test_pattern.ino              test sketch — simulates knob sweeps
  README.md                            firmware and hardware reference
  RECORDING_SETUP.md                   full setup walkthrough
archive/
  MIDI_Field_Guide_MacBook_Feather_Recording.pdf
```

---

## How It Works

```
MIDI Fighter Twister ──USB──► Mac (midi_session.py records here) ──USB──► Feather M4
                                                                               │
                              Twister LED rings ◄── midi_session.py ◄─────────┘
```

`midi_session.py` handles everything:
- **Record**: captures knob movements from the Twister, forwards live to the Feather so servos run while you record, routes LED feedback from Feather back to Twister throughout
- **Play**: sends a recorded `.mid` file to the Feather with correct timing, routes LED feedback back to Twister throughout

The saved `.mid` file can be opened in **GarageBand** (free, already on your Mac) or any DAW for graphical editing. Export back to `.mid` and play with `run_session.sh`.

---

## Tonight: Quick Setup and Run

### Hardware (2 minutes)
1. Unplug the WIDI receiver from the Feather — set it aside
2. Plug **Twister → Mac** via USB
3. Plug **Feather → Mac** via USB
4. Open **Audio MIDI Setup** (Spotlight: "Audio MIDI Setup") → **Window → Show MIDI Studio**
   - Confirm both the Twister and Feather appear as icons
   - If Feather is missing: try a different USB cable

### Record a Session
```bash
cd /Users/jcohn/blob/benmidi_v7
./run_session.sh record mysession.mid
```
First run installs dependencies (~30 seconds). Then:
- Turn knobs — servos respond live, LED rings update, everything is captured
- Press **Ctrl+C** to stop and save

### Play Back
```bash
./run_session.sh play mysession.mid
```
Sends the recording to the Feather. LED rings respond throughout.

### Loop Playback
```bash
./run_session.sh play mysession.mid --loop
```

---

## Editing in GarageBand

1. Open **GarageBand → Empty Project**
2. **File → Open** — select your `.mid` file
3. Edit in the piano roll (copy, paste, move, loop regions)
4. **File → Export → Export Song to MIDI** — save as a new `.mid` file
5. Play back with `./run_session.sh play edited.mid`

---

## Console Output

While running, the script prints every message so you can see what's happening:

```
  [REC ] Ch1  CC 3 = 87          ← knob movement captured
  [LED ] Ch1  CC 3 = 112  → Twister   ← LED feedback routed
  [PLAY] Ch1  CC 3 = 87   → Feather   ← playback sent
```

---

## Troubleshooting

**Feather doesn't appear in Audio MIDI Setup**
- Make sure the current firmware is flashed
- Try a different USB cable (some are charge-only)
- Unplug/replug, then re-open Audio MIDI Setup

**Script can't find ports by name**
- It will print a numbered list and ask you to pick — just type the number

**Install failed**
- Run `./run_session.sh record` again — detects broken venv and rebuilds automatically

**Servos respond but LED rings don't**
- Check console for `[LED]` lines — if you see them, the routing is working and the issue is with the Twister connection
- If no `[LED]` lines, the Feather isn't sending feedback — check the firmware is flashed correctly

# blob

An interactive art piece: 9 linear servo actuators controlled in real time by a MIDI Fighter Twister controller. Each knob drives one servo — speed and direction are relative to a dynamic midpoint so the knobs feel like joysticks. Buttons reset positions or trigger full retraction.

The Feather M4 runs the servo logic. During testing and performance, a Mac sits in the middle to record, edit, and replay MIDI sequences.

---

## Repo Contents

```
benmidi_v7/
  benmidi_v6_copy_20260503161043.ino   firmware (flash this to the Feather)
  midi_led_router.py                   routes LED feedback Feather → Twister
  README.md                            firmware and hardware reference
  RECORDING_SETUP.md                   full recording setup walkthrough
archive/
  MIDI_Field_Guide_MacBook_Feather_Recording.pdf
```

---

## Tonight: Quick Setup and Run

### Hardware (2 minutes)
1. Unplug the WIDI receiver from the Feather — set it aside
2. Plug **Twister → Mac** via USB
3. Plug **Feather → Mac** via USB
4. Open **Audio MIDI Setup** (Spotlight: "Audio MIDI Setup") → **Window → Show MIDI Studio**
   - Confirm both the Twister and Feather appear as icons
   - If Feather is missing: try a different USB cable or reflash the firmware

### Start the LED Router (1 minute)
Open **Terminal** and run:
```bash
cd /Users/jcohn/blob/benmidi_v7
python3 midi_led_router.py
```
It prints the routing and sits quietly. **Leave Terminal open.**
If it can't find the ports by name, it will ask you to type the number — just pick from the printed list.

### Set Up GarageBand (2 minutes)
1. Open **GarageBand → Empty Project → cancel** the New Track dialog
2. Menu bar: **Track → New External MIDI Track**
3. In the track header: set **Port** to the Feather, **Channel** to 1
4. Click the red circle on the track header to **arm it**

### Record
- Press **R** to record (one bar count-in, then go)
- Turn knobs — all movement is captured
- Press **Space** to stop

### Edit
| What | How |
|---|---|
| Copy a region | Hold Option (⌥) and drag |
| Loop / repeat | Drag the top-right corner of the region rightward |
| Move | Drag the region |
| Delete | Select + Delete key |

### Play Back
Press **Space** — the Feather receives the MIDI exactly as recorded, servos respond, LED rings update via the Python router.

### Save
**Cmd+S** saves the GarageBand project. To export a `.mid` file: **File → Export → Export Song to MIDI.**

---

## If the LED Router Isn't Working

Skip it — the servos still work fine. The Twister LED rings just won't update during playback. See `benmidi_v7/RECORDING_SETUP.md` for troubleshooting, or use the fallback GarageBand-only steps at the bottom of that file.

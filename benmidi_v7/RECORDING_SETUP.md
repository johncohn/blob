# MIDI Recording Setup Guide
## Capturing, Editing, and Replaying MIDI for the Servo Art Piece

This guide walks through recording MIDI from the MIDI Fighter Twister through your Mac to the Feather M4, so you can capture, edit, and loop sequences during testing and performance.

---

## How It Works

Normally the Twister connects wirelessly via WIDI directly to the Feather. For recording, you bypass the WIDI and put the Mac in the middle:

```
MIDI Fighter Twister  ──USB──►  Mac (GarageBand records here)  ──USB──►  Feather M4
                                                                              │
                                        Twister LED rings  ◄── Python script ┘
```

- **GarageBand** captures the knob movements, lets you edit them, and plays them back to the Feather
- **A small Python script** (`midi_led_router.py`) routes the Feather's LED feedback back to the Twister so the ring lights respond in real time

There is also a **fallback** at the end of this guide — GarageBand only, no Python, no LED feedback — if you need to get up and running fast.

---

## What You Need

- Mac with Apple Silicon (M1/M2/M3)
- GarageBand (free, should already be installed — check Applications folder)
- Python 3 (check by running `python3 --version` in Terminal)
- Two USB cables (one for Twister, one for Feather)
- The WIDI receiver unplugged from the Feather for this setup

---

## Part 1: Hardware Setup

1. **Unplug the WIDI receiver** from the Feather M4. Set it aside — you won't need it for this.

2. **Connect the MIDI Fighter Twister** to your Mac via USB.

3. **Connect the Feather M4** to your Mac via USB (the same cable you use to flash it).

4. **Verify both devices appear on the Mac:**
   - Open **Audio MIDI Setup** (find it in Applications → Utilities, or Spotlight search)
   - Click **Window → Show MIDI Studio** in the menu bar
   - You should see icons for both the Twister and the Feather in the MIDI Studio window
   - If either is missing, try unplugging and replugging that USB cable
   - If the Feather doesn't appear, make sure it has the current firmware flashed (`benmidi_v6_copy_20260503161043.ino`) — the MIDIUSB library is what makes it show up as a MIDI device

---

## Part 2: Install the Python LED Router

This routes the Feather's LED feedback messages back to the Twister so the ring lights work during recording and playback. Skip to Part 3 if you want to start without this.

### Run the Router

The script uses a Python virtual environment so it doesn't touch your system Python installation. Everything is self-contained in a `venv/` folder inside `benmidi_v7/`. It installs `python-rtmidi` directly from public PyPI, bypassing any corporate or managed package registry that may be configured on your machine.

Open **Terminal** (Applications → Utilities → Terminal) and run:

```bash
cd /Users/jcohn/blob/benmidi_v7
./run_router.sh
```

**First time only:** the script creates the virtual environment and installs `python-rtmidi` automatically. This takes about 30 seconds and you'll see:

```
Setting up virtual environment...
Installing python-rtmidi from public PyPI...
Ready.
```

Every subsequent run skips straight to launching the router. If a previous install failed for any reason, re-running the script detects the broken state and rebuilds automatically.

If Python 3 itself isn't installed, install it via Homebrew first:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python
```

Then run `./run_router.sh` again.

You will see something like:

```
MIDI inputs:
  0: Midi Fighter Twister
  1: Feather M4 Express
  2: IAC Driver Bus 1

MIDI outputs:
  0: Midi Fighter Twister
  1: Feather M4 Express
  2: IAC Driver Bus 1

Routing: Feather M4 Express → Midi Fighter Twister
Active. Ctrl+C to stop.
```

The script auto-detects the Feather and Twister by name. If it can't find them it will ask you to type the number of the correct port.

**Leave this Terminal window open** and move on to GarageBand. The router runs silently in the background as long as Terminal stays open.

To stop it later: click the Terminal window and press **Ctrl+C**.

---

## Part 3: Set Up GarageBand

### Create a New Project

1. Open **GarageBand**
2. Choose **Empty Project**
3. In the **New Track** dialog that appears, you can click **Cancel** for now — we'll add the right track type from the menu

### Add an External MIDI Track

An External MIDI track is what lets GarageBand send recorded MIDI to a physical device (the Feather) rather than a software synth.

1. In the menu bar: **Track → New External MIDI Track**
2. A new track appears in the track list on the left

### Configure the Track

1. Click the track name to select it
2. At the top of the track header area you'll see **MIDI channel** and **Port** settings
3. Set **Port** to your Feather M4 (it will appear by its USB MIDI name)
4. Set **Channel** to **1** (the Feather reads CC messages on Channel 1 for knob rotation and Channel 2 for buttons — GarageBand will capture both when recording)

### Set the Tempo

The Feather doesn't care about tempo, but it affects how recorded CC data lines up visually in the editor. A slower tempo (60–80 BPM) makes the regions easier to see and move around.

1. Click the tempo number at the top of the GarageBand window
2. Type a value — **60 BPM** is a good starting point

---

## Part 4: Recording

1. **Arm the track for recording** — click the red circle button on the track header (it turns solid red when armed)

2. **Click the red Record button** in the toolbar at the top (or press **R**)

3. GarageBand will count in for one bar, then start recording

4. **Turn your Twister knobs** — all CC messages are captured as they happen

5. Press **Space** to stop recording

You'll see a green MIDI region appear on the track containing all the CC data you just played.

### Tip: Monitor What Was Recorded

Double-click the green region to open the **Piano Roll editor**. CC data (knob movements) appears as automation — you may need to click the **View** button at the bottom of the Piano Roll and select **Show Automation** to see the CC curves. You don't need to edit individual CC values — working with whole regions (the green blocks) is enough for copying and looping.

---

## Part 5: Editing — Copy, Repeat, Move

All the editing you need happens directly on the green regions in the main timeline.

### Copy a Region

1. Hold **Option (⌥)** and drag the region — this creates a copy
2. Or select the region and press **Cmd+C**, then **Cmd+V** to paste

### Repeat / Loop a Region

1. Hover your mouse over the **top-right corner** of the region
2. The cursor changes to a loop arrow
3. **Drag to the right** — the region repeats as many times as you pull it

### Move a Region

Click and drag the region left or right along the timeline.

### Delete a Region

Click to select it, then press **Delete**.

---

## Part 6: Playback to the Feather

1. Make sure the Feather is still connected via USB
2. Make sure the track output is still set to the Feather port
3. Press **Space** (or click the Play button) — GarageBand sends the recorded CC data to the Feather exactly as if you were turning the knobs live
4. The Python script (if running) will route the Feather's LED responses back to the Twister rings simultaneously

---

## Part 7: Saving Your MIDI

### Save the GarageBand Project

**Cmd+S** — saves the full project so you can reopen and edit it later.

### Export as a MIDI File (optional)

If you want a standalone `.mid` file:

1. **File → Export → Export Song to MIDI...**
2. Choose a location and save

---

## Troubleshooting

**Feather doesn't appear as a MIDI device in Audio MIDI Setup**
- Make sure the current firmware is flashed — the `MIDIUSB.h` library is what enumerates it as a USB MIDI device
- Try a different USB cable (some cables are charge-only)
- Unplug and replug, then re-open Audio MIDI Setup

**GarageBand doesn't show the Feather in the port list**
- Plug in the Feather before opening GarageBand — GarageBand scans ports at launch
- If already open: quit GarageBand, make sure Feather is connected, reopen

**Python script says "No module named rtmidi"**
- Just run `./run_router.sh` again — it detects the broken install and rebuilds the virtual environment automatically

**Python script can't find the Feather or Twister by name**
- It will prompt you to type the port number — just look at the printed list and enter the right number

**LED rings don't respond during playback**
- Check the Terminal window — the script may have stopped (press Ctrl+C and rerun it)
- If the script is running but lights still don't respond, check that the Feather is still recognized (unplug/replug)

**Recorded CC data plays back but servos don't respond**
- Check the track output port is set to the Feather, not a software instrument
- Make sure the track is not muted (M button on the track header)
- Verify the Feather is powered on and the servo board is connected

---

## Fallback: GarageBand Only (No LED Feedback)

Use this if the Python script isn't working or you're in a hurry. Everything works except the Twister LED rings won't respond during playback.

1. Plug in Twister and Feather via USB
2. Open GarageBand → Empty Project → cancel the New Track dialog
3. **Track → New External MIDI Track**
4. Set the track **Port** to the Feather, **Channel** to 1
5. Arm the track (red circle on track header)
6. Press **R** to record
7. Turn knobs — all movement is captured
8. Press **Space** to stop
9. Edit regions using Option+drag (copy), corner-drag (loop), drag (move)
10. Press **Space** to play back — servos respond, LED rings will not update

That's it. You can always add the Python LED router later without changing anything else.

---

## Quick Reference

| Action | How |
|---|---|
| Start recording | R |
| Stop / Play | Space |
| Copy a region | Option + drag |
| Loop a region | Drag top-right corner |
| Move a region | Drag |
| Delete a region | Select + Delete |
| Save project | Cmd+S |
| Start LED router | `python3 midi_led_router.py` in Terminal |
| Stop LED router | Ctrl+C in Terminal |

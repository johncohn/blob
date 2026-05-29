# Blob — TouchOSC Control Surface

TouchOSC is being evaluated as an alternative to the MIDI Fighter Twister.
Key advantages: phone/tablet form factor, arbitrary layout, bidirectional MIDI
(surface updates when a recording plays back), and no wireless WIDI adapter needed
(uses Network MIDI over WiFi directly).

---

## Surface layout

```
┌────────────────────────────────────────────────────────────────┬──────────────────┐
│  SERVO MATRIX                                                  │  BLOB            │
│  ┌────────┐  ┌────────┐  ┌────────┐                           │  BLOWER          │
│  │  S1    │  │  S2    │  │  S3    │                           │  ┌──────┐ [BRTH] │
│  │ CC 16  │  │ CC 17  │  │ CC 18  │                           │  │ spd  │        │
│  └────────┘  └────────┘  └────────┘                           │  │ CC32 │        │
│  ┌────────┐  ┌────────┐  ┌────────┐                           │  └──────┘        │
│  │  S4    │  │  S5    │  │  S6    │                           │  HEARTBEAT       │
│  │ CC 20  │  │ CC 21  │  │ CC 22  │                           │  ┌──────┐┌──────┐│
│  └────────┘  └────────┘  └────────┘                           │  │speed ││bright││
│  ┌────────┐  ┌────────┐  ┌────────┐                           │  │ CC34 ││ CC35 ││
│  │  S7    │  │  S8    │  │  S9    │                           │  └──────┘└──────┘│
│  │ CC 24  │  │ CC 25  │  │ CC 26  │                           │                  │
│  └────────┘  └────────┘  └────────┘                           │                  │
│                                                                │                  │
│  [  HALT  CC36  ]          [  RETRACT  CC37  ]                │                  │
└────────────────────────────────────────────────────────────────┴──────────────────┘
```

---

## Controls reference

### Servo sliders (3×3 grid)

| Control | CC | Behaviour |
|---------|-----|-----------|
| S1 | CC 16 | Above centre → extend; below centre → retract. Speed ∝ distance from centre. |
| S2 | CC 17 | Same |
| S3 | CC 18 | Same |
| S4 | CC 20 | Same |
| S5 | CC 21 | Same |
| S6 | CC 22 | Same |
| S7 | CC 24 | Same |
| S8 | CC 25 | Same |
| S9 | CC 26 | Same |

All CC values 0–127. Centre = 64 = stop. Above 64 = extend, below 64 = retract.
The Feather firmware interprets the distance from 64 as speed.

### Right panel

| Control | CC | Type | Notes |
|---------|-----|------|-------|
| Blower speed | CC 32 | Fader | 0 = off, 127 = full speed. M4 firmware TBD. |
| Breathe | CC 33 | Toggle button | On = 127, Off = 0. Signals M4 to cycle blower for breathing effect. M4 TBD. |
| HB speed | CC 34 | Fader | Heartbeat rate. M4 firmware TBD. |
| HB brightness | CC 35 | Fader | Heartbeat LED brightness. M4 firmware TBD. |

### Action buttons

| Control | CC | Behaviour |
|---------|-----|-----------|
| HALT | CC 36 | Momentary. Sends CC 127 on press, 0 on release. M4 stops all servos. Lua script resets all servo sliders to centre (64). |
| RETRACT | CC 37 | Momentary. Sends CC 127 on press, 0 on release. M4 fully retracts all servos. Lua script sets all servo sliders to 0. |

All controls on **MIDI channel 2** to match the existing Feather firmware.

---

## Network MIDI setup (Mac ↔ iPad/iPhone)

Both devices must be on the same WiFi network.

**On the Mac:**
1. Open **Audio MIDI Setup** → Window → Show MIDI Studio
2. Double-click **Network**
3. Under "My Sessions", click **+** and name it (e.g. `Blob`)
4. Tick the session to enable it

**In TouchOSC (on device):**
1. Settings → Connections → MIDI → **+**
2. Type: **RTP-MIDI**
3. Browse — your Mac's session appears automatically; tap to connect

The Network MIDI port shows up on the Mac as a normal MIDI port named after the session.
`midi_session.py` will detect it automatically if you add `"network"` to the keyword list
(see **Integration** below).

---

## Integration with midi_session.py

### Treating TouchOSC as a drop-in Twister replacement

In `midi_session.py`, add `"network"` to `TWISTER_KEYS` in `capture()` and `play()`:

```python
TWISTER_KEYS = ["twister", "fighter", "widi", "cme", "network"]
```

`capture` mode then treats the TouchOSC Network MIDI port as the control source,
forwarding messages to the Feather and saving to a `.mid` file exactly as with the Twister.

### Bidirectional surface update during playback

Because every control has `receive="1"` in its MIDI definition, `midi_session.py play`
updates the TouchOSC surface live as a recording plays back — sliders and buttons move
to reflect the recorded state. This means:

1. Record a performance on the physical Twister (or TouchOSC) → `.mid` file
2. Edit in GarageBand or any DAW (CC lane editing)
3. `python3 midi_session.py play edited.mid` — Feather servos move AND TouchOSC updates

### New CCs not yet in the Feather firmware

CC 32–37 (blower, breathe, heartbeat, halt, retract) are recorded and saved to the `.mid`
file but the Feather firmware currently ignores them. They will be wired up incrementally.
Recording them now means you can program the full performance timeline in a DAW today
and add firmware support later without re-recording.

---

## Regenerating the surface file

The surface is generated by `touchosc_gen.py`. Edit the script to change CC assignments,
layout geometry, colours, or add new controls, then re-run:

```bash
python3 touchosc_gen.py                 # writes blob_surface.tosc
python3 touchosc_gen.py my_variant.tosc # custom filename
```

Load `blob_surface.tosc` into TouchOSC via the Files panel → Import.

If you make edits directly in TouchOSC's editor and want those preserved, export the file
back out (Files → Export) and commit it. The Python generator is for programmatic bulk
changes; the TouchOSC editor is for fine-grained visual tweaks.

---

## Future work (firmware side)

| Feature | CC | Status |
|---------|-----|--------|
| Servo speed control (existing) | 16-26 | ✅ implemented |
| Blower speed (PWM) | 32 | pending |
| Breathe cycle | 33 | pending |
| Heartbeat speed | 34 | pending |
| Heartbeat brightness | 35 | pending |
| HALT (stop + centre) | 36 | pending |
| RETRACT (withdraw all) | 37 | partially (existing double-click on CC 31) |

# Blob

An interactive kinetic art piece: 9 servo actuators controlled in real time from an iPad running TouchOSC, with a Raspberry Pi as the hub and an Adafruit Feather M4 CAN as the servo driver. Supports live control, MIDI recording and looped playback, and two iPads simultaneously.

---

## System Architecture

```
iPad (TouchOSC)
  │  MIDI over Network  ←→  Pi (blobpi.local)  ←→  Feather M4 CAN  →  9 servos
  │  OSC over UDP              blob_monitor.py         (USB MIDI)
  └─ (Ben's iPad, direct IP)       │
                                 OLED display
                                 recordings/*.mid
```

- **Pi** (`blobpi.local`, systemd service `blob-monitor`) is the central hub
- **John's iPad** — connects via MIDI over Network (TouchOSC Browse → "blobpi")
- **Ben's iPad** — connects via OSC over UDP (direct IP, no mDNS needed; see below)
- **Feather M4 CAN** — receives MIDI CC on channel 1 via USB; drives servos
- **OLED** — 128×32 SSD1306 on I2C shows IP, mode, and last servo activity

---

## Repo Contents

```
blob_monitor.py              Main Pi service — MIDI/OSC hub, recording, playback
benmidi_v7/
  touchosc_gen.py            Generates the TouchOSC layout file
  TextInputDialog.tosc       On-screen keyboard widget (imported into layout)
  blob1.band/                GarageBand session for editing recordings
  bentest*.mid               Test recordings
recordings/                  MIDI recordings (named or auto-timestamped)
  latest.mid                 Copy of most recent recording
blob_surface_compass.tosc    TouchOSC layout (compass layout — the only active one)
archive/                     Old code and experiments
```

---

## Pi Setup

The Pi runs `blob-monitor.service` (Restart=always). SSH access:
```
ssh pi@blobpi.local          # password: JCMy3boys!!
```

Service commands:
```bash
sudo systemctl status blob-monitor
sudo systemctl restart blob-monitor
journalctl -u blob-monitor -f       # live log
```

Deploy updated `blob_monitor.py`:
```bash
scp blob_monitor.py pi@blobpi.local:/home/pi/blob_monitor.py
ssh pi@blobpi.local 'sudo systemctl restart blob-monitor'
```

---

## TouchOSC Setup

Load `blob_surface_compass.tosc` onto each iPad via AirDrop or Files.

### John's iPad — MIDI over Network
1. Chain link → MIDI → Connection 1 → Browse
2. Select **"blobpi"** from the list

### Ben's iPad — OSC (direct IP, no mDNS)
1. Chain link → **OSC** → + → add connection:
   - **Host:** `192.168.68.197` *(John's home)* or `192.168.1.210` *(Ben's home)*
   - **Send port:** `8000`
   - **Receive port:** `9000`

Both iPads can be connected simultaneously. The Pi auto-wires any new MIDI device within 2 seconds.

> **Note:** Ben's iPad has an mDNS issue (unknown cause) that prevents it from seeing
> the Pi in TouchOSC Browse. Using OSC with a direct IP bypasses this entirely.

---

## CC Map (MIDI channel 2 / OSC `/blob/cc/{n}`)

| Control | CC | Notes |
|---|---|---|
| Servo 1–3 (NW, N, NE) | 16, 17, 18 | XY compass pads |
| Servo 4–6 (W, Ctr, E) | 20, 21, 22 | |
| Servo 7–9 (SW, S, SE) | 24, 25, 26 | |
| Blower High | 32 | |
| Breathe toggle | 33 | enables Blower Low + Breathing Rate |
| HB Speed | 34 | |
| HB Bright | 35 | |
| HALT ALL | 36 | centers all servos in one press (notify-based, no constraint drift) |
| RETRACT ALL | 37 | |
| Air Shutoff | 38 | |
| RECORD | 39 | toggle |
| PLAY | 40 | toggle, always loops |
| Blower Low | 41 | greyed when Breathe off |
| Breathing Rate | 42 | greyed when Breathe off |
| LOOP | 43 | toggle |
| Pi heartbeat | 63 | Pi→iPad only; drives the green dot in the top-right corner |

M4 receives servo CCs on **channel 1** (0xB0). TouchOSC sends on channel 2; blob_monitor normalizes.

---

## Recording and Playback

Recordings are Standard MIDI Files (Type 0, 960 PPQ) in `recordings/`.
File extensions (`.mid`) are handled automatically — never type them.

### From the iPad surface

**Naming a recording** (do this before pressing RECORD):
1. Tap the **SET** button to the right of the RECORD field
2. Type a name on the on-screen keyboard → OK
3. The name appears in the RECORD field; the Pi confirms it
4. Press RECORD — the file will be saved as `name.mid`
5. Without a name, files are auto-timestamped: `blob_YYYYMMDD_HHMMSS.mid`

**Loading a file for playback**:
1. Tap the **SET** button to the right of the PLAY field
2. Type the name (or a prefix/substring) → OK
3. Pi searches `recordings/` for a match, loads it, confirms the name in the PLAY field
4. If the name shows `?name`, no matching file was found
5. Press PLAY

**Transport buttons:**
- **RECORD** toggle → starts/stops recording; auto-saves on stop
- **PLAY** toggle → plays loaded recording, loops continuously
- Pressing PLAY while recording → stops recording and immediately starts playback
- Pressing RECORD while playing → stops playback and starts new recording
- **HALT ALL** → sends all servos to center in one press
- **RETRACT ALL** → sends all servos to their retracted positions

**After recording**, the PLAY field automatically updates to the just-saved filename
so you can press PLAY immediately without retyping.

### From the Pi keyboard (interactive mode)
```
[R]   Record / stop recording
[P]   Play / stop playback
[O]   Toggle loop mode
[Space] Pause / resume
[[]   Rewind
[L]   Load file picker (with Drive sync)
[Q]   Quit
```

### Google Drive sync
If `rclone` is configured with a `gdrive:` remote, recordings are automatically
uploaded after each save and synced on startup/playback.

---

## OLED Display (128×32 SSD1306)

- **Row 1:** `● 192.168.68.197` — `●` = iPad connected, `○` = no devices
- **Row 2:** Mode — `IDLE` / `REC` / `PLAYING MM:SS/MM:SS` / `PAUSED`
- **Row 3:** Last servo activity — `S4 063 [████░░░░]`

---

## Regenerating the TouchOSC Layout

```bash
cd /Users/jcohn/blob
python3 benmidi_v7/touchosc_gen.py --compass    # writes blob_surface_compass.tosc
```

The on-screen keyboard widget is imported automatically from
`benmidi_v7/TextInputDialog.tosc` and scaled to fit the 768×1024 portrait canvas.

---

## Troubleshooting

**iPad not connecting (John)**
- Make sure TouchOSC has Local Network permission: iOS Settings → Privacy & Security → Local Network
- Browse should show "blobpi"; if not, force-close and reopen TouchOSC
- Pi auto-wires new devices within 2 seconds of mDNS discovery

**Ben's iPad not connecting**
- Use OSC connection with direct IP (see above) — Browse will never work on Ben's iPad
- IP changes between networks: John's home = `192.168.68.197`, Ben's home = `192.168.1.210`
- Can also try `blobpi.local` as hostname if that resolves on the current network

**Servos not responding**
- Check M4 is connected: `aconnect -l` on Pi should show "Feather M4 CAN"
- M4 auto-reconnects if USB is power-cycled
- HALT ALL button centers all 9 servos reliably in a single press

**Feedback not working (buttons/sliders not updating on iPad)**
- Feedback uses MIDI channel 2 (0xB1) for MIDI-connected iPads
- OSC feedback sent to port 9000 on Ben's iPad
- If buttons stay out of sync, restart blob-monitor: `sudo systemctl restart blob-monitor`

**Pi stuck in play mode**
- HALT ALL stops servos but doesn't stop playback
- Press PLAY button again to toggle playback off
- If unresponsive: `sudo systemctl restart blob-monitor` resets to IDLE

**Play not loading the typed filename**
- Type the name via SET button *before* pressing PLAY
- The PLAY field confirms the loaded file (shows `?name` if not found)
- Names are matched by prefix or substring — partial names work
- Never include `.mid` in the name field; it is added/stripped automatically

**Pi IP changed**
- Use `blobpi.local` instead of a hardcoded IP — resolves via mDNS on any network

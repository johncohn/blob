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
  blob1.band/                GarageBand session for editing recordings
  bentest*.mid               Test recordings
recordings/                  MIDI recordings (auto-named or custom-named)
  latest.mid                 Symlink/copy of most recent recording
blob_surface_compass.tosc    TouchOSC layout (compass layout — the active one)
blob_surface.tosc            TouchOSC layout (legacy grid layout — not used)
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
| HALT ALL | 36 | sends center (64) to all servos ×4 |
| RETRACT ALL | 37 | |
| Air Shutoff | 38 | |
| RECORD | 39 | toggle |
| PLAY | 40 | toggle, always loops |
| Blower Low | 41 | greyed when Breathe off |
| Breathing Rate | 42 | greyed when Breathe off |
| LOOP | 43 | toggle |
| Pi heartbeat | 63 | Pi→iPad only; green dot in top-right corner |

M4 receives servo CCs on **channel 1** (0xB0). TouchOSC sends on channel 2; blob_monitor normalizes.

---

## Recording and Playback

Recordings are Standard MIDI Files (Type 0, 960 PPQ) in `recordings/`.

### From the iPad surface
- **RECORD** button → starts recording; press again to stop and save
- **PLAY** button → plays latest recording, loops continuously
- **LOOP** button → same as PLAY
- Pressing PLAY while recording → stops recording and immediately starts playback
- Pressing RECORD while playing → stops playback and starts new recording

### Custom filenames (via OSC)
Send an OSC string message **before** pressing RECORD:
- Path: `/blob/record/filename`, argument: `"song_name"` → saves as `song_name.mid`
- Path: `/blob/play/filename`, argument: `"song_name"` → loads file matching that name

Without a custom name, recordings are auto-named `blob_YYYYMMDD_HHMMSS.mid`.

### From the Pi keyboard (interactive mode)
```
[R]   Record / stop recording
[P]   Play / stop playback
[O]   Toggle loop mode
[Space] Pause / resume
[[]   Rewind
[L]   Load file picker
[Q]   Quit
```

### Google Drive sync
If `rclone` is configured with a `gdrive:` remote, recordings are automatically
uploaded after each save and synced on startup.

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

---

## Troubleshooting

**iPad not connecting (John)**
- Make sure TouchOSC has Local Network permission: iOS Settings → Privacy & Security → Local Network
- Browse should show "blobpi"; if not, force-close and reopen TouchOSC
- Pi auto-wires new devices within 2 seconds of mDNS discovery

**Ben's iPad not connecting**
- Ben's iPad has an mDNS issue (cause unknown); use OSC connection with direct IP (see above)
- IP changes between John's home (192.168.68.197) and Ben's home (192.168.1.210)
- Can use `blobpi.local` as hostname if mDNS resolves on that network

**Servos not responding**
- Check M4 is connected via USB: `aconnect -l` on Pi should show "Feather M4 CAN"
- M4 auto-reconnects if USB is power-cycled (blob_monitor detects and reopens port)
- HALT ALL button sends center value (64) ×4 to guarantee stop

**Feedback not working (buttons not toggling)**
- Feedback uses MIDI channel 2 (0xB1) — this matches TouchOSC's configured channel
- BlobFeedback ALSA port should show in `aconnect -l`; if missing, restart blob-monitor

**Pi IP changed**
- Use `blobpi.local` (mDNS hostname) instead of IP — always resolves on any network

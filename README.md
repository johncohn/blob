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
monitor.sh                   Launcher used on the Pi (port-name hints for blob_monitor)
midi_preview.py              Make a recording audible/visible in GarageBand
blob_surface_compass.tosc    TouchOSC layout (compass layout — the only active one)
blob_surface.tosc            Old grid layout (superseded; `touchosc_gen.py` without --compass)
benmidi_v7/
  benmidi_v7.ino             Feather M4 CAN firmware (MIDI CC → PCA9685 servo PWM)
  touchosc_gen.py            Generates the TouchOSC layout file
  TextInputDialog.tosc       On-screen keyboard widget (imported into layout)
  blob1.band/                GarageBand session for editing recordings
  bentest*.mid               Test recordings
  README.md, TOUCHOSC.md,    HISTORICAL — MIDI Fighter Twister / Mac-hub era docs.
  RECORDING_SETUP.md         Firmware details still apply; workflows do not.
  midi_session.py,           HISTORICAL — Mac-side record/play tools from before the Pi
  midi_led_router.py, run_*.sh
recordings/                  MIDI recordings (named or auto-timestamped)
  latest.mid                 Copy of most recent recording
archive/                     Old code and experiments
```

**Lives only on the Pi (not in this repo):** the `blob-monitor` systemd unit, `rtpmidid`
(Network MIDI daemon that exposes iPads as ALSA ports), the Python venv, `rclone` config,
and the Pi's own `/home/pi/recordings/` (the repo copy is just whatever was scp'd back).

---

## How the servos actually move (read this first)

The servos are **speed-controlled, not position-controlled**. In `benmidi_v7.ino`:

- CC value **64 = stop** (1500 µs pulse). Above/below 64 drives the actuator one way or the
  other, faster the farther from 64. A **±4 deadband** around the midpoint = stopped.
- So a TouchOSC pad left off-center keeps that servo **moving** until it hits its end.
  Pads do **not** spring back on release — **double-tap** a pad to recenter it (stop),
  or press **HALT ALL**, which sends 64 to every servo.
- Recordings therefore store *speed over time*; playback repeats the motion, not absolute
  positions, so drift between loops is expected.
- Firmware listens to **channel 1** CCs 16–18, 20–22, 24–26 → PCA9685 (I2C 0x40) channels
  0,1,2,4,5,6,8,9,10. The heartbeat and air CCs are handled separately — see
  "Heartbeat lights and breathing" below.
- **RETRACT ALL** works in the surface, not the firmware: its Lua drives every pad to its
  full-speed end, and those pad CCs move the servos. Press HALT ALL to stop.
- Pulse range is inverted (`USMIN 2400`, `USMAX 600`) for this actuator model.

Each XY pad is constrained to one axis (N/S/CTR vertical, E/W horizontal, diagonals
diagonal) by Lua in `touchosc_gen.py` (`_xy_script`).

### Feather firmware

Flash `benmidi_v7/benmidi_v7.ino` (board: Adafruit Feather M4 CAN).
Libraries: `MIDIUSB`, `Adafruit_NeoPixel`, `Adafruit_PWMServoDriver`.

Flashing from the Mac (the normal `arduino-cli upload` / IDE Upload fails with
"No device found" on this setup, so use the UF2 drive instead):
1. Move the Feather's USB from the Pi to the Mac.
2. Double-tap the Feather's reset button: LED goes green and a `FTHRCANBOOT` drive mounts.
3. Build and copy:
   ```bash
   arduino-cli compile -b adafruit:samd:adafruit_feather_m4_can --output-dir /tmp/bm benmidi_v7
   python3 uf2conv.py -c -b 0x4000 -f 0x55114460 -o /tmp/bm/benmidi_v7.uf2 /tmp/bm/benmidi_v7.ino.bin
   cp /tmp/bm/benmidi_v7.uf2 /Volumes/FTHRCANBOOT/
   ```
   (`uf2conv.py` is Microsoft's converter; a copy ships with the RP2040 Arduino core under
   `~/Library/Arduino15/packages/rp2040/hardware/rp2040/*/tools/`.) The drive vanishes when
   it's done and the board restarts.
4. Plug the Feather back into the Pi. blob-monitor reconnects by itself within a few seconds.

 The NeoPixel (pin 8)
shows the last-moved servo's colour, brightness = CC value. The Channel-2 double-click /
retract logic is left over from the MIDI Fighter Twister and is never triggered by the Pi
(blob_monitor forwards everything on channel 1).

---

## Heartbeat lights and breathing

All on the Feather (`benmidi_v7.ino`). The iPad sliders only send **settings**
(rate, brightness, speeds); the Feather generates the heartbeat and breathing waveforms
itself. The Pi already forwards, records and plays back those CCs like the servo CCs.
It also stores the current settings at t=0 of each recording, and re-sends them when
the Feather reconnects.

### Feather pins

| Pin | Use | Notes |
|---|---|---|
| D5 | Blower PWM → gate of low-side FET | Hardware timer (TCC1); drain pulled up to 12 V (~1 kΩ) = blower control line |
| D6 | Vent solenoid → gate of power FET | HIGH = valve open. Logic-level FET, 10 kΩ gate pull-down, flyback diode on coil |
| D9 | Heartbeat puck data → 330 Ω → puck 0 DIN | |
| SDA/SCL | PCA9685 servo driver | unchanged |

### Behaviour

| Control | CC | Effect |
|---|---|---|
| HB SPEED | 34 | 30 → 180 BPM. Double "lub-dub" pulse per beat |
| HB BRIGHT | 35 | Peak red brightness; 0 = dark |
| BLOW HI | 32 | Breathe off: steady blower speed. Breathe on: peak inhale speed. **0 = blower off** |
| BREATHE | 33 | On = breathing cycle; each switch-on starts with an inhale |
| BLOW LO | 41 | Blower speed at the start/end of each inhale |
| RATE | 42 | 12 s per breath (5/min) → 3 s (20/min) |
| AIR SHUTOFF | 38 | Upper half = blower stopped + vent open (overrides everything) |

Breath cycle: **inhale** (first 45%) = vent closed, blower swells BLOW LO → BLOW HI → BLOW LO;
**exhale** (remaining 55%) = blower stopped, vent open. At power-up everything is
off/dark/closed until the iPad sends values. The Feather keeps going with the last settings
if the Pi drops. Constants such as BPM range, breath period range, inhale share and pulse
shape are `#define`s at the top of the sketch.

**Schematic:** `hardware/blob_peripherals.kicad_sch` (KiCad 10; PDF alongside). It's
generated by `hardware/gen_schematic.py`, so edit the script and re-run it. Editing the
schematic in KiCad also works, but re-running the script overwrites those edits.

### Puck chain wiring (Adafruit 5408 4 W RGBW)

```
Feather D9 ─330Ω─► puck 0 (dark) ─► puck 1 (dark) ─► … ─► 8 heart pucks (pulse red)
             +5V from Feather USB pin      +5V from big supply at every puck
             through a 1N4001 (~4.3 V)     (positives NOT joined to the Feather side)
GND: common everywhere (Feather GND = big supply GND), heavy wire.
```

- **Puck 0 is the level shifter:** at ~4.3 V supply it accepts the Feather's 3.3 V data and
  re-drives it at 4.3 V, which the 5 V pucks accept. The firmware keeps it dark, so it
  draws almost nothing from the Pi's USB.
- **Do not carry +5 V from puck 0's output to puck 1.** Run only DOUT and GND onward. The
  pucks pass +5 V through, so a connected wire would tie the Pi's USB supply to the big supply.
- Repeater pucks every ~4 ft regenerate data and stay dark. Set `PUCK_REPEATERS` in the
  sketch to the real count, including puck 0.
- Power: red only ≈ 0.2 A per heart puck at full (≈1.6 A for 8). Size the supply for
  all pucks at full white (0.8 A each) in case of a data glitch. Fit 1000 µF across the
  supply at the heart string.
- On boot the heart string flashes dim red for 0.4 s as a chain check. If it flashes
  green, change `PUCK_TYPE` to `NEO_RGBW`.

### Blower and solenoid — verify on the bench before trusting
- **Speed encoding (bench-verified with `alia_blinky-main/fantest`).** Fixed 25 kHz
  carrier; speed = duty cycle on the blower's control line, 0–100 % (the label's 15–32 kHz
  is the accepted carrier range, not the speed control). Slider 0–127 maps straight to
  0–100 %; the FET inverts, so the pin gets 100 % − speed. Stopped = line held at 0 V.
- **Full-speed burst on reset.** During upload, reset or early boot the pin floats, the FET
  is off and the pull-up drives the line to 12 V = full speed. Expect a short burst; a
  10 kΩ pull-up from the FET gate to 3.3 V would hold the blower stopped instead.
- **Solenoid (US Solid USS2-00103, 12 V NC, 1½").** Large valves like this are often
  pilot-operated and need some pressure difference to open fully. Confirm it really vents at
  balloon pressure. Its FET must be logic-level (fully on at 3.3 V gate, e.g. IRLB8721).

---

## Pi Setup

**Hardware:** Raspberry Pi **Zero 2 W**, hostname `blobpi`, user `pi`.

- **Power:** use the **PWR** micro-USB port with a solid 5V / 2A+ supply and a good cable.
  A weak "dumb" wall wart or thin cable will stall the boot (green LED on, OLED blank,
  never joins WiFi). `vcgencmd get_throttled` should report `throttled=0x0`.
- **Feather:** plugs into the **USB** (data) port via an OTG cable/adapter. This is the
  Zero's only data port, so **do not enable USB-gadget networking** (`dwc2`/`g_ether`) —
  it stops the Feather from enumerating. Check with `lsusb` → `Adafruit Feather M4 CAN`.
- **Servos** must have their own power supply, never through the Pi.

The Pi runs `blob-monitor.service` (Restart=always). SSH access:
```
ssh pi@blobpi.local          # password: see password manager
```
John's Mac (`~/.ssh/id_ed25519`) is authorized for key login; `sudo` still asks for the
password. Use `blobpi.local` rather than the raw IP — the saved host key is under that name.

Saved WiFi networks on the Pi: `ORBI51` (→ `192.168.1.210`), John's home
(→ `192.168.68.197`), `johncohn6s` (phone hotspot), `GMA-WIFI_Access_Point`. To add one:
```bash
sudo nmcli dev wifi connect "SSID" password "WIFI_PASSWORD"
```

Service commands:
```bash
sudo systemctl status blob-monitor
sudo systemctl restart blob-monitor
journalctl -u blob-monitor -f       # live log (needs sudo)
```

Deploy updated `blob_monitor.py`:
```bash
ssh pi@blobpi.local 'cp /home/pi/blob_monitor.py /home/pi/blob_monitor.py.bak'
scp blob_monitor.py pi@blobpi.local:/home/pi/blob_monitor.py
# restart: the service runs as user pi with Restart=always, so no sudo is needed —
# kill the process and systemd starts the new code ~5 s later
ssh pi@blobpi.local 'kill $(systemctl show -p MainPID --value blob-monitor)'
```
(`sudo` over a non-interactive ssh — e.g. Claude Code's `!` prompt — fails because it
can't ask for the password; use the `kill` form or `ssh -t` from a real terminal.)

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

### Hearing / viewing a recording in GarageBand
Recordings hold only servo CC data, so an instrument track plays nothing. Make a preview
copy with one note track per servo (pitch follows position, C2–C6):
```bash
scp pi@blobpi.local:/home/pi/recordings/NAME.mid recordings/
python3 midi_preview.py recordings/NAME.mid      # → recordings/NAME_preview.mid
```
Drag the preview into an empty GarageBand project; each servo becomes its own instrument
track (select a track, press **Y** to change its sound). The preview is for listening
only — edits to it don't flow back to the servos.

### Google Drive sync
If `rclone` is configured with a `gdrive:` remote, recordings are automatically
uploaded after each save and synced on startup/playback.

---

## OLED Display (128×32 SSD1306)

Adafruit PiOLED on I2C address `0x3c`. It plugs straight onto **GPIO header pins 1–6**
(the corner nearest the SD card), lying over the board:

| Pin | Signal | | Pin | Signal |
|---|---|---|---|---|
| 1 | 3.3V | | 2 | 5V |
| 3 | SDA | | 4 | 5V |
| 5 | SCL | | 6 | GND |

With jumper wires only four are needed: 1→VIN, 3→SDA, 5→SCL, 6→GND. The display is
drawn by `blob-monitor`, so it stays blank until the Pi has fully booted and the service
is running.

- **Row 1:** `● 192.168.68.197` — `●` = iPad connected, `○` = no devices
- **Row 2:** Mode — `IDLE` / `REC` / `PLAYING MM:SS/MM:SS` / `PAUSED`
- **Row 3:** Last servo activity — `S4 063 [████░░░░]`. The index is **0-based**
  (`S0` = servo 1/NW … `S8` = servo 9/SE); 64 = stopped.

---

## Regenerating the TouchOSC Layout

```bash
cd /Users/jcohn/blob
python3 benmidi_v7/touchosc_gen.py --compass    # writes blob_surface_compass.tosc
```

The on-screen keyboard widget is imported automatically from
`benmidi_v7/TextInputDialog.tosc` and scaled to fit the 768×1024 portrait canvas.

After regenerating, AirDrop the `.tosc` to each iPad and open it in TouchOSC.

### Servo direction

Servo direction is set in the layout, not on the Pi: the last field of each
`compass_items` entry in `touchosc_gen.py` (`invert`). Currently reversed:
**servos 2, 3, 5, 6, 9** (CC 17, 18, 21, 22, 26). The flag applies to both the MIDI and
OSC messages, so MIDI and OSC iPads behave the same. Recordings store the values as
sent, so recordings made before a direction change still play the old way.

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

**Pi won't boot / OLED blank / not on WiFi**
- Almost always power: try a better supply and cable (see Pi Setup)
- Allow ~90 s after power-on before expecting the OLED or `blobpi.local`

**Servos not responding (OLED shows slider changes)**
- Check M4 is connected: `lsusb` should list "Adafruit Feather M4 CAN" and
  `aconnect -l` should show "Feather M4 CAN". If `lsusb` shows only the root hub, check
  the OTG cable and make sure USB-gadget mode is not enabled in `/boot/firmware/cmdline.txt`
- Check the servos' own power supply is on
- M4 auto-reconnects if USB is unplugged/replugged or power-cycled: every 2 s blob-monitor
  checks `aconnect -l` and re-opens its output if the link to the Feather was dropped
  (before 2026-11-15 a replug silently left the servos dead until a restart).
  Manual fix if it ever sticks: `aconnect -l` → find "RtMidiOut Client" (e.g. 130) and
  "Feather M4 CAN" (e.g. 20), then `aconnect 130:0 20:0`

**Some servos move the wrong way**
- See "Servo direction" above — edit `invert` in `touchosc_gen.py`, regenerate, re-AirDrop
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

---

## Known gaps (as of 2026-11-15)

Found by reading the code; none are fixed yet.

- **Heartbeat/breathing only partly tested on hardware.** The firmware is flashed and the
  servos work with it (2026-11-15); the blower duty-cycle control matches the bench-tested
  `fantest` sketch but hasn't been run from TouchOSC yet, and the pucks and solenoid aren't
  wired yet. See the bench checks under "Heartbeat lights and breathing".
- **RETRACT ALL never stops by itself.** The pads stay at full speed until HALT ALL is pressed.
- **HALT ALL feedback isn't sent over OSC.** `_halt_all` sends 64 to the M4 and MIDI
  feedback only, so another OSC-connected iPad's pads don't visibly recenter (the pressing
  iPad recenters itself via Lua notify).
- **Named recordings are invisible to two fallbacks.** `load_latest()` (PLAY with nothing
  loaded) and the Pi keyboard `[L]` picker only look at `blob_*.mid`, so a fresh boot +
  PLAY picks the newest *timestamped* file, not `latest.mid` or a named one.
- **OSC peers are never forgotten** — every IP that ever sent OSC keeps getting feedback.

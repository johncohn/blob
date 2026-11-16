# Blob — notes for Claude

Kinetic art piece: iPad TouchOSC → Pi Zero 2 W (`blob_monitor.py`) → Feather M4 CAN
(USB MIDI) → PCA9685 → 9 speed-controlled servo actuators. Full docs: `README.md`
(architecture, CC map, known gaps), `QUICKSTART.md` (bench bring-up).

## Orientation
- `blob_monitor.py` — the whole Pi service. Threads: rtmidi callback (`_on_midi_inner`),
  OSC UDP server :8000 (`_osc_handle`, hand-rolled parser), `_wire_ipad` (polls
  `aconnect -l` every 2 s and wires rtpmidid ports ↔ RtMidiIn / BlobFeedback),
  heartbeat CC63, M4 reconnect, playback (`_play_fn`), OLED, rclone Drive sync.
  Headless when stdin isn't a TTY (systemd); curses UI otherwise.
- `benmidi_v7/touchosc_gen.py --compass` regenerates `blob_surface_compass.tosc`
  (zlib-compressed XML). Servo direction = `invert` in `compass_items`. XY-pad Lua lives
  in `_xy_script` — see TouchOSC Lua lessons in Claude memory before editing.
- `benmidi_v7/benmidi_v7.ino` — Feather firmware (the current one; extend it, don't
  replace it). Servos: ch1 CCs 16-18/20-22/24-26, 64 = stop. Also generates the heartbeat
  (NeoPixel pucks on D9), blower PWM (D5, hardware TCC1, fixed 25 kHz, duty = speed,
  matching `~/alia_blinky-main/fantest`) and vent solenoid (D6) from
  CCs 32-35/38/41/42. Build check:
  `arduino-cli compile -b adafruit:samd:adafruit_feather_m4_can benmidi_v7`.
- Pi `ENV_CCS` in blob_monitor: snapshot at t=0 of each recording, re-sent on M4 reconnect.
- `benmidi_v7/{README,TOUCHOSC,RECORDING_SETUP}.md`, `midi_session.py`,
  `midi_led_router.py`, `blob_surface.tosc` are historical (Twister/Mac era).

## Conventions / invariants
- iPad→Pi MIDI arrives on ch2; Pi normalizes to ch1 for the M4; feedback to iPads on ch2
  (MIDI) and `/blob/cc/{n}` float 0–1 to UDP :9000 (OSC).
- Every surface control sends MIDI **and** OSC; keep both paths in sync when changing CCs.
- Filenames: never expose `.mid` to the user; `_strip_mid` everywhere.
- Air safety (`updateAir` in benmidi_v7.ino): the vent never opens until the blower has been
  stopped `SPINDOWN_WAIT`; the blower never starts until the vent has been shut
  `VENT_CLOSE_LEAD`. These interlocks run after every mode (breathe, steady, AIR SHUTOFF) —
  keep any new air behaviour above them, and keep the tests in `tests/firmware/test.cpp`.
- AIR SHUTOFF (CC 38) is a toggle button in the compass surface, not a fader.

## Deploy / test
- Pi: `ssh pi@blobpi.local` (key auth from this Mac; sudo needs the password — ask the user).
- Deploy: back up, `scp blob_monitor.py pi@blobpi.local:/home/pi/`, then restart without sudo:
  `ssh pi@blobpi.local 'kill $(systemctl show -p MainPID --value blob-monitor)'`
  (runs as pi, `Restart=always`, back in ~5 s). Check with `aconnect -l` that
  "RtMidiOut Client" is "Connecting To" the Feather. `journalctl` needs sudo.
- Flash Feather: `arduino-cli upload` fails ("No device found"); user moves USB to the Mac;
  open the port at 1200 baud (python termios, see README) or have the user double-tap reset
  → `/Volumes/FTHRCANBOOT`, then compile with `--output-dir`, convert
  with `uf2conv.py -c -b 0x4000 -f 0x55114460` (in the rp2040 core's tools dir) and `cp`
  the .uf2 onto the drive. Steps in README "Feather firmware".
- `tests/run.sh` — host-side checks, no hardware: firmware logic compiled against mocks
  (`tests/firmware/`), blob_monitor with fake MIDI ports (`tests/test_monitor.py`), and an
  arduino-cli build. Run it after any change. Real verification still needs the Pi + iPad +
  Feather powered on.
- Repo is **public** on GitHub (`johncohn/blob`) — never commit passwords/IPs beyond
  the LAN addresses already documented.

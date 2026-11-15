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
- `benmidi_v7/benmidi_v7.ino` — Feather firmware. CC 64 = stop; only ch1 CCs 16-18,
  20-22, 24-26 do anything.
- `benmidi_v7/{README,TOUCHOSC,RECORDING_SETUP}.md`, `midi_session.py`,
  `midi_led_router.py`, `blob_surface.tosc` are historical (Twister/Mac era).

## Conventions / invariants
- iPad→Pi MIDI arrives on ch2; Pi normalizes to ch1 for the M4; feedback to iPads on ch2
  (MIDI) and `/blob/cc/{n}` float 0–1 to UDP :9000 (OSC).
- Every surface control sends MIDI **and** OSC; keep both paths in sync when changing CCs.
- Filenames: never expose `.mid` to the user; `_strip_mid` everywhere.

## Deploy / test
- Pi: `ssh pi@blobpi.local` (key auth from this Mac; sudo needs the password — ask the user).
- Deploy: `scp blob_monitor.py pi@blobpi.local:/home/pi/` then
  `ssh pi@blobpi.local 'sudo systemctl restart blob-monitor'`; watch `journalctl -u blob-monitor -f`.
- No automated tests. Syntax/lint locally: `python3 -m py_compile blob_monitor.py`,
  `uv run ruff check`. Real verification needs the Pi + iPad + Feather powered on.
- Repo is **public** on GitHub (`johncohn/blob`) — never commit passwords/IPs beyond
  the LAN addresses already documented.

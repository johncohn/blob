# Blob — Quickstart (Bench Test)

Fastest path to "servos move when I touch the iPad." For full details see `README.md`.

## What you need

- Raspberry Pi Zero 2 W (running `blob-monitor` service), powered from its **PWR** port
  by a solid 5V / 2A+ supply and a good cable — a weak wall wart or thin cable stalls the
  boot (green LED on, OLED blank, Pi never joins WiFi)
- Adafruit Feather M4 CAN, plugged into the Pi's **USB** (data) port through an **OTG**
  cable/adapter, connected to the 9 servos
- Servo power supply for the Feather/servos (the Pi can't power them)
- PiOLED display seated on GPIO pins 1–6 (corner nearest the SD card) — see README
- iPad(s) with TouchOSC installed and `blob_surface_compass.tosc` already imported
  (Files app → AirDrop/copy the `.tosc` onto the iPad, then in TouchOSC: Files → Import)
- A WiFi network that the Pi and every iPad can join

---

## 1. WiFi — get everyone on the same network

The Pi and each iPad must be on the **same WiFi network/subnet** — there's no separate
"Blob network," it just needs to be whatever WiFi is available at the venue (e.g. "John's
home" or "Ben's home" networks referenced in the README).

1. Connect the Pi to that WiFi (or plug it into Ethernet if the network supports it).
2. Connect every iPad to the **same** WiFi network — not cellular, not a different SSID.
3. Give the Pi ~30 seconds to boot and join the network.

Two different iPad connection methods are supported, and each has its own WiFi quirk:

- **MIDI-over-network (John's iPad)** relies on **mDNS/Bonjour** to discover the Pi as
  "blobpi" — this generally works automatically once both are on the same WiFi, as long
  as the network doesn't block mDNS (some guest/hotel networks do).
- **OSC direct-IP (Ben's iPad)** does **not** need mDNS — it just needs to reach the Pi's
  IP address directly, so it works even on networks where mDNS is flaky. You do need to
  know the Pi's current IP on that network (see below).

### Finding the Pi's IP on a new network

- Check the **OLED display** on row 1 — it shows the Pi's current IP (`● 192.168.x.x`).
  Give the Pi ~90 s after power-on; the OLED stays blank until it has fully booted.
- Known networks: `ORBI51` → `192.168.1.210`, John's home → `192.168.68.197`.
- Or SSH in once via `blobpi.local` (works if mDNS resolves) and run `hostname -I`.
- Or check your router's connected-devices list for `blobpi`.

---

## 2. Confirm the Pi service is running

```bash
ssh pi@blobpi.local          # password: see password manager
sudo systemctl status blob-monitor
```

Should show `active (running)`. If not:
```bash
sudo systemctl restart blob-monitor
journalctl -u blob-monitor -f     # watch live log while you test
```

---

## 3. Confirm the Feather is talking to the Pi

Still on the Pi:
```bash
lsusb | grep -i feather          # Adafruit Feather M4 CAN
aconnect -l | grep -i feather
```
You should see a "Feather M4 CAN" client. If it's missing, check the OTG cable (a plain
micro-USB→USB-C cable won't work) and power-cycle the Feather — `blob_monitor.py`
auto-reconnects once it reappears. USB-gadget networking must stay **off**: it takes over
the Zero's only USB port and hides the Feather.

---

## 4. Connect John's iPad (MIDI over network)

1. Open TouchOSC → load the compass layout if not already loaded.
2. Chain link icon (top) → **MIDI** → Connection 1 → **Browse**.
3. Select **"blobpi"** from the list.
4. Watch the green dot in the top-right corner of the surface — it should go live within
   a few seconds (Pi heartbeat, CC63).

If "blobpi" doesn't show up in Browse: iOS Settings → Privacy & Security → Local Network
→ make sure TouchOSC has permission, then force-close/reopen TouchOSC.

## 5. Connect Ben's iPad (OSC, direct IP)

1. Open TouchOSC → load the compass layout if not already loaded.
2. Chain link icon → **OSC** → **+** → add a connection:
   - **Host:** the Pi's current IP (see step 1 above — e.g. `192.168.68.197` at John's,
     `192.168.1.210` at Ben's, or whatever the OLED shows on a new network)
   - **Send port:** `8000`
   - **Receive port:** `9000`
3. Watch the green connection dot come up the same way.

---

## 6. Smoke test

- Nudge one servo slider (e.g. S1/NW pad) — the corresponding servo should move; the
  OLED row 3 should show `S0 ### [bar]` updating.
  Pads set **speed**, not position: the servo keeps moving while the pad is off-center.
  **Double-tap** the pad to recenter (stop).
- Check each servo's direction. Servos 2, 3, 5, 6, 9 are reversed in the layout; if any
  move the wrong way, see "Servo direction" in the README.
- Press **HALT ALL** — all 9 servos should snap to center in one press.
- Press **RECORD**, wiggle a couple of controls for a few seconds, press **RECORD** again
  to stop — the file auto-saves (check `recordings/` on the Pi or the OLED log).
- Press **PLAY** — it should replay what you just recorded, looping until you press PLAY
  again, and the iPad's sliders should visibly track the playback.

If both iPads are connected, moving a control on one should also update the same control
on the other (feedback is mirrored to both).

---

## Quick troubleshooting

| Symptom | Try |
|---|---|
| Green LED on but OLED blank, Pi not on network | Power: better supply/cable, wait ~90 s |
| No green dot on either iPad | `sudo systemctl restart blob-monitor` on the Pi |
| "blobpi" missing from MIDI Browse | Check Local Network permission; confirm same WiFi; try again in ~10s |
| Ben's iPad won't connect | Don't use Browse — use direct-IP OSC (step 5); confirm the IP is current for *this* network |
| Servos don't move but OLED/dot update | `lsusb` on the Pi for the Feather; check OTG cable and servo power; power-cycle the Feather M4 |
| Some servos move the wrong way | Old `.tosc` on the iPad — AirDrop the current `blob_surface_compass.tosc` |
| One iPad's changes don't show on the other | Restart `blob-monitor`; feedback channel may have desynced |

See `README.md` for the full CC map, recording/playback naming workflow, and deeper
troubleshooting.

#!/usr/bin/env python3
"""
Generate hardware/blob_peripherals.kicad_sch — rough wiring schematic for the
Feather M4 CAN peripherals added in benmidi_v7.ino (heartbeat pucks, blower PWM,
vent solenoid).

Connections are made with short wire stubs + net labels at every pin, so parts can be
moved freely in KiCad without breaking nets. Library symbols are copied from the
installed KiCad libraries and embedded, so the file opens on any machine.

    python3 hardware/gen_schematic.py          # rewrites the .kicad_sch
"""
import math
import re
import uuid
from pathlib import Path

KICAD_SYMBOLS = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols")
HERE    = Path(__file__).resolve().parent
PROJECT = "blob_peripherals"
OUT     = HERE / f"{PROJECT}.kicad_sch"
ROOT_UUID = "6a1b0c2e-6f0b-4f7e-9d43-0b10b1ab0001"   # fixed so regenerating keeps the same sheet
STUB = 2.54


def uid():
    return str(uuid.uuid4())


# ── minimal S-expression reader/writer ─────────────────────────────────────────
def parse(text):
    toks = re.findall(r'"(?:\\.|[^"\\])*"|\(|\)|[^\s()"]+', text)
    stack = [[]]
    for t in toks:
        if t == "(":
            stack.append([])
        elif t == ")":
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(t)
    return stack[0][0]


def dump(x, ind=0):
    if not isinstance(x, list):
        return x
    if all(not isinstance(e, list) for e in x):
        return "(" + " ".join(x) + ")"
    pad = "\t" * (ind + 1)
    head = [e for e in x if not isinstance(e, list)]
    return "(" + " ".join(head) + "".join(
        "\n" + pad + dump(e, ind + 1) for e in x if isinstance(e, list)) + "\n" + "\t" * ind + ")"


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


_lib_cache = {}


def lib_symbol(lib, name):
    """Return the symbol as an embeddable lib_symbols entry named 'lib:name' (flattening 'extends')."""
    if lib not in _lib_cache:
        _lib_cache[lib] = {e[1].strip('"'): e for e in parse((KICAD_SYMBOLS / f"{lib}.kicad_sym").read_text())
                           if isinstance(e, list) and e[0] == "symbol"}
    syms = _lib_cache[lib]
    sym = syms[name]
    ext = next((e for e in sym if isinstance(e, list) and e[0] == "extends"), None)
    if ext:
        parent = syms[ext[1].strip('"')]
        pname = ext[1].strip('"')
        props = [e for e in sym if isinstance(e, list) and e[0] == "property"]
        body = []
        for e in parent:
            if isinstance(e, list) and e[0] == "property":
                continue
            if isinstance(e, list) and e[0] == "symbol":          # sub-unit: rename
                e = [e[0], e[1].replace(pname, name)] + e[2:]
            body.append(e)
        sym = body[:2] + props + body[2:]
    out = [sym[0], q(f"{lib}:{name}")] + sym[2:]
    return out


def lib_pins(sym):
    """{number: (x, y, angle)} from an embedded symbol (all units)."""
    pins = {}

    def walk(n):
        if isinstance(n, list):
            if n and n[0] == "pin":
                at = next(e for e in n if isinstance(e, list) and e[0] == "at")
                num = next(e for e in n if isinstance(e, list) and e[0] == "number")[1].strip('"')
                pins[num] = (float(at[1]), float(at[2]), float(at[3]))
            for e in n:
                walk(e)
    walk(sym)
    return pins


# ── custom symbols ─────────────────────────────────────────────────────────────
def custom_symbol(name, ref, value, left, right, w=15.24, desc=""):
    """Box symbol. left/right: [(number, pin_name)], top-to-bottom, 2.54 mm pitch, passive pins."""
    n = max(len(left), len(right))
    h = n * 2.54 + 2.54
    top = h / 2
    pins = []
    for side, plist in ((-1, left), (1, right)):
        for i, (num, pname) in enumerate(plist):
            y = top - 2.54 * (i + 1)
            x = side * (w / 2 + 2.54)
            ang = 0 if side < 0 else 180
            pins.append(f'(pin passive line (at {x:.2f} {y:.2f} {ang}) (length 2.54) '
                        f'(name {q(pname)} (effects (font (size 1.27 1.27)))) '
                        f'(number {q(num)} (effects (font (size 1.27 1.27)))))')
    text = f'''(symbol {q("blob:" + name)} (pin_numbers (hide yes)) (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)
  (property "Reference" {q(ref)} (at 0 {top + 1.27:.2f} 0) (effects (font (size 1.27 1.27))))
  (property "Value" {q(value)} (at 0 {-top - 1.27:.2f} 0) (effects (font (size 1.27 1.27))))
  (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
  (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
  (property "Description" {q(desc)} (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
  (symbol {q(name + "_0_1")} (rectangle (start {-w/2:.2f} {top:.2f}) (end {w/2:.2f} {-top:.2f})
    (stroke (width 0.254) (type default)) (fill (type background))))
  (symbol {q(name + "_1_1")} {" ".join(pins)}))'''
    return parse(text)


# ── schematic builder ──────────────────────────────────────────────────────────
POWER_NETS = ("GND", "+12V", "+5V")


class Sch:
    def __init__(self):
        self.libs, self.items = {}, []
        self.pwr_n = 0
        self.pins = {}          # "R1.2" → (x, y, dx, dy)  absolute pin end + outward direction

    def _lib(self, lib_id, sym=None):
        if lib_id not in self.libs:
            self.libs[lib_id] = sym if sym is not None else lib_symbol(*lib_id.split(":"))
        return self.libs[lib_id]

    def _instance(self, lib_id, ref, value, x, y, rot=0, hide_ref=False, text_at="right", hide_value=False):
        """Place a symbol. text_at: where Reference/Value go — right | above | box (custom box symbols)."""
        sym = self._lib(lib_id)
        pins = lib_pins(sym)
        hide = " (hide yes)" if hide_ref else ""
        vhide = " (hide yes)" if hide_value else ""
        if text_at == "box":                      # custom symbols: ref above the box, value below
            ys = [py for _, py, _ in pins.values()]
            top = max(ys) + 2.54
            rp, vp, just = (x, y - top - 1.27), (x, y + top + 5.08), "center"
        elif text_at == "above":                  # horizontal 2-pin parts: ref + value stacked above
            rp, vp, just = (x, y - 5.08), (x, y - 2.79), "center"
        elif text_at == "power_up":               # +12V / +5V: value above the arrow
            rp, vp, just = (x, y - 5.08), (x, y - 3.81), "center"
        elif text_at == "power_down":             # GND: value below the symbol
            rp, vp, just = (x, y + 5.08), (x, y + 4.83), "center"
        else:
            rp, vp, just = (x + 3.81, y - 1.27), (x + 3.81, y + 1.27), "left"
        j = "" if just == "center" else f" (justify {just})"
        fa = 90 if rot in (90, 270) else 0         # fields rotate with the symbol: undo it
        pin_s = " ".join(f'(pin {q(n)} (uuid {q(uid())}))' for n in pins)
        self.items.append(f'''(symbol (lib_id {q(lib_id)}) (at {x:.2f} {y:.2f} {rot}) (unit 1)
  (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no) (uuid {q(uid())})
  (property "Reference" {q(ref)} (at {rp[0]:.2f} {rp[1]:.2f} {fa}) (effects (font (size 1.27 1.27)){j}{hide}))
  (property "Value" {q(value)} (at {vp[0]:.2f} {vp[1]:.2f} {fa}) (effects (font (size 1.27 1.27)){j}{vhide}))
  (property "Footprint" "" (at {x:.2f} {y:.2f} 0) (effects (font (size 1.27 1.27)) (hide yes)))
  (property "Datasheet" "" (at {x:.2f} {y:.2f} 0) (effects (font (size 1.27 1.27)) (hide yes)))
  {pin_s}
  (instances (project {q(PROJECT)} (path {q("/" + ROOT_UUID)} (reference {q(ref)}) (unit 1)))))''')
        r = math.radians(rot)
        for num, (px, py, pa) in pins.items():
            ax = x + px * math.cos(r) - py * math.sin(r)          # symbol y-up → sheet y-down
            ay = y - (px * math.sin(r) + py * math.cos(r))
            out = math.radians(pa + rot + 180)                     # pin angle points into the body
            self.pins[f"{ref}.{num}"] = (round(ax, 2), round(ay, 2),
                                         round(math.cos(out)), -round(math.sin(out)))

    def part(self, lib_id, ref, value, x, y, rot=0, text_at="right"):
        self._instance(lib_id, ref, value, x, y, rot, text_at=text_at)

    def P(self, pin):
        return self.pins[pin][:2]

    # ── connection helpers ─────────────────────────────────────────────────────
    def wire(self, *pts):
        """Orthogonal polyline through pin names or (x, y) points."""
        pts = [self.P(p) if isinstance(p, str) else p for p in pts]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            self.items.append(f'(wire (pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f})) '
                              f'(stroke (width 0) (type default)) (uuid {q(uid())}))')

    def junction(self, x, y):
        self.items.append(f'(junction (at {x:.2f} {y:.2f}) (diameter 0) (color 0 0 0 0) (uuid {q(uid())}))')

    def nc(self, pin):
        x, y = self.P(pin)
        self.items.append(f'(no_connect (at {x:.2f} {y:.2f}) (uuid {q(uid())}))')

    def stub(self, pin, net, length=STUB, flag=False):
        """Short wire out of a pin ending in a power symbol or net label (optional PWR_FLAG)."""
        ax, ay, dx, dy = self.pins[pin]
        n = 3 if flag else 1
        pts = [(ax + dx * length * k, ay + dy * length * k) for k in range(n + 1) if k in (0, 1, n)]
        self.wire(*pts)
        if flag:
            self.power(net, *pts[1], flag=True)
        ex, ey = pts[-1]
        if net in POWER_NETS:
            self.power(net, ex, ey)
        else:
            self.label(net, ex, ey, {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(dx, dy)])

    def label(self, net, x, y, ang=0):
        just = "left bottom" if ang in (0, 90) else "right bottom"
        self.items.append(f'(label {q(net)} (at {x:.2f} {y:.2f} {ang}) (fields_autoplaced yes) '
                          f'(effects (font (size 1.27 1.27)) (justify {just})) (uuid {q(uid())}))')

    def power(self, net, x, y, flag=False):
        self.pwr_n += 1
        lib = "power:PWR_FLAG" if flag else f"power:{net}"
        self._instance(lib, f"#{'FLG' if flag else 'PWR'}{self.pwr_n:02d}",
                       "PWR_FLAG" if flag else net, x, y, hide_ref=True, hide_value=flag,
                       text_at="power_down" if net == "GND" else "power_up")

    def text(self, s, x, y, size=1.27, bold=False):
        b = " (bold yes)" if bold else ""
        self.items.append(f'(text {q(s)} (exclude_from_sim no) (at {x:.2f} {y:.2f} 0) '
                          f'(effects (font (size {size} {size}){b}) (justify left top)) (uuid {q(uid())}))')

    def write(self, path, title, date, rev, comments):
        libs = "\n".join(dump(v, 1) for v in self.libs.values())
        cm = " ".join(f'(comment {i} {q(c)})' for i, c in enumerate(comments, 1))
        body = "\n".join(self.items)
        path.write_text(f'''(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0")
(uuid {q(ROOT_UUID)})
(paper "A3")
(title_block (title {q(title)}) (date {q(date)}) (rev {q(rev)}) {cm})
(lib_symbols
{libs}
)
{body}
(sheet_instances (path "/" (page "1")))
(embedded_fonts no)
)
''')


def supply(s, conn, pos_net, flag_neg=True):
    """2-pin supply connector: pin 1 → left, up → pos rail; pin 2 → left, down → GND. PWR_FLAGs on the risers."""
    x1, y1 = s.P(f"{conn}.1")
    x2, y2 = s.P(f"{conn}.2")
    a, b = (x1 - 7.62, y1), (x2 - 2.54, y2)
    s.wire(f"{conn}.1", a, (a[0], a[1] - 2.54), (a[0], a[1] - 5.08))
    s.power(pos_net, a[0], a[1] - 2.54, flag=True)
    s.power(pos_net, a[0], a[1] - 5.08)
    s.wire(f"{conn}.2", b, (b[0], b[1] + 5.08), (b[0], b[1] + 7.62))
    if flag_neg:
        s.power("GND", b[0], b[1] + 5.08, flag=True)
    s.power("GND", b[0], b[1] + 7.62)


def fet_switch(s, name, n, y, gate_net, load):
    """Gate resistor + pull-down + IRLB8721 low-side switch, drawn with real wires.
    Row y = gate line. Returns drain pin name. n = index for references."""
    R_g, R_pd, Q = f"R{2 * n - 1 + (n > 1)}", f"R{2 * n + (n > 1)}", f"Q{n}"
    s.part("Device:R", R_g, "100", 121.92, y, rot=90, text_at="above")
    s.part("Device:R", R_pd, "10k", 139.70, y + 7.62)
    s.part("Transistor_FET:IRLB8721PBF", Q, "IRLB8721", 160.02, y)
    s.stub(f"{R_g}.1", gate_net, length=5.08)
    s.wire(f"{R_g}.2", (139.70, y), f"{Q}.1")
    s.wire(f"{R_pd}.1", (139.70, y))
    s.junction(139.70, y)
    s.stub(f"{R_pd}.2", "GND")
    s.stub(f"{Q}.3", "GND")
    return R_g, R_pd, Q


def main():
    s = Sch()
    s._lib("blob:Feather_M4_CAN", custom_symbol(
        "Feather_M4_CAN", "U", "Feather_M4_CAN",
        left=[("U1", "USB-C→Pi")],
        right=[("USB", "USB(5V)"), ("D5", "D5/PWM"), ("D6", "D6"), ("D9", "D9"),
               ("SDA", "SDA"), ("SCL", "SCL"), ("GND", "GND")],
        w=45.72, desc="Adafruit Feather M4 CAN running benmidi_v7.ino (only used pins shown)"))
    s._lib("blob:NeoPixel_Puck", custom_symbol(
        "NeoPixel_Puck", "P", "Adafruit 5408",
        left=[("1", "+5V"), ("2", "DIN"), ("3", "GND")],
        right=[("4", "+5V"), ("5", "DOUT"), ("6", "GND")],
        w=20.32, desc="Adafruit 5408 4W RGBW NeoPixel puck; +5V and GND pass straight through"))

    # ── Feather ───────────────────────────────────────────────────────────────
    s.text("FEATHER M4 CAN", 25.4, 78.74, 2, True)
    s.part("blob:Feather_M4_CAN", "U1", "Feather M4 CAN  (benmidi_v7.ino)", 53.34, 101.6, text_at="box")
    s.nc("U1.U1")
    for pin, net in [("USB", "USB_5V"), ("GND", "GND"), ("D5", "BLOWER_PWM"), ("D6", "SOL_DRV"),
                     ("D9", "PUCK_DATA"), ("SDA", "SDA"), ("SCL", "SCL")]:
        s.stub(f"U1.{pin}", net, length=7.62 if net != "GND" else 2.54)
    s.text("SDA / SCL → PCA9685 servo driver (unchanged)\nUSB-C → Pi Zero 2 W via OTG (Pi powers the Feather)",
           25.4, 119.38)

    # ── Blower ────────────────────────────────────────────────────────────────
    s.text("BLOWER SPEED  — Terrabloom ECMF-200-S control input", 109.22, 15.24, 2, True)
    y = 50.8
    fet_switch(s, "blower", 1, y, "BLOWER_PWM", None)
    s.part("Device:R", "R3", "1k pull-up", 162.56, 33.02)
    s.part("Connector_Generic:Conn_01x02", "J1", "to blower ctrl", 200.66, 40.64)
    s.stub("R3.1", "+12V")
    s.wire("Q1.2", (162.56, 40.64), "R3.2")
    s.wire((162.56, 40.64), "J1.1")
    s.junction(162.56, 40.64)
    s.stub("J1.2", "GND")
    s.text("BLOWER_CTRL", 172.72, 38.1)
    s.text("FET inverts the signal — firmware compensates (BLOWER_FET_INVERTS).\n"
           "Speed: fixed 25 kHz, duty 0-100 % on the line (bench-verified with fantest).\n"
           "Line at 0 V = stopped. Reset/upload: pin floats → line 12 V → brief full speed.",
           109.22, 71.12)

    # ── Solenoid ──────────────────────────────────────────────────────────────
    s.text("VENT SOLENOID  — US Solid USS2-00103, 12 V normally closed", 109.22, 88.9, 2, True)
    y = 119.38
    fet_switch(s, "solenoid", 2, y, "SOL_DRV", None)
    s.part("Device:D", "D1", "1N5819", 175.26, 105.41, rot=270)
    s.part("Connector_Generic:Conn_01x02", "J2", "solenoid coil", 213.36, 106.68)
    s.wire("Q2.2", (162.56, 109.22), (175.26, 109.22))
    s.wire((175.26, 109.22), "J2.2")
    s.junction(175.26, 109.22)
    s.stub("D1.1", "+12V")
    s.stub("J2.1", "+12V")
    s.text("SOL_LO", 182.88, 111.76)
    s.text("D6 HIGH = valve open (exhale / AIR SHUTOFF).\n"
           "10k pull-down keeps the valve shut while the Feather resets.\n"
           "Q2 must be logic-level (fully on at 3.3 V gate). D1 = flyback (1N5819 or 1N4007).", 109.22, 139.7)

    # ── 12 V supply ───────────────────────────────────────────────────────────
    s.text("12 V SUPPLY", 238.76, 15.24, 2, True)
    s.part("Connector_Generic:Conn_01x02", "J3", "12 V in", 264.16, 40.64)
    supply(s, "J3", "+12V")
    s.text("Feeds blower pull-up + solenoid.\nGND common with Feather and 5 V supply.", 238.76, 55.88)

    # ── Heartbeat pucks ───────────────────────────────────────────────────────
    s.text("HEARTBEAT PUCK CHAIN  — Adafruit 5408 4 W RGBW NeoPixel", 25.4, 160.02, 2, True)
    PY = 195.58
    xs = {"P1": 109.22, "P2": 167.64, "P3": 226.06, "P4": 284.48}
    names = {"P1": "puck 0 — dark, level shifter", "P2": "repeater(s) ~4 ft apart — dark",
             "P3": "heart puck 1 — red", "P4": "heart puck 8 — red"}
    for r, x in xs.items():
        s.part("blob:NeoPixel_Puck", r, names[r], x, PY, text_at="box")
    # Data daisy-chains DOUT → DIN. +5V/GND pass through each puck internally, but each
    # puck is fed directly from the supplies, so the pass-through outputs are left unused.
    for a, b in (("P1", "P2"), ("P2", "P3"), ("P3", "P4")):
        s.wire(f"{a}.5", f"{b}.2")
    for r in xs:
        s.stub(f"{r}.3", "GND")
        s.nc(f"{r}.4")
        s.nc(f"{r}.6")
        if r != "P1":
            s.stub(f"{r}.1", "+5V")
    s.nc("P4.5")
    # Feather side: series resistor into DIN, diode-fed supply for puck 0
    s.part("Device:R", "R6", "330", 71.12, PY, rot=90, text_at="above")
    s.stub("R6.1", "PUCK_DATA", length=5.08)
    s.wire("R6.2", "P1.2")
    s.part("Device:D", "D2", "1N4001  (→ ~4.3 V)", 71.12, 182.88, rot=180, text_at="above")
    s.stub("D2.2", "USB_5V", length=5.08)
    s.wire("D2.1", (83.82, 182.88), (83.82, PY - 2.54), "P1.1")
    s.text("PUCK0_V", 85.09, 186.69)
    s.text("+5V out NOT connected:\nkeeps the Pi/USB 5 V off the big supply.\nOnly DOUT + GND continue.",
           119.38, 172.72)
    s.text("… heart pucks 2–7 chained here …", 241.3, 185.42)
    s.text("Set PUCK_REPEATERS in benmidi_v7.ino = number of dark pucks (incl. puck 0).\n"
           "Every puck after puck 0: +5 V and GND straight from the big supply.", 147.32, 213.36)

    s.text("5 V HIGH-CURRENT SUPPLY", 330.2, 160.02, 2, True)
    s.part("Connector_Generic:Conn_01x02", "J4", "5 V in", 360.68, 182.88)
    supply(s, "J4", "+5V", flag_neg=False)
    s.part("Device:C_Polarized", "C1", "1000 µF", 345.44, 205.74)
    s.stub("C1.1", "+5V")
    s.stub("C1.2", "GND")
    s.text("Positive rail independent of the Feather;\nGND common. Put C1 at the heart string.",
           330.2, 220.98)

    s.write(OUT, "Blob — Feather M4 CAN peripherals", "2026-11-15", "B (rough)",
            ["Heartbeat pucks (D9), blower PWM (D5), vent solenoid (D6) — see README",
             "Generated by hardware/gen_schematic.py; firmware: benmidi_v7/benmidi_v7.ino"])
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()

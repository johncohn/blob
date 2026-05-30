#!/usr/bin/env python3
"""
touchosc_gen.py  —  generate blob_surface.tosc

Produces a TouchOSC layout file (modern Hexler format, v1.4+) for the Blob art piece.
Format: zlib-compressed XML with root tag <lexml version="3">.

Canvas: 1024 × 950

Left panel  (x 0–680):
  Background box behind servo grid
  3×3 servo faders   CC 16-18, 20-22, 24-26  ch2
  HALT ALL / RETRACT ALL momentary buttons
  RECORD / PLAY toggles + filename text fields

Right panel (x 702–1024):
  BLOWER header
    BREATHE toggle (full-width) — Lua greys/enables blower low + breathing rate
    BLOWER HIGH fader   CC 32
    BLOWER LOW  fader   CC 41  (greyed when breathe off)
    BREATHING RATE fader CC 42  (greyed when breathe off)
  AIR SHUTOFF fader      CC 38
  HEARTBEAT header
    HEARTBEAT fader      CC 34
    HEART BRIGHT fader   CC 35

Global:
  BREATHE toggle         CC 33
  HALT                   CC 36
  RETRACT                CC 37
  RECORD                 CC 39
  PLAY                   CC 40

Text fields send via OSC:
  /blob/record/filename  <string>
  /blob/play/filename    <string>

Usage:
    python3 touchosc_gen.py              # writes ../blob_surface.tosc
    python3 touchosc_gen.py out.tosc     # custom filename
"""

import math
import sys
import uuid
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

MIDI_CH = 1   # TouchOSC uses 0-based channels; 1 → MIDI channel 2 (0xB1)

# ── CC assignments ────────────────────────────────────────────────────────────

SERVO_CCS = [[16, 17, 18], [20, 21, 22], [24, 25, 26]]

CC_BLOWER_HIGH    = 32
CC_BREATHE        = 33
CC_HB_SPEED       = 34
CC_HB_BRIGHT      = 35
CC_HALT           = 36
CC_RETRACT        = 37
CC_SHUTOFF        = 38
CC_RECORD         = 39
CC_PLAY           = 40
CC_BLOWER_LOW     = 41
CC_BREATHING_RATE = 42
CC_LOOP           = 43
CC_CONNECTED      = 63   # Pi heartbeat: 127=online, 0=offline; drives the green dot


# ── layout constants ──────────────────────────────────────────────────────────

CANVAS_W, CANVAS_H = 1024, 950

# Left panel — servo grid (matches user's edited positions)
SV_X0   = 20
SV_Y0   = 62       # top of first fader row
SV_W    = 200
SV_H    = 170
SV_GAPX = 20
SV_GAPY = 30       # gap between label bottom and next fader top
SV_LBLH = 22

# Right panel
R_X       = 702
R_W       = CANVAS_W - R_X           # 322 px

# Blower section — 3 faders side-by-side
BL_FW   = 100      # each fader width  (3×100 + 2×8 gap = 316 ≤ 322)
BL_FH   = 145
BL_GAP  = 8
BL_Y0   = 56       # section header y

# Shutoff
SO_Y    = 330      # fader label y
SO_H    = 60

# Heartbeat
HB_Y0   = 430
HB_FW   = 150
HB_FH   = 170
HB_GAP  = R_W - 2 * HB_FW           # gap between the two faders

# Left-panel buttons
BTN_Y   = 723
BTN_H   = 65
BTN_LBL = 18

REC_Y   = 811
REC_H   = 58
PLAY_Y  = 895
PLAY_H  = 58
ABTW    = 130      # RECORD / PLAY button width
TXT_X   = SV_X0 + ABTW + 14
TXT_W   = CANVAS_W - TXT_X - 14


# ── low-level XML helpers ─────────────────────────────────────────────────────

def uid():
    return str(uuid.uuid4())

def prop_s(parent, key, val):
    p = ET.SubElement(parent, 'property', type='s')
    ET.SubElement(p, 'key').text = key
    ET.SubElement(p, 'value').text = val

def prop_b(parent, key, val: bool):
    p = ET.SubElement(parent, 'property', type='b')
    ET.SubElement(p, 'key').text = key
    ET.SubElement(p, 'value').text = '1' if val else '0'

def prop_i(parent, key, val: int):
    p = ET.SubElement(parent, 'property', type='i')
    ET.SubElement(p, 'key').text = key
    ET.SubElement(p, 'value').text = str(val)

def prop_f(parent, key, val: float):
    p = ET.SubElement(parent, 'property', type='f')
    ET.SubElement(p, 'key').text = key
    ET.SubElement(p, 'value').text = repr(float(val))

def prop_frame(parent, x, y, w, h):
    p = ET.SubElement(parent, 'property', type='r')
    ET.SubElement(p, 'key').text = 'frame'
    v = ET.SubElement(p, 'value')
    for tag, val in (('x', x), ('y', y), ('w', w), ('h', h)):
        ET.SubElement(v, tag).text = str(val)

def prop_color(parent, r, g, b, a=1.0):
    p = ET.SubElement(parent, 'property', type='c')
    ET.SubElement(p, 'key').text = 'color'
    v = ET.SubElement(p, 'value')
    for tag, val in (('r', r), ('g', g), ('b', b), ('a', a)):
        ET.SubElement(v, tag).text = repr(val)

def val_x(parent, default=0.5):
    v = ET.SubElement(parent, 'value')
    ET.SubElement(v, 'key').text = 'x'
    ET.SubElement(v, 'locked').text = '0'
    ET.SubElement(v, 'lockedDefaultCurrent').text = '0'
    ET.SubElement(v, 'default').text = repr(default)
    ET.SubElement(v, 'defaultPull').text = '0'

def val_xy(parent):
    """Two values (x, y) each defaulting to 0.5 — used by XY pad controls."""
    for key in ('x', 'y'):
        v = ET.SubElement(parent, 'value')
        ET.SubElement(v, 'key').text = key
        ET.SubElement(v, 'locked').text = '0'
        ET.SubElement(v, 'lockedDefaultCurrent').text = '0'
        ET.SubElement(v, 'default').text = repr(0.5)
        ET.SubElement(v, 'defaultPull').text = '0'

def val_text(parent, text=''):
    v = ET.SubElement(parent, 'value')
    ET.SubElement(v, 'key').text = 'text'
    ET.SubElement(v, 'locked').text = '0'
    ET.SubElement(v, 'lockedDefaultCurrent').text = '0'
    ET.SubElement(v, 'default').text = text
    ET.SubElement(v, 'defaultPull').text = '0'

def osc_cc(parent, cc, key='x'):
    """Add an OSC message /blob/cc/{cc} carrying value key as float 0-1.
    Uses OSC connection 1 — Ben enters the Pi's IP there; no mDNS needed."""
    osc = ET.SubElement(parent, 'osc')
    ET.SubElement(osc, 'enabled').text     = '1'
    ET.SubElement(osc, 'send').text        = '1'
    ET.SubElement(osc, 'receive').text     = '1'
    ET.SubElement(osc, 'feedback').text    = '0'
    ET.SubElement(osc, 'connections').text = '00001'
    trig = ET.SubElement(ET.SubElement(osc, 'triggers'), 'trigger')
    ET.SubElement(trig, 'var').text       = key
    ET.SubElement(trig, 'condition').text = 'ANY'
    part = ET.SubElement(ET.SubElement(osc, 'path'), 'partial')
    ET.SubElement(part, 'type').text       = 'CONSTANT'
    ET.SubElement(part, 'conversion').text = 'STRING'
    ET.SubElement(part, 'value').text      = f'/blob/cc/{cc}'
    ET.SubElement(part, 'scaleMin').text   = '0'
    ET.SubElement(part, 'scaleMax').text   = '1'
    arg = ET.SubElement(ET.SubElement(osc, 'arguments'), 'partial')
    ET.SubElement(arg, 'type').text       = 'VALUE'
    ET.SubElement(arg, 'conversion').text = 'FLOAT'
    ET.SubElement(arg, 'value').text      = key
    ET.SubElement(arg, 'scaleMin').text   = '0'
    ET.SubElement(arg, 'scaleMax').text   = '1'


def midi_cc(parent, cc, channel=MIDI_CH, key='x', invert=False):
    """Emit a CONTROLCHANGE MIDI message triggered by value `key` (default 'x').
    invert=True swaps scaleMin/Max so high value → CC 0, low value → CC 127.
    Use for pads where the compass direction is at the low-coordinate corner."""
    midi = ET.SubElement(parent, 'midi')
    ET.SubElement(midi, 'enabled').text     = '1'
    ET.SubElement(midi, 'send').text        = '1'
    ET.SubElement(midi, 'receive').text     = '1'
    ET.SubElement(midi, 'feedback').text    = '0'
    ET.SubElement(midi, 'connections').text = '00001'
    trig = ET.SubElement(ET.SubElement(midi, 'triggers'), 'trigger')
    ET.SubElement(trig, 'var').text       = key
    ET.SubElement(trig, 'condition').text = 'ANY'
    msg = ET.SubElement(midi, 'message')
    ET.SubElement(msg, 'type').text    = 'CONTROLCHANGE'
    ET.SubElement(msg, 'channel').text = str(channel)
    ET.SubElement(msg, 'data1').text   = str(cc)
    ET.SubElement(msg, 'data2').text   = '0'
    vals = ET.SubElement(midi, 'values')
    mv1 = ET.SubElement(vals, 'value')
    ET.SubElement(mv1, 'type').text     = 'CONSTANT'
    ET.SubElement(mv1, 'key').text      = ''
    ET.SubElement(mv1, 'scaleMin').text = '0'
    ET.SubElement(mv1, 'scaleMax').text = '15'
    mv2 = ET.SubElement(vals, 'value')
    ET.SubElement(mv2, 'type').text     = 'CONSTANT'
    ET.SubElement(mv2, 'key').text      = ''
    ET.SubElement(mv2, 'scaleMin').text = '0'
    ET.SubElement(mv2, 'scaleMax').text = '127'
    mv3 = ET.SubElement(vals, 'value')
    ET.SubElement(mv3, 'type').text     = 'VALUE'
    ET.SubElement(mv3, 'key').text      = key
    ET.SubElement(mv3, 'scaleMin').text = '127' if invert else '0'
    ET.SubElement(mv3, 'scaleMax').text = '0'   if invert else '127'

def osc_text(parent, path):
    osc = ET.SubElement(parent, 'osc')
    ET.SubElement(osc, 'enabled').text     = '1'
    ET.SubElement(osc, 'send').text        = '1'
    ET.SubElement(osc, 'receive').text     = '1'
    ET.SubElement(osc, 'feedback').text    = '0'
    ET.SubElement(osc, 'connections').text = '00001'
    trig = ET.SubElement(ET.SubElement(osc, 'triggers'), 'trigger')
    ET.SubElement(trig, 'var').text       = 'text'
    ET.SubElement(trig, 'condition').text = 'ANY'
    part = ET.SubElement(ET.SubElement(osc, 'path'), 'partial')
    ET.SubElement(part, 'type').text       = 'CONSTANT'
    ET.SubElement(part, 'conversion').text = 'STRING'
    ET.SubElement(part, 'value').text      = path
    ET.SubElement(part, 'scaleMin').text   = '0'
    ET.SubElement(part, 'scaleMax').text   = '1'
    arg = ET.SubElement(ET.SubElement(osc, 'arguments'), 'partial')
    ET.SubElement(arg, 'type').text       = 'VALUE'
    ET.SubElement(arg, 'conversion').text = 'STRING'
    ET.SubElement(arg, 'value').text      = 'text'
    ET.SubElement(arg, 'scaleMin').text   = '0'
    ET.SubElement(arg, 'scaleMax').text   = '1'


# ── control builders ──────────────────────────────────────────────────────────

def node(parent, ntype, name, locked=True):
    n = ET.SubElement(parent, 'node', ID=uid(), type=ntype)
    pr = ET.SubElement(n, 'properties')
    va = ET.SubElement(n, 'values')
    me = ET.SubElement(n, 'messages')
    ch = ET.SubElement(n, 'children')
    prop_s(pr, 'name', name)
    prop_b(pr, 'locked', locked)
    return n, pr, va, me, ch

def box(parent, name, x, y, w, h, rgb=(0.10, 0.10, 0.10)):
    _, pr, _, _, _ = node(parent, 'BOX', name)
    prop_frame(pr, x, y, w, h)
    prop_color(pr, *rgb)
    prop_b(pr, 'outline', False)

def fader(parent, name, x, y, w, h, cc=None, default=0.5,
          rgb=(0.22, 0.60, 1.0), interactive=True, script='', invert=False, osc=False):
    _, pr, va, me, _ = node(parent, 'FADER', name)
    prop_frame(pr, x, y, w, h)
    prop_color(pr, *rgb)
    prop_b(pr, 'outline', True)
    prop_b(pr, 'interactive', interactive)
    prop_i(pr, 'response', 0)
    if script:
        prop_s(pr, 'script', script)
    val_x(va, default)
    if cc is not None:
        midi_cc(me, cc, invert=invert)
        if osc:
            osc_cc(me, cc)

def _xy_script(direction):
    """
    Lua script for all 9 XY pad servo controls.
    Double-tap (0.50 s) centres the puck. Constraint locks to 1-D axis.
    N/S/CTR: x locked to 0.5 (vertical).  E/W: y locked to 0.5 (horizontal).
    NW/SE: project onto '\\' diagonal.  NE/SW: project onto '/' diagonal.
    NOTE: comparisons use '>' to avoid '<' → '&lt;' XML encoding.
    """
    header = (
        'local tapPhase = 0\n'
        'local tap1Time = -9999\n'
        'local tap1X = 0.5\n'
        'local tap1Y = 0.5\n'
        'local doCenter = false\n'
        'local upd = false\n'
        'local skip = 0\n'
        'function onValueChanged(key)\n'
        '  if key == "touch" then\n'
        '    local t = os.clock()\n'
        '    if self.values.touch then\n'
        '      skip = 0\n'
        '      local ax = self.values.x - 0.5\n'
        '      local ay = self.values.y - 0.5\n'
        '      if 0.0025 > ax*ax + ay*ay then\n'
        '        tapPhase = 0\n'
        '        doCenter = false\n'
        '      elseif tapPhase == 2 then\n'
        '        local dt = t - tap1Time\n'
        '        local dx = self.values.x - tap1X\n'
        '        local dy = self.values.y - tap1Y\n'
        '        if 0.5 > dt and 0.0025 > dx*dx + dy*dy then\n'
        '          doCenter = true\n'
        '          tapPhase = 3\n'
        '        else\n'
        '          tap1Time = t\n'
        '          tapPhase = 1\n'
        '          doCenter = false\n'
        '        end\n'
        '      else\n'
        '        tap1Time = t\n'
        '        tapPhase = 1\n'
        '        doCenter = false\n'
        '      end\n'
        '    else\n'
        '      if tapPhase == 1 then\n'
        '        tap1X = self.values.x\n'
        '        tap1Y = self.values.y\n'
        '        tapPhase = 2\n'
        '      elseif tapPhase == 3 and doCenter then\n'
        '        doCenter = false\n'
        '        tapPhase = 0\n'
        '        skip = 2\n'
        '        upd = true\n'
        '        self.values.x = 0.5\n'
        '        self.values.y = 0.5\n'
        '        upd = false\n'
        '      else\n'
        '        tapPhase = 0\n'
        '        doCenter = false\n'
        '      end\n'
        '    end\n'
    )
    if direction in ('N', 'S', 'CTR'):
        body = (
            '  elseif key == "x" and not upd then\n'
            '    upd = true\n'
            '    self.values.x = 0.5\n'
            '    upd = false\n'
        )
    elif direction in ('E', 'W'):
        body = (
            '  elseif key == "y" and not upd then\n'
            '    upd = true\n'
            '    self.values.y = 0.5\n'
            '    upd = false\n'
        )
    elif direction in ('NW', 'SE'):
        body = (
            '  elseif (key == "x" or key == "y") and not upd then\n'
            '    if skip > 0 then skip = skip - 1\n'
            '    else\n'
            '      upd = true\n'
            '      local t = (self.values.x - self.values.y) * 0.5\n'
            '      self.values.x = 0.5 + t\n'
            '      self.values.y = 0.5 - t\n'
            '      upd = false\n'
            '    end\n'
        )
    else:  # NE, SW
        body = (
            '  elseif (key == "x" or key == "y") and not upd then\n'
            '    if skip > 0 then skip = skip - 1\n'
            '    else\n'
            '      upd = true\n'
            '      local t = (self.values.x + self.values.y - 1.0) * 0.5\n'
            '      self.values.x = 0.5 + t\n'
            '      self.values.y = 0.5 + t\n'
            '      upd = false\n'
            '    end\n'
        )
    return header + body + '  end\nend'


def xy_compass(parent, name, cx, cy, size, direction, cc,
               rgb=(0.22, 0.60, 1.0), invert=False, osc=False):
    """
    Square XY pad centred at (cx, cy), constrained to the given compass direction.
    N/S/CTR send MIDI from 'y'; all others from 'x'.
    invert=True reverses the MIDI scale so the compass-direction corner → CC 127.
    Needed for N (top=y=0), W (left=x=0), NW (corner=0,0), SW (corner=0,y).
    """
    midi_key = 'y' if direction in ('N', 'S', 'CTR') else 'x'
    _, pr, va, me, _ = node(parent, 'XY', name)
    prop_frame(pr, cx - size // 2, cy - size // 2, size, size)
    prop_color(pr, *rgb)
    prop_b(pr, 'outline', True)
    prop_s(pr, 'script', _xy_script(direction))
    val_xy(va)
    midi_cc(me, cc, key=midi_key, invert=invert)
    if osc:
        osc_cc(me, cc, key=midi_key)


# Fader double-tap-to-center script (0.50 s window, fires on touch-DOWN).
_FADER_CENTERER = (
    'local lastTapTime = 0\n'
    'function onValueChanged(key)\n'
    '  if key ~= "touch" or not self.values.touch then return end\n'
    '  local t = os.clock()\n'
    '  if 0.50 > t - lastTapTime then\n'
    '    self.values.x = 0.5\n'
    '    lastTapTime = 0\n'
    '  else\n'
    '    lastTapTime = t\n'
    '  end\n'
    'end'
)

def fader_compass(parent, name, cx, cy, size, direction, cc, invert=False,
                  rgb=(0.22, 0.60, 1.0)):
    """True 1-D fader for compass linear directions (N/S/CTR/E/W).
    Centred at (cx, cy) within the same PAD-sized region as the XY pads.
    Narrow dimension = size//2 for a thumb-friendly touch target.
    Double-tap centres the slider. No mask boxes needed.
    """
    tw = max(size // 2, 60)    # narrow dimension — thumb-friendly
    if direction in ('N', 'S', 'CTR'):   # vertical fader (h > w)
        fx, fy, fw, fh = cx - tw // 2, cy - size // 2, tw, size
    else:                                # E, W — horizontal fader (w > h)
        fx, fy, fw, fh = cx - size // 2, cy - tw // 2, size, tw
    fader(parent, name, fx, fy, fw, fh, cc,
          default=0.5, rgb=rgb, invert=invert, script=_FADER_CENTERER)


def diagonal_mask(parent, name, cx, cy, size, slash=False):
    """
    Smooth diagonal rectangular track — thin horizontal strips (~4 px each).
    Leaves a band of width size//3 centred on the diagonal, matching the
    visible width of the linear slider masks on N/S/E/W/CTR pads.
    slash=False → '\' track (NW/SE);  slash=True → '/' track (NE/SW).
    """
    track_w = size // 3
    step    = max(2, size // 35)          # ≈ 4 px for PAD=130
    n       = (size + step - 1) // step
    px, py  = cx - size // 2, cy - size // 2
    half    = track_w // 2
    BG      = (0.10, 0.10, 0.10)

    idx = 0
    for i in range(n):
        by = py + i * step
        bh = min(step, size - i * step)
        if bh <= 0:
            break
        # Track centre in screen-x at this row.
        # '\': starts left at top, ends right at bottom (puck goes top-left → bottom-right).
        # '/': starts right at top, ends left at bottom (puck goes top-right → bottom-left).
        xc = px + i * step + step // 2 if not slash else px + size - i * step - step // 2
        lw = max(0, xc - half - px)
        rx = min(xc + half + 1, px + size)
        rw = max(0, px + size - rx)
        if lw > 0:
            box(parent, f'{name}_mask{idx}', px, by, lw, bh, rgb=BG)
            idx += 1
        if rw > 0:
            box(parent, f'{name}_mask{idx}', rx, by, rw, bh, rgb=BG)
            idx += 1


def linear_mask(parent, name, cx, cy, size, vertical=True):
    """
    Mask the sides of a linear XY pad so only the slider track is visible.
    vertical=True:  masks left+right (for N/S/CTR, x locked).
    vertical=False: masks top+bottom (for E/W, y locked).
    """
    track_w = size // 3
    px, py  = cx - size // 2, cy - size // 2
    side    = (size - track_w) // 2
    BG = (0.10, 0.10, 0.10)
    if vertical:
        box(parent, f'{name}_maskL', px,                  py, side, size, rgb=BG)
        box(parent, f'{name}_maskR', px + side + track_w, py, side, size, rgb=BG)
    else:
        box(parent, f'{name}_maskT', px, py,                  size, side, rgb=BG)
        box(parent, f'{name}_maskB', px, py + side + track_w, size, side, rgb=BG)


def button(parent, name, x, y, w, h, cc=None, toggle=False,
           rgb=(0.85, 0.15, 0.15), script='', osc=False):
    _, pr, va, me, _ = node(parent, 'BUTTON', name)
    prop_frame(pr, x, y, w, h)
    prop_color(pr, *rgb)
    prop_i(pr, 'buttonType', 1 if toggle else 0)
    prop_b(pr, 'outline', True)
    if script:
        prop_s(pr, 'script', script)
    val_x(va, 0.0)
    if cc is not None:
        midi_cc(me, cc)
        if osc:
            osc_cc(me, cc)

def label(parent, name, x, y, w, h, text, size=13, align=2,
          rgb=(0.80, 0.80, 0.80)):
    _, pr, va, _, _ = node(parent, 'LABEL', name)
    prop_frame(pr, x, y, w, h)
    prop_color(pr, *rgb)
    prop_i(pr, 'textSize', size)
    prop_i(pr, 'textAlignH', align)
    prop_b(pr, 'background', False)
    prop_b(pr, 'outline', False)
    val_text(va, text)

def text_input(parent, name, x, y, w, h, osc_path, placeholder='session.mid'):
    _, pr, va, me, _ = node(parent, 'TEXT', name, locked=False)
    prop_frame(pr, x, y, w, h)
    prop_color(pr, 0.22, 0.22, 0.22)
    prop_b(pr, 'outline', True)
    prop_b(pr, 'background', True)
    prop_i(pr, 'textSize', 16)
    prop_i(pr, 'textAlignH', 1)
    val_text(va, placeholder)
    osc_text(me, osc_path)


# ── layout ────────────────────────────────────────────────────────────────────

def conn_indicator(parent, name, x, y, w=28, h=28):
    """Small LED dot: grey when Pi is offline, green when Pi heartbeat (CC63) arrives."""
    script = (
        'function onValueChanged(key)\n'
        '  if key == "x" then\n'
        '    if self.values.x > 0 then\n'
        '      self.color = Color(0.1, 0.9, 0.2)\n'
        '    else\n'
        '      self.color = Color(0.25, 0.25, 0.25)\n'
        '    end\n'
        '  end\n'
        'end'
    )
    _, pr, va, me, _ = node(parent, 'BUTTON', name)
    prop_frame(pr, x, y, w, h)
    prop_color(pr, 0.25, 0.25, 0.25)
    prop_i(pr, 'buttonType', 0)
    prop_b(pr, 'outline', True)
    prop_b(pr, 'interactive', False)
    prop_s(pr, 'script', script)
    val_x(va, 0.0)
    midi_cc(me, CC_CONNECTED)


def build_layout():
    root = ET.Element('lexml', version='3')
    rn   = ET.SubElement(root, 'node', ID=uid(), type='GROUP')
    rp   = ET.SubElement(rn, 'properties')
    ET.SubElement(rn, 'values')
    ET.SubElement(rn, 'messages')
    cv   = ET.SubElement(rn, 'children')

    prop_s(rp, 'name', 'blob_surface')
    prop_frame(rp, 0, 0, CANVAS_W, CANVAS_H)
    prop_color(rp, 0.15, 0.15, 0.15)


    # ── title ─────────────────────────────────────────────────────────────────
    label(cv, 'title', 0, 4, CANVAS_W, 46, 'BLOB CONTROL', size=26, align=2)
    conn_indicator(cv, 'pi_conn', CANVAS_W - 36, 8, 28, 28)
    label(cv, 'lbl_conn', CANVAS_W - 36, 38, 28, 12, 'PI', size=9, align=2)

    # ── servo background box ──────────────────────────────────────────────────
    box(cv, 'servo_bg', 10, 45, 662, 660, rgb=(0.10, 0.10, 0.10))

    # ── 3×3 servo faders ─────────────────────────────────────────────────────
    label(cv, 'hdr_servo', SV_X0, SV_Y0 - 6, 640, 20,
          'SERVO MATRIX', size=12, align=1)

    # Double-tap any servo to center it. Pure local state, no shared globals.
    servo_script = (
        'local lastTapTime = 0\n'
        'local pendingCenter = false\n'
        'function onValueChanged(key)\n'
        '  if key ~= "touch" then return end\n'
        '  local touching = self.values.touch\n'
        '  if touching then\n'
        '    local t = os.clock()\n'
        '    local dt = t - lastTapTime\n'
        '    if (0.35 > dt) then\n'
        '      pendingCenter = true\n'
        '      lastTapTime = 0\n'
        '    else\n'
        '      pendingCenter = false\n'
        '      lastTapTime = t\n'
        '    end\n'
        '  else\n'
        '    if pendingCenter then\n'
        '      self.values.x = 0.5\n'
        '      pendingCenter = false\n'
        '    end\n'
        '  end\n'
        'end'
    )

    for row in range(3):
        for col in range(3):
            cc  = SERVO_CCS[row][col]
            idx = row * 3 + col
            fx  = SV_X0 + col * (SV_W + SV_GAPX)
            fy  = SV_Y0 + row * (SV_H + SV_LBLH + SV_GAPY)
            fader(cv, f'servo{idx}', fx, fy, SV_W, SV_H, cc,
                  script=servo_script, osc=True)
            label(cv, f'lbl_sv{idx}', fx, fy + SV_H + 4, SV_W, SV_LBLH,
                  str(idx + 1), size=16, align=2)

    # ── blower section ────────────────────────────────────────────────────────
    label(cv, 'hdr_blower', R_X, BL_Y0, R_W, 20, 'BLOWER', size=13, align=1)

    # Breathe toggle — Lua greys/enables blower_low and breathing_rate
    breathe_script = (
        'function onValueChanged(key)\n'
        '  if key ~= "x" then return end\n'
        '  local on = self.values.x > 0\n'
        '  local active_col = Color(0.20, 0.80, 0.60)\n'
        '  local grey_col   = Color(0.25, 0.35, 0.30)\n'
        '  for _, n in ipairs({"blower_low", "breathing_rate"}) do\n'
        '    local c = root:findByName(n, true)\n'
        '    if c then\n'
        '      c.color       = on and active_col or grey_col\n'
        '      c.interactive = on\n'
        '    end\n'
        '  end\n'
        'end'
    )
    BREATHE_Y = BL_Y0 + 24
    button(cv, 'breathe', R_X, BREATHE_Y, R_W, 42, CC_BREATHE,
           toggle=True, rgb=(0.20, 0.55, 0.40), script=breathe_script, osc=True)
    label(cv, 'lbl_breathe', R_X, BREATHE_Y + 42 + 2, R_W, 18,
          'BREATHE', size=12, align=2)

    # Three blower faders side-by-side
    BL_FADER_Y = BREATHE_Y + 42 + 22
    GREY = (0.25, 0.35, 0.30)

    fader(cv, 'blower_high', R_X,                       BL_FADER_Y,
          BL_FW, BL_FH, CC_BLOWER_HIGH, default=0.0, rgb=(0.20, 0.80, 0.60), osc=True)
    fader(cv, 'blower_low',  R_X + BL_FW + BL_GAP,     BL_FADER_Y,
          BL_FW, BL_FH, CC_BLOWER_LOW,  default=0.0, rgb=GREY, interactive=False, osc=True)
    fader(cv, 'breathing_rate', R_X + 2*(BL_FW+BL_GAP), BL_FADER_Y,
          BL_FW, BL_FH, CC_BREATHING_RATE, default=0.0, rgb=GREY, interactive=False, osc=True)

    LBL_Y = BL_FADER_Y + BL_FH + 4
    label(cv, 'lbl_bl_hi',   R_X,                       LBL_Y, BL_FW, 18,
          'BLOWER HIGH',    size=11, align=2)
    label(cv, 'lbl_bl_lo',   R_X + BL_FW + BL_GAP,     LBL_Y, BL_FW, 18,
          'BLOWER LOW',     size=11, align=2)
    label(cv, 'lbl_bl_rate', R_X + 2*(BL_FW+BL_GAP),   LBL_Y, BL_FW, 18,
          'BREATHING RATE', size=11, align=2)

    # ── air shutoff ───────────────────────────────────────────────────────────
    SO_LBL_Y  = LBL_Y + 18 + 14
    SO_FADER_Y = SO_LBL_Y + 20
    label(cv, 'lbl_shutoff', R_X, SO_LBL_Y, R_W, 20,
          'AIR SHUTOFF', size=13, align=2)
    fader(cv, 'shutoff', R_X, SO_FADER_Y, R_W, SO_H,
          CC_SHUTOFF, default=0.0, rgb=(0.70, 0.15, 0.70), osc=True)

    # ── heartbeat ─────────────────────────────────────────────────────────────
    HB_HDR_Y  = SO_FADER_Y + SO_H + 18
    HB_FADER_Y = HB_HDR_Y + 24
    label(cv, 'hdr_heart', R_X, HB_HDR_Y, R_W, 20,
          'HEARTBEAT', size=13, align=1)
    fader(cv, 'hb_speed',  R_X,              HB_FADER_Y, HB_FW, HB_FH,
          CC_HB_SPEED,  default=0.0, rgb=(0.90, 0.22, 0.30), osc=True)
    fader(cv, 'hb_bright', R_X + HB_FW + 20, HB_FADER_Y, HB_FW, HB_FH,
          CC_HB_BRIGHT, default=0.0, rgb=(0.90, 0.45, 0.15), osc=True)
    HB_LBL_Y = HB_FADER_Y + HB_FH + 4
    label(cv, 'lbl_hb_spd', R_X,              HB_LBL_Y, HB_FW, 18,
          'HEARTBEAT',   size=12, align=2)
    label(cv, 'lbl_hb_bri', R_X + HB_FW + 20, HB_LBL_Y, HB_FW, 18,
          'HEART BRIGHT', size=12, align=2)

    # ── local capture / loop ──────────────────────────────────────────────────
    # CAPTURE sends CC39 (= RECORD) — blob_monitor.py handles recording.
    # LOOP sends CC43 — blob_monitor.py plays back in loop mode.
    LCL_HDR_Y = HB_LBL_Y + 22
    LCL_BTN_Y = LCL_HDR_Y + 24
    LCL_BTN_W = (R_W - 8) // 2
    LCL_BTN_H = 65
    label(cv, 'hdr_local', R_X, LCL_HDR_Y, R_W, 20,
          'LOCAL LOOP', size=13, align=1)
    button(cv, 'capture', R_X, LCL_BTN_Y, LCL_BTN_W, LCL_BTN_H,
           cc=CC_RECORD, toggle=True, rgb=(0.85, 0.45, 0.10), osc=True)
    button(cv, 'loop',    R_X + LCL_BTN_W + 8, LCL_BTN_Y, LCL_BTN_W, LCL_BTN_H,
           cc=CC_LOOP,   toggle=True, rgb=(0.10, 0.65, 0.70), osc=True)
    label(cv, 'lbl_capture', R_X, LCL_BTN_Y + LCL_BTN_H + 2, LCL_BTN_W, 18,
          'CAPTURE', size=12, align=2)
    label(cv, 'lbl_loop', R_X + LCL_BTN_W + 8, LCL_BTN_Y + LCL_BTN_H + 2, LCL_BTN_W, 18,
          'LOOP', size=12, align=2)

    # ── halt / retract ────────────────────────────────────────────────────────
    halt_script = (
        'function onValueChanged(key)\n'
        '  if key == "x" and self.values.x > 0 then\n'
        '    for i = 0, 8 do\n'
        '      local s = root:findByName("servo" .. i, true)\n'
        '      if s then s.values.x = 0.5 end\n'
        '    end\n'
        '  end\n'
        'end'
    )
    retract_script = (
        'function onValueChanged(key)\n'
        '  if key == "x" and self.values.x > 0 then\n'
        '    for i = 0, 8 do\n'
        '      local s = root:findByName("servo" .. i, true)\n'
        '      if s then s.values.x = 0 end\n'
        '    end\n'
        '  end\n'
        'end'
    )
    button(cv, 'halt',    SV_X0,       BTN_Y, 280, BTN_H, CC_HALT,
           rgb=(0.90, 0.10, 0.10), script=halt_script, osc=True)
    label(cv,  'lbl_halt', SV_X0, BTN_Y + BTN_H + 2, 280, BTN_LBL,
          'HALT ALL', size=12, align=2)

    button(cv, 'retract', SV_X0 + 310, BTN_Y, 280, BTN_H, CC_RETRACT,
           rgb=(0.90, 0.50, 0.10), script=retract_script, osc=True)
    label(cv,  'lbl_retract', SV_X0 + 310, BTN_Y + BTN_H + 2, 280, BTN_LBL,
          'RETRACT ALL', size=12, align=2)

    # ── record / play ─────────────────────────────────────────────────────────
    button(cv, 'record', SV_X0, REC_Y,  ABTW, REC_H,  CC_RECORD,
           toggle=True, rgb=(0.80, 0.10, 0.10), osc=True)
    label(cv,  'lbl_record', SV_X0, REC_Y + REC_H + 2, ABTW, BTN_LBL,
          'RECORD', size=12, align=2)
    text_input(cv, 'rec_filename',  TXT_X, REC_Y,  TXT_W, REC_H,
               '/blob/record/filename')

    button(cv, 'play', SV_X0, PLAY_Y, ABTW, PLAY_H, CC_PLAY,
           toggle=True, rgb=(0.10, 0.70, 0.20), osc=True)
    label(cv,  'lbl_play', SV_X0, PLAY_Y + PLAY_H + 2, ABTW, BTN_LBL,
          'PLAY', size=12, align=2)
    text_input(cv, 'play_filename', TXT_X, PLAY_Y, TXT_W, PLAY_H,
               '/blob/play/filename')

    return root


# ── compass layout ────────────────────────────────────────────────────────────

def build_compass_layout():
    """Compass rose layout optimised for iPad 6th gen portrait (768 × 1024 pts).
    Top 720 px: servo compass fills full width.
    Bottom 302 px: left col = action buttons; right col = env controls.
    """

    root = ET.Element('lexml', version='3')
    rn   = ET.SubElement(root, 'node', ID=uid(), type='GROUP')
    rp   = ET.SubElement(rn, 'properties')
    ET.SubElement(rn, 'values')
    ET.SubElement(rn, 'messages')
    cv   = ET.SubElement(rn, 'children')

    C_W, C_H = 768, 1024   # iPad 6th gen portrait logical resolution
    prop_s(rp, 'name', 'blob_compass')
    prop_frame(rp, 0, 0, C_W, C_H)
    prop_color(rp, 0.12, 0.12, 0.12)

    # ── compass section: fills top 720 px at full canvas width ────────────
    box(cv, 'servo_bg', 4, 4, 760, 716, rgb=(0.08, 0.08, 0.08))
    label(cv, 'title', 4, 6, 760, 20,
          'BLOB CONTROL — COMPASS', size=13, align=2, rgb=(0.40, 0.40, 0.40))
    conn_indicator(cv, 'pi_conn', C_W - 30, 4, 22, 22)
    label(cv, 'lbl_conn', C_W - 30, 28, 22, 10, 'PI', size=8, align=2)

    # ── compass servo placement ───────────────────────────────────────────────
    # Servo numbering (user 1-9):  1=NW  2=N   3=NE
    #                              4=W   5=Ctr  6=E
    #                              7=SW  8=S   9=SE
    # servo_bg: x=[4,764], y=[4,720] — centre (384, 362).
    # R=255, PAD=130: outer pad edges at CCX/CCY ± 320; labels add 66 px more.
    CCX  = 384          # centre of servo_bg (4 + 760//2)
    CCY  = 362          # centre of servo_bg (4 + 716//2)
    R    = 255          # radius to N/S/E/W positions
    R45  = int(R / math.sqrt(2))   # 180 px — diagonal positions
    PAD  = 130          # XY pad size (square)

    # (code_index, direction_label, centre_x, centre_y, invert_midi)
    # invert=True where the compass direction is at a low coordinate:
    #   N  → top  = y=0  (midi key 'y')
    #   W  → left = x=0  (midi key 'x')
    #   NW → (0,0) corner (midi key 'x')
    #   SW → (0,1) corner (midi key 'x')
    compass_items = [
        (0, 'NW',  CCX - R45, CCY - R45, False),
        (1, 'N',   CCX,       CCY - R,   True ),  # reversed
        (2, 'NE',  CCX + R45, CCY - R45, True ),
        (3, 'W',   CCX - R,   CCY,       False),  # reversed
        (4, 'CTR', CCX,       CCY,       True ),
        (5, 'E',   CCX + R,   CCY,       True ),  # reversed
        (6, 'SW',  CCX - R45, CCY + R45, False),  # reversed
        (7, 'S',   CCX,       CCY + R,   False),
        (8, 'SE',  CCX + R45, CCY + R45, True ),  # reversed
    ]

    for idx, direction, cx, cy, inv in compass_items:
        row, col = divmod(idx, 3)
        cc = SERVO_CCS[row][col]

        xy_compass(cv, f'servo{idx}', cx, cy, PAD, direction, cc, invert=inv, osc=True)
        if direction in ('N', 'S', 'CTR'):
            linear_mask(cv, f'servo{idx}', cx, cy, PAD, vertical=True)
        elif direction in ('E', 'W'):
            linear_mask(cv, f'servo{idx}', cx, cy, PAD, vertical=False)
        elif direction in ('NW', 'SE'):
            diagonal_mask(cv, f'servo{idx}', cx, cy, PAD, slash=False)
        else:  # NE, SW
            diagonal_mask(cv, f'servo{idx}', cx, cy, PAD, slash=True)

        # Label placed outward from compass centre
        if cx == CCX and cy == CCY:
            out_x, out_y = 0.0, 1.0          # centre: label below
        else:
            dx, dy = cx - CCX, cy - CCY
            dist = math.hypot(dx, dy)
            out_x, out_y = dx / dist, dy / dist

        lbl_r = PAD // 2 + 2
        lx = int(cx + out_x * lbl_r) - 30
        ly = int(cy + out_y * lbl_r) - 9
        label(cv, f'lbl_sv{idx}', lx, ly, 60, 18,
              f'{idx+1} {direction}', size=11, align=2)

    # ── controls strip (y=722 … 1024) ─────────────────────────────────────────
    # Left  (x=4..381):   HALT/RETRACT · HEARTBEAT · RECORD+filename
    # Right (x=391..764): BREATHE+SHUTOFF · BLOWER faders · PLAY+filename
    # Both columns share y0=726, y_rec=960, GAP=44 between sections.
    CTL_Y = 722
    box(cv, 'col_div', 385, CTL_Y, 2, C_H - CTL_Y, rgb=(0.22, 0.22, 0.22))

    LX   = 4
    LW   = 377
    BW   = (LW - 12) // 2   # 182 px
    BG   = 12
    BH1  = 74
    BH2  = 40
    LBLH = 12
    GAP  = 23
    RX   = 391
    RW   = C_W - RX - 4     # 373 px
    RW2  = (RW - 8) // 2    # 182 px  (BREATHE / SHUTOFF half-widths)
    FW3  = (RW - 12) // 3   # 120 px  (3 blower faders)
    HFW  = BW                # heartbeat fader width = 182 px
    HB_H = 74                # heartbeat fader height
    BL_H = 74                # blower fader height
    GREY = (0.25, 0.35, 0.30)

    # Both columns: top of content
    y0    = CTL_Y + 4        # 726
    # Both columns: RECORD / PLAY button top  (40 px btn + 2 + 13 lbl = 55 → ends 1015)
    y_rec = 960

    # ── scripts ───────────────────────────────────────────────────────────────
    halt_script = (
        'function onValueChanged(key)\n'
        '  if key == "x" and self.values.x > 0 then\n'
        '    local yaxis = {[1]=true,[4]=true,[7]=true}\n'
        '    for i = 0, 8 do\n'
        '      local s = root:findByName("servo" .. i, true)\n'
        '      if s then\n'
        '        s.values.x = 0.5\n'
        '        if yaxis[i] then s.values.y = 0.5 end\n'
        '      end\n'
        '    end\n'
        '  end\n'
        'end'
    )
    retract_script = (
        'function onValueChanged(key)\n'
        '  if key == "x" and self.values.x > 0 then\n'
        '    local rx = {[0]=0,[2]=1,[3]=0,[5]=1,[6]=0,[8]=1}\n'
        '    local ry = {[1]=1,[4]=1,[7]=0}\n'
        '    for i = 0, 8 do\n'
        '      local s = root:findByName("servo" .. i, true)\n'
        '      if s then\n'
        '        if rx[i] ~= nil then\n'
        '          s.values.x = rx[i]\n'
        '        else\n'
        '          s.values.x = 0.5\n'
        '          s.values.y = ry[i]\n'
        '        end\n'
        '      end\n'
        '    end\n'
        '  end\n'
        'end'
    )
    breathe_script = (
        'function onValueChanged(key)\n'
        '  if key ~= "x" then return end\n'
        '  local on = self.values.x > 0\n'
        '  local active_col = Color(0.20, 0.80, 0.60)\n'
        '  local grey_col   = Color(0.25, 0.35, 0.30)\n'
        '  for _, n in ipairs({"blower_low", "breathing_rate"}) do\n'
        '    local c = root:findByName(n, true)\n'
        '    if c then\n'
        '      c.color       = on and active_col or grey_col\n'
        '      c.interactive = on\n'
        '    end\n'
        '  end\n'
        'end'
    )

    # ── left column ───────────────────────────────────────────────────────────
    # Row 1: HALT ALL + RETRACT ALL
    button(cv, 'halt',    LX,       y0, BW, BH1, CC_HALT,
           rgb=(0.90, 0.10, 0.10), script=halt_script, osc=True)
    label(cv,  'lbl_halt', LX,      y0+BH1+2, BW, LBLH, 'HALT ALL', size=11, align=2)
    button(cv, 'retract', LX+BW+BG, y0, BW, BH1, CC_RETRACT,
           rgb=(0.90, 0.50, 0.10), script=retract_script, osc=True)
    label(cv,  'lbl_retract', LX+BW+BG, y0+BH1+2, BW, LBLH, 'RETRACT ALL', size=11, align=2)

    # Row 2: HEARTBEAT  (y0 + 50+13+44 = 835)
    rl2 = y0 + BH1 + LBLH + GAP
    label(cv, 'hdr_heart', LX, rl2, LW, 14, 'HEARTBEAT', size=11, align=1)
    fader(cv, 'hb_speed',  LX,        rl2+16, HFW, HB_H, CC_HB_SPEED,
          default=0.0, rgb=(0.90, 0.22, 0.30), osc=True)
    fader(cv, 'hb_bright', LX+HFW+BG, rl2+16, HFW, HB_H, CC_HB_BRIGHT,
          default=0.0, rgb=(0.90, 0.45, 0.15), osc=True)
    label(cv, 'lbl_hb_spd', LX,        rl2+16+HB_H+2, HFW, 12, 'HB SPEED',  size=10, align=2)
    label(cv, 'lbl_hb_bri', LX+HFW+BG, rl2+16+HB_H+2, HFW, 12, 'HB BRIGHT', size=10, align=2)

    # Row 3: RECORD + filename  (anchored at y_rec)
    RBW  = 76
    TXX_L = LX + RBW + 8
    TXW_L = LW - RBW - 8
    button(cv, 'record', LX, y_rec, RBW, BH2, CC_RECORD,
           toggle=True, rgb=(0.80, 0.10, 0.10), osc=True)
    label(cv,  'lbl_record', LX, y_rec+BH2+2, RBW, LBLH, 'RECORD', size=10, align=2)
    text_input(cv, 'rec_filename', TXX_L, y_rec, TXW_L, BH2, '/blob/record/filename')

    # ── right column ──────────────────────────────────────────────────────────
    # Row 1: BREATHE toggle + AIR SHUTOFF fader  (same line, half-width each)
    BRH = 74
    button(cv, 'breathe', RX,       y0, RW2, BRH, CC_BREATHE,
           toggle=True, rgb=(0.20, 0.55, 0.40), script=breathe_script, osc=True)
    label(cv, 'lbl_breathe', RX,    y0+BRH+2, RW2, 12, 'BREATHE',     size=10, align=2)
    fader(cv, 'shutoff', RX+RW2+8,  y0, RW2, BRH, CC_SHUTOFF,
          default=0.0, rgb=(0.70, 0.15, 0.70), osc=True)
    label(cv, 'lbl_shutoff', RX+RW2+8, y0+BRH+2, RW2, 12, 'AIR SHUTOFF', size=10, align=2)

    # Row 2: BLOWER header + 3 faders  (y0 + 30+12+44 = 812)
    rr2 = y0 + BRH + 12 + GAP
    label(cv, 'hdr_blower', RX, rr2, RW, 14, 'BLOWER', size=11, align=1)
    fader(cv, 'blower_high',    RX,            rr2+16, FW3, BL_H, CC_BLOWER_HIGH,
          default=0.0, rgb=(0.20, 0.80, 0.60), osc=True)
    fader(cv, 'blower_low',     RX+FW3+6,      rr2+16, FW3, BL_H, CC_BLOWER_LOW,
          default=0.0, rgb=GREY, interactive=False, osc=True)
    fader(cv, 'breathing_rate', RX+2*(FW3+6),  rr2+16, FW3, BL_H, CC_BREATHING_RATE,
          default=0.0, rgb=GREY, interactive=False, osc=True)
    label(cv, 'lbl_bl_hi',   RX,           rr2+16+BL_H+2, FW3, 12, 'BLOW HI', size=10, align=2)
    label(cv, 'lbl_bl_lo',   RX+FW3+6,     rr2+16+BL_H+2, FW3, 12, 'BLOW LO', size=10, align=2)
    label(cv, 'lbl_bl_rate', RX+2*(FW3+6), rr2+16+BL_H+2, FW3, 12, 'RATE',   size=10, align=2)

    # Row 3: PLAY + filename  (anchored at y_rec, same as RECORD)
    TXX_R = RX + RBW + 8
    TXW_R = RW - RBW - 8
    button(cv, 'play', RX, y_rec, RBW, BH2, CC_PLAY,
           toggle=True, rgb=(0.10, 0.70, 0.20), osc=True)
    label(cv,  'lbl_play', RX, y_rec+BH2+2, RBW, LBLH, 'PLAY', size=10, align=2)
    text_input(cv, 'play_filename', TXX_R, y_rec, TXW_R, BH2, '/blob/play/filename')

    return root


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    compass = '--compass' in sys.argv
    pos_args = [a for a in sys.argv[1:] if not a.startswith('--')]
    here = Path(__file__).resolve().parent.parent  # always blob/ regardless of cwd
    if compass:
        out   = pos_args[0] if pos_args else str(here / 'blob_surface_compass.tosc')
        root  = build_compass_layout()
    else:
        out   = pos_args[0] if pos_args else str(here / 'blob_surface.tosc')
        root  = build_layout()
    xml_bytes = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    with open(out, 'wb') as f:
        f.write(zlib.compress(xml_bytes))
    print(f'Wrote {out}')
    print()
    print(f'CC map (all MIDI ch {MIDI_CH + 1}):')
    for name, cc in [
        ('Servo 0-2',      '16-18'),
        ('Servo 3-5',      '20-22'),
        ('Servo 6-8',      '24-26'),
        ('Blower high',    CC_BLOWER_HIGH),
        ('Breathe',        f'{CC_BREATHE}  (toggle)'),
        ('Blower low',     CC_BLOWER_LOW),
        ('Breathing rate', CC_BREATHING_RATE),
        ('HB speed',       CC_HB_SPEED),
        ('HB bright',      CC_HB_BRIGHT),
        ('Shutoff',        CC_SHUTOFF),
        ('HALT',           f'{CC_HALT}  (momentary)'),
        ('RETRACT',        f'{CC_RETRACT}  (momentary)'),
        ('Record',         f'{CC_RECORD}  (toggle)'),
        ('Play',           f'{CC_PLAY}  (toggle)'),
    ]:
        print(f'  {name:16s}: CC {cc}')
    print()
    print('OSC:  /blob/record/filename  /blob/play/filename')


if __name__ == '__main__':
    main()

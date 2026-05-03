#include "MIDIUSB.h"

// ---------------------------------------------------------------------------
// MIDI Test Pattern for Feather M4
//
// Phase 1 (auto): Sweeps each knob (CC 0-8) from midpoint → 127 → 0 → midpoint,
//   then moves to the next knob. After all 9 knobs, stops and enters Phase 2.
//   For every knob CC sent, also sends the LED feedback that benmidi_v7 would
//   compute — so the Python router has real feedback traffic to route and echo.
//
// Phase 2 (listen): Receives any incoming CC messages (e.g. GarageBand playback)
//   and responds with LED feedback exactly as benmidi_v7 does. This lets you
//   verify the full playback → Feather → Python router → Twister LED chain.
//
// Serial output labels every message: [OUT KNOB], [OUT LED], [IN KNOB]
// ---------------------------------------------------------------------------

#define NUM_KNOBS    9
#define DEADBAND     4
#define MIDPOINT     64
#define STEP         4      // CC units per tick during sweep
#define TICK_MS      80     // ms between pattern steps

uint8_t knobMidpoint[NUM_KNOBS];
uint8_t knobValue[NUM_KNOBS];

// ---------- MIDI helpers ----------

void sendCC(uint8_t channel, uint8_t cc, uint8_t value) {
  midiEventPacket_t pkt = {0x0B, (uint8_t)(0xB0 | channel), cc, value};
  MidiUSB.sendMIDI(pkt);
  MidiUSB.flush();
}

uint8_t computeLed(uint8_t knobVal, uint8_t midpoint) {
  int16_t d = (int16_t)knobVal - midpoint;
  if (abs(d) <= DEADBAND) return 0;
  return (uint8_t)constrain(map(abs(d), 0, 63, 0, 127), 0, 127);
}

void emitLedFeedback(uint8_t cc, uint8_t knobIdx) {
  uint8_t led = computeLed(knobValue[knobIdx], knobMidpoint[knobIdx]);
  sendCC(0, cc, led);
  Serial.print("[OUT LED ] Ch1 CC");
  Serial.print(cc);
  Serial.print(" = ");
  Serial.println(led);
}

// ---------- Phase 1: auto sweep pattern ----------

uint8_t  patKnob  = 0;
int16_t  patVal   = MIDPOINT;   // int16_t so it can go negative without wrapping
int8_t   patDir   = 1;
bool     patDone  = false;
unsigned long patTick = 0;

void runPattern() {
  if (patDone) return;
  if (millis() - patTick < TICK_MS) return;
  patTick = millis();

  uint8_t sendVal = (uint8_t)constrain(patVal, 0, 127);
  knobValue[patKnob] = sendVal;

  // send knob movement
  sendCC(0, patKnob, sendVal);
  Serial.print("[OUT KNOB] Ch1 CC");
  Serial.print(patKnob);
  Serial.print(" = ");
  Serial.println(sendVal);

  // send matching LED feedback
  emitLedFeedback(patKnob, patKnob);

  // advance sweep
  patVal += patDir * STEP;

  if (patDir > 0 && patVal >= 127) {
    patVal = 127;
    patDir = -1;
  } else if (patDir < 0 && patVal <= 0) {
    patVal = 0;
    patDir = 1;
    // move to next knob, reset to midpoint
    patKnob++;
    patVal = MIDPOINT;
    if (patKnob >= NUM_KNOBS) {
      patDone = true;
      Serial.println();
      Serial.println("=== Pattern complete. Listening for GarageBand playback... ===");
      Serial.println();
    }
  }
}

// ---------- Phase 2: respond to incoming MIDI ----------

void processIncoming() {
  midiEventPacket_t rx = MidiUSB.read();
  if (rx.header == 0) return;

  // knob rotation on Ch1
  if (rx.byte1 == 0xB0) {
    uint8_t cc  = rx.byte2;
    uint8_t val = rx.byte3;
    if (cc < NUM_KNOBS) {
      knobValue[cc] = val;
      Serial.print("[IN  KNOB] Ch1 CC");
      Serial.print(cc);
      Serial.print(" = ");
      Serial.println(val);
      emitLedFeedback(cc, cc);
    }
  }
}

// ---------- setup / loop ----------

void setup() {
  Serial.begin(115200);

  for (uint8_t i = 0; i < NUM_KNOBS; i++) {
    knobMidpoint[i] = MIDPOINT;
    knobValue[i]    = MIDPOINT;
  }

  Serial.println();
  Serial.println("=== MIDI Test Pattern ===");
  Serial.println("Phase 1: sweeping knobs 0-8, sending LED feedback after each step");
  Serial.println("Phase 2: listening — responds to GarageBand playback with LED feedback");
  Serial.println();
}

void loop() {
  runPattern();
  processIncoming();
}

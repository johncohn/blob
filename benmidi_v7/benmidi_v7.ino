#include "MIDIUSB.h"
#include <Adafruit_NeoPixel.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// ---------- Config ----------
#define NEOPIXEL_PIN 8
#define NUM_PIXELS   1

#define PCA9685_ADDR 0x40    // change if you jumpered A0..A5
#define SERVO_FREQ   50      // 50 Hz for hobby servos
#define USMIN        2400    // min pulse (you're using inverted mapping)
#define USMAX        600     // max pulse

#define NUM_SERVOS   9       // Number of servos controlled
#define MASTER_BUTTON 31     // Master button (knob 16 = CC 31)
#define DEADBAND     4       // ±4 MIDI values around midpoint = ~1 light worth
#define DOUBLE_CLICK_MS 400  // Max time between clicks for double-click (increased for debounce)
#define RETRACT_TIME_MS 50000 // 50 seconds for full retraction

// ---------- Environment CCs (channel 1, forwarded by blob_monitor on the Pi) ----------
// Same numbers as the TouchOSC layout. These carry only the slider *settings*;
// the heartbeat and breathing waveforms are generated here, so recording/playback
// of the sliders on the Pi reproduces the effect.
#define CC_BLOWER_HIGH    32   // blower max speed (and constant speed when Breathe is off); 0 = blower off
#define CC_BREATHE        33   // toggle: >=64 = breathing cycle on
#define CC_HB_SPEED       34   // heartbeat rate
#define CC_HB_BRIGHT      35   // heartbeat brightness; 0 = dark
#define CC_SHUTOFF        38   // >=64 = air shutoff: blower stopped, vent solenoid open
#define CC_BLOWER_LOW     41   // blower min speed during inhale
#define CC_BREATHING_RATE 42   // breaths per minute

// ---------- Heartbeat LED pucks (Adafruit 5408 4W RGBW NeoPixel) ----------
// Chain: Feather → PUCK_REPEATERS dark pucks (one every ~4 ft, regenerate data) → PUCK_HEART lit pucks.
// Puck 0 is powered from the Feather side (level-shift trick); see README "Heartbeat lights" wiring.
#define PUCK_PIN          9    // D9 → 330Ω → DIN of puck 0
#define PUCK_REPEATERS    3    // <<< set to the real number of dark repeater pucks (incl. puck 0)
#define PUCK_HEART        8    // pulsing pucks at the end of the chain
#define PUCK_TYPE         (NEO_GRBW + NEO_KHZ800)  // if "red" shows as green, try NEO_RGBW
#define HB_BPM_MIN        30.0f   // HB SPEED slider at 0
#define HB_BPM_MAX        180.0f  // HB SPEED slider at 127
#define HB_LUB_AT         0.06f   // s into the beat: centre of first ("lub") pulse
#define HB_LUB_W          0.06f   // s: pulse half-width
#define HB_DUB_W          0.07f
#define HB_DUB_GAIN       0.6f    // second ("dub") pulse relative brightness
#define FRAME_MS          20      // LED/air update period (50 Hz)

// ---------- Breathing: blower PWM + vent solenoid ----------
// Blower: D5 → gate of low-side FET; FET drain pulled up to 12 V → blower control input.
// The FET inverts (pin HIGH → line 0 V); BLOWER_FET_INVERTS accounts for that.
// D5 = PA16 = TCC1 WO[0], so the PWM is generated in hardware and keeps running
// while NeoPixel.show() has interrupts disabled.
#define BLOWER_PIN        5
#define BLOWER_MODE_FREQ  1        // 1: speed = frequency (15 kHz slow … 32 kHz fast, 50% duty)
                                   // 0: speed = duty cycle at BLOWER_DUTY_FREQ
#define BLOWER_FREQ_MIN   15000.0f
#define BLOWER_FREQ_MAX   32000.0f
#define BLOWER_DUTY_FREQ  25000.0f
#define BLOWER_DUTY_MIN   0.10f    // duty mode only: line duty at slider 1
#define BLOWER_DUTY_MAX   1.00f    // duty mode only: line duty at slider 127
#define BLOWER_FET_INVERTS    1
#define BLOWER_STOP_LINE_HIGH 0    // blower line when stopped: 0 = held at 0 V, 1 = held at 12 V.
                                   // VERIFY on the bench which level actually stops this blower.
// Solenoid: D6 → gate of power FET (flyback diode across coil). HIGH = energised = vent open.
#define SOLENOID_PIN      6
#define BREATH_PERIOD_SLOW 12.0f   // s per breath at RATE slider 0  (5 breaths/min)
#define BREATH_PERIOD_FAST 3.0f    // s per breath at RATE slider 127 (20 breaths/min)
#define INHALE_FRACTION    0.45f   // share of each breath spent inhaling (blower on, vent closed)

// Twister is a 4x4 grid on bank 2 (CC 16-31). Servos occupy the top-left 3x3,
// so every 4th knob (rightmost column) and the entire bottom row are unmapped.
//
// Twister layout → servo index:
//   knob 1(CC16)→0  knob 2(CC17)→1  knob 3(CC18)→2  knob 4(CC19)→-
//   knob 5(CC20)→3  knob 6(CC21)→4  knob 7(CC22)→5  knob 8(CC23)→-
//   knob 9(CC24)→6  knob10(CC25)→7  knob11(CC26)→8  knob12(CC27)→-
//   knob13(CC28)→-  knob14(CC29)→-  knob15(CC30)→-  knob16(CC31)→master
const uint8_t CC_TO_SERVO[128] = {
  255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, //  0-15: unused
  0,   1,   2,   255,  // CC 16-19: row 1 (knobs 1-3 active, knob 4 skipped)
  3,   4,   5,   255,  // CC 20-23: row 2 (knobs 5-7 active, knob 8 skipped)
  6,   7,   8,   255,  // CC 24-27: row 3 (knobs 9-11 active, knob 12 skipped)
  255, 255, 255, 255,  // CC 28-31: row 4 (bottom row — CC 31 = master button)
  255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, // 32-47
  255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, // 48-63
  255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, // 64-79
  255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, // 80-95
  255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, // 96-111
  255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255  // 112-127
};

#define MASTER_BUTTON_CC 31  // Master button (knob 16 = CC 31 on Channel 2)

// PCA9685 channels skip every 4th (3,7,11 unused), mirroring the Twister layout.
// Servo index 0-8 → PCA9685 channel 0,1,2,4,5,6,8,9,10
const uint8_t SERVO_TO_CHANNEL[9] = {0, 1, 2, 4, 5, 6, 8, 9, 10};

// ---------- Globals ----------
Adafruit_NeoPixel pixels = Adafruit_NeoPixel(NUM_PIXELS, NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(PCA9685_ADDR);

uint32_t knobColors[16];

// Dynamic midpoint tracking for each servo
uint8_t servoMidpoint[NUM_SERVOS];
uint8_t currentKnobValue[NUM_SERVOS];
bool knobInitialized[NUM_SERVOS]; // Track if we've received initial knob position

// Button state tracking for click detection (now CC-based, up to 128 CCs)
unsigned long lastButtonPress[128];
bool waitingForDoubleClick[128];
uint8_t clickCount[128]; // Count clicks to better detect double-clicks

// Retraction state
bool isRetracting[NUM_SERVOS];
unsigned long retractionStartTime[NUM_SERVOS];

// Environment state (last CC values received; all start at 0 = off/dark)
Adafruit_NeoPixel pucks = Adafruit_NeoPixel(PUCK_REPEATERS + PUCK_HEART, PUCK_PIN, PUCK_TYPE);
uint8_t ccBlowerHigh = 0, ccBlowerLow = 0, ccBreathe = 0, ccRate = 0, ccShutoff = 0;
uint8_t ccHbSpeed = 0, ccHbBright = 0;
float breathPhase = 0.0f;   // 0..1 through the current breath (inhale first)
float beatTime    = 0.0f;   // seconds into the current heartbeat
unsigned long lastFrameUs = 0;

Tcc*     blowerTcc   = nullptr;
uint8_t  blowerCh    = 0;
uint32_t blowerPer   = 0;
uint32_t blowerCc    = 0;

// ---------- Helpers ----------
static inline void writeServoUS(uint8_t ch, uint16_t us) {
  // keep it sane while debugging
  us = constrain(us, 500, 2500);
  pwm.writeMicroseconds(ch, us);
}

// Calculate servo speed based on knob position relative to midpoint
int16_t calculateServoSpeed(uint8_t servoIdx, uint8_t knobValue) {
  int16_t midpoint = servoMidpoint[servoIdx];
  int16_t delta = knobValue - midpoint;

  // Apply deadband
  if (abs(delta) <= DEADBAND) {
    return 0; // Within deadband, stop servo
  }

  // Remove deadband offset from delta
  if (delta > 0) {
    delta -= DEADBAND;
  } else {
    delta += DEADBAND;
  }

  return delta;
}

// Convert speed delta to servo pulse
uint16_t speedToPulse(int16_t speed) {
  // Map from -63 to +63 range (127/2 - DEADBAND) to servo pulse range
  // 0 speed = 1500us (stopped)
  // Negative speed (counterclockwise from midpoint) = retract (lower pulse)
  // Positive speed (clockwise from midpoint) = extend (higher pulse)
  if (speed == 0) {
    return 1500; // Stopped
  }

  // REVERSED: Negate speed to fix direction
  // Counterclockwise (negative) → retract → lower pulse (toward USMAX=600)
  // Clockwise (positive) → extend → higher pulse (toward USMIN=2400)
  int16_t pulseRange = (USMIN - USMAX) / 2;
  int16_t pulse = 1500 + map(-speed, -(127/2 - DEADBAND), (127/2 - DEADBAND), -pulseRange, pulseRange);

  return constrain(pulse, USMAX, USMIN);
}

// Reset midpoint for a servo
void resetMidpoint(uint8_t servoIdx) {
  if (servoIdx >= NUM_SERVOS) return;

  servoMidpoint[servoIdx] = currentKnobValue[servoIdx];
  isRetracting[servoIdx] = false;

  // Stop servo
  writeServoUS(SERVO_TO_CHANNEL[servoIdx], 1500);
}

// Start retraction for a servo
void startRetraction(uint8_t servoIdx) {
  if (servoIdx >= NUM_SERVOS) return;

  isRetracting[servoIdx] = true;
  retractionStartTime[servoIdx] = millis();

  // Full speed retraction (counterclockwise = lower pulse)
  // USMAX = 600 (minimum pulse) = retract direction
  writeServoUS(SERVO_TO_CHANNEL[servoIdx], USMAX);
}

// Send MIDI CC back to Twister to control LED ring
void updateKnobLED(uint8_t cc, uint8_t servoIdx) {
  if (servoIdx >= NUM_SERVOS) return;

  // Calculate LED position based on deflection from midpoint
  int16_t deflection = currentKnobValue[servoIdx] - servoMidpoint[servoIdx];

  // Map deflection to LED value
  // At midpoint (deflection=0): LED should be off or minimal
  // The MIDI Fighter Twister uses CC values to control LED brightness/position
  // This may need adjustment based on your Twister's configuration
  uint8_t ledValue = map(abs(deflection), 0, 63, 0, 127);

  // Queue LED CC — caller is responsible for flushing
  midiEventPacket_t event = {0x0B, 0xB0, cc, ledValue};
  MidiUSB.sendMIDI(event);
}

// Map CC number to servo index using same mapping as CC
int8_t ccToServo(uint8_t cc) {
  if (cc >= 128) return -1;
  uint8_t servo = CC_TO_SERVO[cc];
  if (servo == 255) return -1;
  return servo;
}

// Handle button presses (CC messages on Channel 2, value 127 = pressed)
void processButtonPress(uint8_t cc) {
  unsigned long now = millis();
  bool isDoubleClick = false;

  // Check if this is a double-click
  if (waitingForDoubleClick[cc] && (now - lastButtonPress[cc]) < DOUBLE_CLICK_MS) {
    isDoubleClick = true;
    waitingForDoubleClick[cc] = false;
    clickCount[cc] = 0; // Reset count


  } else {
    // First click or too long since last click
    waitingForDoubleClick[cc] = true;
    lastButtonPress[cc] = now;
    clickCount[cc] = 1;
    return; // Wait to see if there's a second click
  }

  // Handle master button (CC 31 on Channel 2)
  if (cc == MASTER_BUTTON_CC) {
    for (uint8_t i = 0; i < NUM_SERVOS; i++) {
      startRetraction(i);
    }
    return;
  }

  // Handle individual servo buttons using mapping
  int8_t servoIdx = ccToServo(cc);
  if (servoIdx >= 0) {
    startRetraction(servoIdx);
  }
}

// Check for pending single-clicks that didn't become double-clicks
void checkPendingClicks() {
  unsigned long now = millis();

  for (uint8_t i = 0; i < 128; i++) {
    if (waitingForDoubleClick[i] && clickCount[i] > 0 && (now - lastButtonPress[i]) >= DOUBLE_CLICK_MS) {
      waitingForDoubleClick[i] = false;
      clickCount[i] = 0;

      // Process as single-click
      if (i == MASTER_BUTTON_CC) {
        for (uint8_t j = 0; j < NUM_SERVOS; j++) {
          resetMidpoint(j);
        }
      } else {
        // Use mapping to find servo
        int8_t servoIdx = ccToServo(i);
        if (servoIdx >= 0) {
          resetMidpoint(servoIdx);
        }
      }
    }
  }
}

// ---------- Blower PWM (hardware TCC) ----------
void blowerInit() {
  const PinDescription &pd = g_APinDescription[BLOWER_PIN];
  analogWrite(BLOWER_PIN, 128);   // let the core mux the pin and clock its TCC (GCLK0 = F_CPU)
  blowerTcc = (Tcc*) GetTC(pd.ulPWMChannel);
  blowerCh  = GetTCChannelNumber(pd.ulPWMChannel);

  blowerTcc->CTRLA.bit.ENABLE = 0;
  while (blowerTcc->SYNCBUSY.bit.ENABLE);
  blowerTcc->CTRLA.reg = TCC_CTRLA_PRESCALER_DIV1 | TCC_CTRLA_PRESCSYNC_GCLK;
  blowerTcc->WAVE.reg  = TCC_WAVE_WAVEGEN_NPWM;
  while (blowerTcc->SYNCBUSY.bit.WAVE);
  blowerPer = (uint32_t)(F_CPU / BLOWER_FREQ_MIN) - 1;
  blowerTcc->PER.reg = blowerPer;
  while (blowerTcc->SYNCBUSY.bit.PER);
  blowerCc = 0;
  blowerTcc->CC[blowerCh].reg = 0;
  while (blowerTcc->SYNCBUSY.reg & TCC_SYNCBUSY_CC_Msk);
  blowerTcc->CTRLA.bit.ENABLE = 1;
  while (blowerTcc->SYNCBUSY.bit.ENABLE);
}

// speed < 0 = stop (constant level); otherwise 0..1
void blowerApply(float speed) {
  uint32_t per = blowerPer, cc;
  if (speed < 0.0f) {
    bool pinHigh = BLOWER_FET_INVERTS ? !BLOWER_STOP_LINE_HIGH : BLOWER_STOP_LINE_HIGH;
    cc = pinHigh ? per + 1 : 0;           // CC > PER → output never clears → constant HIGH
  } else {
    speed = constrain(speed, 0.0f, 1.0f);
#if BLOWER_MODE_FREQ
    float f = BLOWER_FREQ_MIN + speed * (BLOWER_FREQ_MAX - BLOWER_FREQ_MIN);
    per = (uint32_t)(F_CPU / f) - 1;
    cc  = (per + 1) / 2;                  // 50% duty — unaffected by FET inversion
#else
    per = (uint32_t)(F_CPU / BLOWER_DUTY_FREQ) - 1;
    float lineDuty = BLOWER_DUTY_MIN + speed * (BLOWER_DUTY_MAX - BLOWER_DUTY_MIN);
    float pinDuty  = BLOWER_FET_INVERTS ? 1.0f - lineDuty : lineDuty;
    cc = (uint32_t)(pinDuty * (per + 1));
#endif
  }
  if (per == blowerPer && cc == blowerCc) return;
  // Buffered registers: new period/duty take effect at the next cycle boundary (no glitches)
  blowerTcc->PERBUF.reg           = per;
  blowerTcc->CCBUF[blowerCh].reg  = cc;
  blowerPer = per;
  blowerCc  = cc;
}

// ---------- Breathing state machine ----------
void updateAir(float dt) {
  bool  ventOpen = false;
  float speed    = -1.0f;                 // stopped

  if (ccShutoff >= 64) {
    ventOpen = true;                      // AIR SHUTOFF: stop blower, let the air out
  } else if (ccBlowerHigh <= 1) {
    // BLOW HI at zero = blower off, vent closed
  } else if (ccBreathe < 64) {
    speed = ccBlowerHigh / 127.0f;        // Breathe off: steady blower at BLOW HI
  } else {
    float period = BREATH_PERIOD_SLOW + (BREATH_PERIOD_FAST - BREATH_PERIOD_SLOW) * (ccRate / 127.0f);
    breathPhase += dt / period;
    breathPhase -= floorf(breathPhase);
    if (breathPhase < INHALE_FRACTION) {  // inhale: vent closed, blower swells LOW → HIGH → LOW
      float p  = breathPhase / INHALE_FRACTION;
      float lo = ccBlowerLow / 127.0f, hi = ccBlowerHigh / 127.0f;
      speed = lo + (hi - lo) * sinf(PI * p);
    } else {                              // exhale: blower stopped, vent open
      ventOpen = true;
    }
  }
  digitalWrite(SOLENOID_PIN, ventOpen ? HIGH : LOW);
  blowerApply(speed);
}

// ---------- Heartbeat ----------
static inline float hbPulse(float t, float centre, float halfWidth) {
  float x = (t - centre) / halfWidth;
  return expf(-x * x);
}

void updateHeart(float dt) {
  float bpm    = HB_BPM_MIN + (HB_BPM_MAX - HB_BPM_MIN) * (ccHbSpeed / 127.0f);
  float period = 60.0f / bpm;
  beatTime += dt;
  beatTime = fmodf(beatTime, period);
  // Pulse widths are in seconds (not fractions of the beat) so fast rates stay visible
  float dubAt = HB_LUB_AT + min(0.30f, 0.40f * period);
  float env   = max(hbPulse(beatTime, HB_LUB_AT, HB_LUB_W),
                    HB_DUB_GAIN * hbPulse(beatTime, dubAt, HB_DUB_W));
  uint8_t red = Adafruit_NeoPixel::gamma8((uint8_t)(env * ccHbBright * 2.0f));

  for (uint16_t i = 0; i < PUCK_REPEATERS; i++) pucks.setPixelColor(i, 0);   // repeaters stay dark
  for (uint16_t i = 0; i < PUCK_HEART; i++)
    pucks.setPixelColor(PUCK_REPEATERS + i, pucks.Color(red, 0, 0, 0));
  pucks.show();
}

// Returns true if the CC was an environment control
bool processEnvCC(uint8_t control, uint8_t value) {
  switch (control) {
    case CC_BLOWER_HIGH:    ccBlowerHigh = value; return true;
    case CC_BLOWER_LOW:     ccBlowerLow  = value; return true;
    case CC_BREATHING_RATE: ccRate       = value; return true;
    case CC_SHUTOFF:        ccShutoff    = value; return true;
    case CC_HB_SPEED:       ccHbSpeed    = value; return true;
    case CC_HB_BRIGHT:      ccHbBright   = value; return true;
    case CC_BREATHE:
      if (value >= 64 && ccBreathe < 64) breathPhase = 0.0f;   // each Breathe-on starts with an inhale
      ccBreathe = value;
      return true;
  }
  return false;
}

void processInput(uint8_t control, uint8_t midiValue) {
  if (control >= 128) return;
  uint8_t servoIdx = CC_TO_SERVO[control];
  if (servoIdx == 255 || servoIdx >= NUM_SERVOS) return;

  // Store current knob value
  currentKnobValue[servoIdx] = midiValue;

  // Mark servo as active on first message (midpoint stays at 64 from setup)
  if (!knobInitialized[servoIdx]) {
    knobInitialized[servoIdx] = true;
  }

  // If retracting, cancel retraction and set new midpoint
  if (isRetracting[servoIdx]) {
    resetMidpoint(servoIdx);
    updateKnobLED(control, servoIdx);
    return;
  }

  // Calculate speed based on position relative to midpoint
  int16_t speed = calculateServoSpeed(servoIdx, midiValue);
  uint16_t pulse = speedToPulse(speed);
  writeServoUS(SERVO_TO_CHANNEL[servoIdx], pulse);

  // Update LED feedback to show deflection from midpoint
  updateKnobLED(control, servoIdx);

  // NeoPixel feedback - simple brightness like v5 for debugging
  uint32_t color = knobColors[servoIdx];
  uint8_t brightness = midiValue * 2;
  if (brightness > 255) brightness = 255;
  pixels.setBrightness(brightness);
  pixels.setPixelColor(0, color);
  pixels.show();

  // debug
}

void setup() {
  // Air outputs first, so the vent stays closed and the blower stopped from power-up
  pinMode(SOLENOID_PIN, OUTPUT);
  digitalWrite(SOLENOID_PIN, LOW);
  blowerInit();
  blowerApply(-1.0f);

  // Heartbeat pucks: brief dim-red self-test on the heart string, then dark
  pucks.begin();
  pucks.clear();
  for (uint16_t i = 0; i < PUCK_HEART; i++)
    pucks.setPixelColor(PUCK_REPEATERS + i, pucks.Color(40, 0, 0, 0));
  pucks.show();
  delay(400);
  pucks.clear();
  pucks.show();

  // The Feather M4 CAN's onboard NeoPixel has a separate power-enable pin
  pinMode(PIN_NEOPIXEL_POWER, OUTPUT);
  digitalWrite(PIN_NEOPIXEL_POWER, HIGH);

  Wire.begin();

  // ---------- PCA9685 ----------
  pwm.begin();
  pwm.setOscillatorFrequency(27000000); // Adafruit board nominal
  pwm.setPWMFreq(SERVO_FREQ);
  delay(10);

  // ---------- NeoPixel ----------
  pixels.begin();
  pixels.clear();
  pixels.setBrightness(20);
  pixels.show();

  // colors per channel
  knobColors[0]  = pixels.Color(255, 0, 0);      // 0: Red
  knobColors[1]  = pixels.Color(0, 255, 0);      // 1: Green
  knobColors[2]  = pixels.Color(0, 0, 255);      // 2: Blue
  knobColors[3]  = pixels.Color(255, 255, 0);    // 3: Yellow
  knobColors[4]  = pixels.Color(255, 0, 255);    // 4: Magenta
  knobColors[5]  = pixels.Color(0, 255, 255);    // 5: Cyan
  knobColors[6]  = pixels.Color(255, 128, 0);    // 6: Orange
  knobColors[7]  = pixels.Color(128, 0, 255);    // 7: Purple
  knobColors[8]  = pixels.Color(255, 255, 255);  // 8: White
  knobColors[9]  = pixels.Color(128, 128, 128);  // 9: Gray
  knobColors[10] = pixels.Color(128, 64, 0);     // 10: Brown
  knobColors[11] = pixels.Color(0, 128, 64);     // 11: Teal
  knobColors[12] = pixels.Color(0, 64, 128);     // 12: Deep Blue
  knobColors[13] = pixels.Color(64, 0, 128);     // 13: Dark Purple
  knobColors[14] = pixels.Color(128, 0, 64);     // 14: Maroon-ish
  knobColors[15] = pixels.Color(0, 128, 255);    // 15: Sky Blue

  // Initialize servo control variables
  for (uint8_t i = 0; i < NUM_SERVOS; i++) {
    servoMidpoint[i] = 64;            // MIDI center — CW from here = extend, CCW = retract
    currentKnobValue[i] = 64;
    knobInitialized[i] = false;
    isRetracting[i] = false;
    retractionStartTime[i] = 0;
    writeServoUS(SERVO_TO_CHANNEL[i], 1500);  // Stop all servos at startup
  }

  // Initialize button state
  for (uint8_t i = 0; i < 128; i++) {
    lastButtonPress[i] = 0;
    waitingForDoubleClick[i] = false;
    clickCount[i] = 0;
  }

}

void loop() {
  // MIDI over USB (MIDIUSB)
  // Drain every queued packet so a burst (e.g. playback) never lags behind
  midiEventPacket_t rx;
  while ((rx = MidiUSB.read()).header != 0) {
    // Control Change on Channel 1 (0xB0) - servos + environment controls
    if (rx.byte1 == 0xB0) {
      uint8_t control   = rx.byte2;
      uint8_t midiValue = rx.byte3;
      if (!processEnvCC(control, midiValue)) {
        processInput(control, midiValue);
      }
    }
    // Control Change on Channel 2 (0xB1) - button press
    else if (rx.byte1 == 0xB1) {
      uint8_t control = rx.byte2;
      uint8_t value = rx.byte3;
      // Only process on button press (value 127), ignore release (value 0)
      if (value == 127) {
        processButtonPress(control);
      }
    }
  }

  // Check for pending single-clicks
  checkPendingClicks();

  // Monitor retraction timers
  unsigned long now = millis();
  for (uint8_t i = 0; i < NUM_SERVOS; i++) {
    if (isRetracting[i]) {
      if ((now - retractionStartTime[i]) >= RETRACT_TIME_MS) {
        resetMidpoint(i);
      }
    }
  }

  // Heartbeat + breathing at a fixed frame rate
  unsigned long nowUs = micros();
  if (nowUs - lastFrameUs >= FRAME_MS * 1000UL) {
    float dt = (lastFrameUs == 0) ? 0.0f : (nowUs - lastFrameUs) / 1e6f;
    lastFrameUs = nowUs;
    updateAir(dt);
    updateHeart(dt);
  }

  MidiUSB.flush();  // send all queued LED feedback in one shot
  delay(1);
}
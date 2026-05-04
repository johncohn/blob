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
  midiEventPacket_t rx = MidiUSB.read();
  if (rx.header != 0) {
    // Control Change on Channel 1 (0xB0) - knob rotation
    if (rx.byte1 == 0xB0) {
      uint8_t control   = rx.byte2;
      uint8_t midiValue = rx.byte3;
      processInput(control, midiValue);
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

  MidiUSB.flush();  // send all queued LED feedback in one shot
  delay(1);
}
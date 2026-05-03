# MIDI Fighter Twister Servo Controller

Arduino-based project for controlling 9 linear servo actuators using a MIDI Fighter Twister controller with dynamic midpoint management and intelligent button controls.

## Hardware

- **Controller:** MIDI Fighter Twister by DJ TechTools (16 addressable RGB encoder knobs)
- **Servos:** 9 linear servo actuators
- **Driver:** PCA9685 16-channel PWM servo driver
- **Microcontroller:** Arduino with USB MIDI support
- **Feedback:** NeoPixel LED strip (1 pixel)

## Features

### Dynamic Midpoint Control

Each of the 9 servo-controlling knobs maintains its own dynamic midpoint position:
- Initial midpoint: MIDI value 64 (center)
- Turning knob left of midpoint → servo moves one direction
- Turning knob right of midpoint → servo moves opposite direction
- Speed proportional to distance from midpoint

### Button Controls

#### Individual Knob Buttons (Knobs 0-8)

**Single-Click:**
- Resets that servo's midpoint to current knob position
- Stops the servo immediately
- LED updates to show current position as new center

**Double-Click:**
- Initiates full-speed retraction (counterclockwise direction)
- Runs for 50 seconds
- Automatically resets midpoint when retraction completes
- **Cancellation:** Moving the knob during retraction cancels it and sets new midpoint to current position

#### Master Button (Knob 15 - Lower Right)

**Single-Click:**
- Resets midpoints for all 9 servos simultaneously
- Stops all servos

**Double-Click:**
- Retracts all 9 servos at full speed simultaneously
- Each servo runs for 50 seconds
- Moving any individual knob cancels that servo's retraction only

### Deadband Feature

Prevents servo creep when knob is at or near midpoint:
- ±4 MIDI values (~1 LED indicator worth) around midpoint = zero speed
- Servo only moves when knob is >4 values away from midpoint
- Eliminates the issue where servos continue to creep despite knob appearing centered

### Visual Feedback

**NeoPixel LED:**
- Color changes based on which knob is being adjusted (9 distinct colors)
- Brightness indicates distance from midpoint:
  - Dim: At or near midpoint (stopped)
  - Bright: Far from midpoint (moving fast)

## Configuration

Key constants in `benmidi_v6.ino`:

```cpp
#define NUM_SERVOS      9       // Number of servos controlled
#define MASTER_BUTTON   15      // Lower right button (knob 15)
#define DEADBAND        4       // ±4 MIDI values around midpoint = stopped
#define DOUBLE_CLICK_MS 300     // Max time between clicks for double-click (ms)
#define RETRACT_TIME_MS 50000   // Full retraction duration (50 seconds)
```

### Servo Calibration

```cpp
#define SERVO_FREQ   50      // 50 Hz for hobby servos
#define USMIN        2400    // Min pulse width (microseconds)
#define USMAX        600     // Max pulse width (microseconds)
```

**Note:** The pulse values are inverted for this particular servo setup.

## MIDI Mapping

- **Knob Rotation:** MIDI CC messages 0-8 control servos 0-8
- **Button Press:** MIDI Note On messages 0-8 for servo buttons, Note 15 for master button
- **MIDI Channel:** Typically channel 1 (adjust in MIDI Fighter Twister configuration)

## Installation

1. Install required Arduino libraries:
   - MIDIUSB
   - Adafruit_NeoPixel
   - Wire (built-in)
   - Adafruit_PWMServoDriver

2. Connect hardware:
   - PCA9685 to Arduino via I2C (default address 0x40)
   - NeoPixel to pin 8
   - MIDI Fighter Twister via USB

3. Upload `benmidi_v6.ino` to Arduino

4. Configure MIDI Fighter Twister to send:
   - CC messages on knob rotation
   - Note On messages on button press

## Usage

### Basic Operation

1. Turn any knob (0-8) to control the corresponding servo
2. Servo speed/direction is relative to that knob's current midpoint
3. LED brightness shows how far from midpoint you are

### Resetting Position

**Single Servo:**
- Single-click the knob to set current position as new midpoint

**All Servos:**
- Single-click knob 15 (lower right) to reset all midpoints

### Retracting Servos

**Single Servo:**
- Double-click the knob to retract at full speed for 50 seconds

**All Servos:**
- Double-click knob 15 (lower right) to retract all servos

### Canceling Retraction

- Simply turn the knob during retraction
- Servo stops and current position becomes new midpoint

## Troubleshooting

**Servos creep when knob appears centered:**
- This is now fixed with the deadband feature
- Adjust `DEADBAND` value if needed (currently ±4 MIDI values)

**Double-clicks not registering:**
- Increase `DOUBLE_CLICK_MS` value for more time between clicks

**Retraction too short/long:**
- Adjust `RETRACT_TIME_MS` to match your servo travel time

**Servo moves wrong direction:**
- Swap `USMIN` and `USMAX` values
- Or reverse the polarity in `startRetraction()` function

## Serial Debugging

Connect via Serial Monitor (115200 baud) to see:
- MIDI CC values and servo responses
- Button clicks (single/double)
- Midpoint resets
- Retraction start/stop/cancel events

**Manual Testing:**
Enter `control,value` in Serial Monitor (e.g., `0,100`) to manually control servos.

## Technical Details

**Servo Control:**
- Uses microsecond pulse width (600-2400µs range)
- 1500µs = stopped
- PCA9685 provides 16 independent PWM channels at 50Hz

**Click Detection:**
- Waits 300ms after first press to distinguish single vs double-click
- State machine tracks pending clicks for all 16 buttons

**Retraction Monitoring:**
- Non-blocking timer checks elapsed time each loop iteration
- Immediately cancels on knob movement detection

## License

MIT License - Feel free to modify and use for your projects.

## Author

Created for controlling linear servo actuators in interactive installations and performances.

#pragma once
#include "Arduino.h"
extern int g_servoUs[16];
struct Adafruit_PWMServoDriver{Adafruit_PWMServoDriver(int){} void begin(){} void setOscillatorFrequency(long){} void setPWMFreq(int){} void writeMicroseconds(int ch,int us){g_servoUs[ch]=us;}};

#pragma once
#include "Arduino.h"
#define NEO_GRB 1
#define NEO_GRBW 2
#define NEO_KHZ800 0
struct Adafruit_NeoPixel{
  std::vector<uint32_t> px; int shows=0;
  Adafruit_NeoPixel(int n,int,int){px.assign(n,0);}
  void begin(){} void clear(){std::fill(px.begin(),px.end(),0);} void setBrightness(int){} void show(){shows++;}
  void setPixelColor(int i,uint32_t c){px[i]=c;}
  static uint32_t Color(uint8_t r,uint8_t g,uint8_t b){return (r<<16)|(g<<8)|b;}
  static uint32_t Color(uint8_t r,uint8_t g,uint8_t b,uint8_t w){return ((uint32_t)w<<24)|(r<<16)|(g<<8)|b;}
  static uint8_t gamma8(uint8_t x){return (uint8_t)(std::pow(x/255.0,2.6)*255+0.5);}
};

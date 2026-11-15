#pragma once
#include <cstdint>
#include <cmath>
#include <algorithm>
#include <deque>
#include <vector>
#define F_CPU 120000000UL
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define PI 3.14159265358979f
#define PIN_NEOPIXEL_POWER 7
using std::min; using std::max;
template<class T,class L,class H> T constrain(T x,L l,H h){return x<l?l:(x>h?h:x);}
inline long map(long x,long a,long b,long c,long d){return (x-a)*(d-c)/(b-a)+c;}
extern unsigned long g_us;
inline unsigned long micros(){return g_us;}
inline unsigned long millis(){return g_us/1000;}
inline void delay(unsigned long ms){g_us+=ms*1000;}
extern int g_pin[64]; extern int g_analog[64];
inline void pinMode(int,int){}
inline void digitalWrite(int p,int v){g_pin[p]=v;}
inline void analogWrite(int p,int v){g_analog[p]=v;}
// ---- TCC mock ----
struct Reg{uint32_t reg=0;};
struct Tcc{
  struct{union{uint32_t reg; struct{uint32_t SWRST:1,ENABLE:1;} bit;};} CTRLA{};
  struct{union{uint32_t reg; struct{uint32_t SWRST:1,ENABLE:1,CTRLB:1,STATUS:1,COUNT:1,PATT:1,WAVE:1,PER:1;} bit;};} SYNCBUSY{};
  Reg WAVE, PER, PERBUF; Reg CC[6]; Reg CCBUF[6];
};
#define TCC_CTRLA_PRESCALER_DIV1 0
#define TCC_CTRLA_PRESCSYNC_GCLK 0
#define TCC_WAVE_WAVEGEN_NPWM 2
#define TCC_SYNCBUSY_CC_Msk 0
struct PinDescription{int ulPWMChannel;};
extern PinDescription g_APinDescription[64];
extern Tcc g_tcc1;
#define GetTC(x) (&g_tcc1)
#define GetTCChannelNumber(x) ((x)&0xff)

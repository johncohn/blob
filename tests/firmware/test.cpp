#include <cstdio>
#include "mock/Arduino.h"
unsigned long g_us=0; int g_pin[64]; int g_analog[64]; int g_servoUs[16];
PinDescription g_APinDescription[64]; Tcc g_tcc1;
#include "mock/MIDIUSB.h"
MidiUSB_ MidiUSB;
#include "../../benmidi_v7/benmidi_v7.ino"
int fails=0;
#define CHECK(c,...) do{ if(!(c)){fails++; printf("FAIL %s:%d ",__FILE__,__LINE__); printf(__VA_ARGS__); printf("\n");} }while(0)
bool blowerStopped(){ return blowerCc==0 || blowerCc>blowerPer; }
double blowerFreq(){ return (double)F_CPU/(blowerPer+1); }
uint8_t heartRed(){ return (pucks.px[PUCK_REPEATERS]>>16)&0xff; }
void run(double secs, void(*f)()=nullptr){ unsigned long end=g_us+(unsigned long)(secs*1e6); while(g_us<end){ loop(); if(f) f(); } }
// invariants checked every loop
bool everBlowWhileVent=false; double fmin_=1e9,fmax_=0;
void inv(){ if(g_pin[SOLENOID_PIN] && !blowerStopped()) everBlowWhileVent=true;
  if(!blowerStopped()){ fmin_=std::min(fmin_,blowerFreq()); fmax_=std::max(fmax_,blowerFreq()); }
  for(int i=0;i<PUCK_REPEATERS;i++) if(pucks.px[i]) { everBlowWhileVent=everBlowWhileVent; printf("FAIL repeater lit\n"); fails++; } }
int main(){
  g_APinDescription[BLOWER_PIN].ulPWMChannel=(1<<8)|0;
  g_us=1000; setup();
  // power-up state
  CHECK(g_pin[SOLENOID_PIN]==LOW,"vent closed at boot");
  CHECK(blowerStopped(),"blower stopped at boot");
  CHECK(blowerPer==7999,"per=%u",blowerPer);
  CHECK(g_tcc1.CC[blowerCh].reg==0,"init cc");
  CHECK(pucks.px[PUCK_REPEATERS]==0,"pucks dark after self-test");
  run(1.0,inv); CHECK(heartRed()==0 && blowerStopped(),"idle stays off");

  // steady blower, breathe off
  cc(CC_BLOWER_HIGH,127); run(0.1,inv);
  CHECK(!blowerStopped() && fabs(blowerFreq()-32000)<20,"steady max f=%.0f",blowerFreq());
  CHECK(blowerCc==(blowerPer+1)/2,"50%% duty");
  CHECK(g_pin[SOLENOID_PIN]==LOW,"vent closed when steady");
  cc(CC_BLOWER_HIGH,1); run(0.1,inv); CHECK(blowerStopped(),"BLOW HI<=1 stops");

  // breathing: hi=127 lo=0 rate=127 (3 s period, inhale 1.35 s)
  cc(CC_BLOWER_HIGH,127); cc(CC_BLOWER_LOW,0); cc(CC_BREATHING_RATE,127); cc(CC_BREATHE,127);
  int transitions=0, last=-1; double openTime=0, t0=g_us/1e6;
  fmin_=1e9; fmax_=0;
  run(9.0,[](){ inv(); });
  // count vent transitions by sampling
  g_us+=0; 
  { int prev=g_pin[SOLENOID_PIN]; unsigned long s=g_us; int opens=0; double open=0; 
    while(g_us<s+9000000){ loop(); inv(); int v=g_pin[SOLENOID_PIN]; if(v&&!prev) opens++; if(v) open+=0.001; prev=v; }
    CHECK(opens==3,"3 breaths in 9 s, got %d",opens);
    CHECK(fabs(open/9.0-0.55)<0.03,"exhale share %.3f",open/9.0); }
  CHECK(!everBlowWhileVent,"blower never runs while vent open");
  CHECK(fmin_<15500 && fmax_>31500,"inhale sweeps %.0f..%.0f",fmin_,fmax_);
  // rate change mid-breath keeps phase continuous
  float ph=breathPhase; cc(CC_BREATHING_RATE,0); run(0.021,inv); CHECK(std::min(fabs(breathPhase-ph),1-fabs(breathPhase-ph))<0.02,"phase jump %f->%f",ph,breathPhase);
  // shutoff overrides
  cc(CC_SHUTOFF,127); run(0.05,inv); CHECK(blowerStopped() && g_pin[SOLENOID_PIN]==HIGH,"shutoff vents");
  cc(CC_SHUTOFF,0); cc(CC_BREATHE,0); run(0.05,inv); CHECK(!blowerStopped() && g_pin[SOLENOID_PIN]==LOW,"back to steady");
  // breathe re-enable restarts on inhale
  cc(CC_BREATHE,127); run(0.05,inv); CHECK(g_pin[SOLENOID_PIN]==LOW && !blowerStopped(),"starts with inhale");
  CHECK(!everBlowWhileVent,"invariant");

  // heartbeat: 30 BPM, full brightness → 2 s beat, two pulses
  cc(CC_HB_SPEED,0); cc(CC_HB_BRIGHT,127); run(0.05,inv);
  beatTime=0; std::vector<int> r; for(int i=0;i<2000;i++){ loop(); if(i%20==19) r.push_back(heartRed()); }
  int peaks=0, mx=0; for(size_t i=1;i+1<r.size();i++){ if(r[i]>r[i-1]&&r[i]>=r[i+1]&&r[i]>20) peaks++; mx=std::max(mx,r[i]); }
  CHECK(peaks==2,"lub-dub peaks=%d",peaks); CHECK(mx>200,"peak bright %d",mx);
  CHECK(r[75]==0,"dark between beats (%d)",r[1500]);
  for(int i=0;i<PUCK_HEART;i++) CHECK(pucks.px[PUCK_REPEATERS+i]==pucks.px[PUCK_REPEATERS],"all heart pucks equal");
  // fast rate: 180 BPM still shows two distinct pulses per beat
  cc(CC_HB_SPEED,127); run(0.05,inv); beatTime=0; r.clear(); for(int i=0;i<333;i++){ loop(); if(i%20==19) r.push_back(heartRed()); }
  peaks=0; for(size_t i=1;i+1<r.size();i++) if(r[i]>r[i-1]&&r[i]>=r[i+1]&&r[i]>20) peaks++;
  CHECK(peaks==2,"180bpm peaks=%d",peaks);
  cc(CC_HB_BRIGHT,0); run(3,inv); CHECK(heartRed()==0,"bright 0 dark");

  // servo path untouched: CC16=127 drives servo 0, env CCs don't touch servos
  int before[16]; std::copy(g_servoUs,g_servoUs+16,before);
  cc(CC_HB_SPEED,64); cc(CC_BLOWER_LOW,64); run(0.01);
  CHECK(std::equal(before,before+16,g_servoUs),"env CCs don't move servos");
  cc(16,127); run(0.01); CHECK(g_servoUs[0]!=1500 && g_servoUs[0]!=before[0],"servo 0 moves (%d)",g_servoUs[0]);
  cc(16,64); run(0.01); CHECK(g_servoUs[0]==1500,"servo 0 stops");
  // burst: 200 queued CCs all processed in one loop
  for(int i=0;i<200;i++) cc(17,i%128); loop(); CHECK(MidiUSB.q.empty(),"burst drained");

  printf(fails? "%d FAILURES\n":"ALL FIRMWARE TESTS PASSED\n",fails); return fails!=0;
}

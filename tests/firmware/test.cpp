#include <cstdio>
#include "mock/Arduino.h"
unsigned long g_us=0; int g_pin[64]; int g_analog[64]; int g_servoUs[16];
PinDescription g_APinDescription[64]; Tcc g_tcc1;
#include "mock/MIDIUSB.h"
MidiUSB_ MidiUSB;
#include "../../benmidi_v7/benmidi_v7.ino"
int fails=0;
#define CHECK(c,...) do{ if(!(c)){fails++; printf("FAIL %s:%d ",__FILE__,__LINE__); printf(__VA_ARGS__); printf("\n");} }while(0)
// duty the blower sees on its control line (FET inverts the pin)
double lineDuty(){ double pin=std::min<double>(blowerCc,blowerPer+1)/(blowerPer+1); return BLOWER_FET_INVERTS? 1-pin : pin; }
bool blowerStopped(){ return lineDuty()<1e-6; }
double blowerFreq(){ return (double)F_CPU/(blowerPer+1); }
uint8_t heartRed(){ return (pucks.px[PUCK_REPEATERS]>>16)&0xff; }
void run(double secs, void(*f)()=nullptr){ unsigned long end=g_us+(unsigned long)(secs*1e6); while(g_us<end){ loop(); if(f) f(); } }
// invariants checked every loop
bool everBlowWhileVent=false; double fmin_=1e9,fmax_=0, dmin_=2,dmax_=-1;
unsigned long lastRunUs=0, lastVentUs=0; bool spinGuardBroken=false, leadGuardBroken=false;
void inv(){ if(g_pin[SOLENOID_PIN] && !blowerStopped()) everBlowWhileVent=true;
  if(!blowerStopped()){ if(g_us-lastVentUs < (unsigned long)(VENT_CLOSE_LEAD*1e6)-1000) leadGuardBroken=true; lastRunUs=g_us; }
  if(g_pin[SOLENOID_PIN]){ if(g_us-lastRunUs < (unsigned long)(SPINDOWN_WAIT*1e6)-1000) spinGuardBroken=true; lastVentUs=g_us; }
  if(!blowerStopped()){ fmin_=std::min(fmin_,blowerFreq()); fmax_=std::max(fmax_,blowerFreq()); dmin_=std::min(dmin_,lineDuty()); dmax_=std::max(dmax_,lineDuty()); }
  for(int i=0;i<PUCK_REPEATERS;i++) if(pucks.px[i]) { everBlowWhileVent=everBlowWhileVent; printf("FAIL repeater lit\n"); fails++; } }
int main(){
  g_APinDescription[BLOWER_PIN].ulPWMChannel=(1<<8)|0;
  g_us=1000; setup();
  // power-up state
  CHECK(g_pin[SOLENOID_PIN]==LOW,"vent closed at boot");
  CHECK(blowerStopped(),"blower stopped at boot");
  CHECK(blowerPer==4799,"per=%u (25 kHz)",blowerPer);
  CHECK(BLOWER_MODE_FREQ==0,"duty mode (fantest)");
  CHECK(pucks.px[PUCK_REPEATERS]==0,"pucks dark after self-test");
  run(1.0,inv); CHECK(heartRed()==0 && blowerStopped(),"idle stays off");

  // steady blower, breathe off
  cc(CC_BLOWER_HIGH,127); run(0.1,inv);
  CHECK(fabs(blowerFreq()-25000)<5,"fixed 25 kHz f=%.0f",blowerFreq());
  CHECK(lineDuty()>0.999,"slider 127 = 100%% line duty (%.3f)",lineDuty());
  CHECK(blowerCc==0,"inverted: pin held LOW at full speed");
  cc(CC_BLOWER_HIGH,38); run(0.1,inv); CHECK(fabs(lineDuty()-0.30)<0.01,"slider 38 ~30%% (%.3f)",lineDuty());
  CHECK(fabs(blowerCc/(double)(blowerPer+1)-0.70)<0.01,"pin duty = 100-speed");
  CHECK(g_pin[SOLENOID_PIN]==LOW,"vent closed when steady");
  cc(CC_BLOWER_HIGH,1); run(0.1,inv); CHECK(blowerStopped(),"BLOW HI<=1 stops");

  // breathing: hi=127 lo=0 rate=127 → 6 s period, blower on 3 s (0.4 ramp up, 2.2 hold, 0.4 ramp down)
  cc(CC_BLOWER_HIGH,127); cc(CC_BLOWER_LOW,0); cc(CC_BREATHING_RATE,127); cc(CC_BREATHE,127);
  fmin_=1e9; fmax_=0; dmin_=2; dmax_=-1;
  run(12.0,inv);
  { int prev=g_pin[SOLENOID_PIN]; unsigned long s=g_us; int opens=0; double open=0, full=0, on=0;
    unsigned long startUs=0; double rampUp=-1; bool wasOn=false;
    while(g_us<s+18000000){ loop(); inv(); int v=g_pin[SOLENOID_PIN];
      if(v&&!prev) opens++; if(v) open+=0.001; prev=v;
      bool isOn=!blowerStopped(); if(isOn){ on+=0.001; if(lineDuty()>0.99) full+=0.001; }
      if(isOn&&!wasOn) startUs=g_us; if(isOn&&lineDuty()>0.99&&rampUp<0&&startUs) rampUp=(g_us-startUs)/1e6; wasOn=isOn; }
    CHECK(opens==3,"3 breaths in 18 s at fast rate, got %d",opens);
    // vent open = 6 - 3 (blower) - 1.5 (spin-down) - 0.3 (close lead) = 1.2 s per breath
    CHECK(fabs(open/18.0-0.20)<0.02,"vent-open share %.3f",open/18.0);
    CHECK(rampUp>0 && rampUp<0.45,"ramp to full in %.2f s",rampUp);
    CHECK(full/on>0.70,"holds full power %.0f%% of on-time",100*full/on); }
  CHECK(!everBlowWhileVent,"blower never runs while vent open");
  CHECK(!spinGuardBroken,"vent opens only after the blower has been stopped SPINDOWN_WAIT");
  CHECK(!leadGuardBroken,"blower starts only after the vent has been shut VENT_CLOSE_LEAD");
  CHECK(dmin_<0.05 && dmax_>0.98,"inhale sweeps duty %.3f..%.3f",dmin_,dmax_);
  CHECK(fabs(fmin_-25000)<5 && fabs(fmax_-25000)<5,"carrier stays 25 kHz");
  // slowest rate: one 40 s breath
  cc(CC_BREATHING_RATE,0); cc(CC_BREATHE,0); run(0.05,inv); cc(CC_BREATHE,127);
  { int prev=g_pin[SOLENOID_PIN], opens=0; unsigned long s=g_us;
    while(g_us<s+80000000){ loop(); inv(); int v=g_pin[SOLENOID_PIN]; if(v&&!prev) opens++; prev=v; }
    CHECK(opens==2,"2 breaths in 80 s at slow rate, got %d",opens); }
  // mid rate is exponential: slider 64 ≈ 15.5 s
  CHECK(fabs(BREATH_PERIOD_SLOW*powf(BREATH_PERIOD_FAST/BREATH_PERIOD_SLOW,64/127.0f)-15.5)<0.5,"mid period");
  // rate change mid-breath keeps phase continuous
  cc(CC_BREATHING_RATE,127); run(1.0,inv);
  float ph=breathPhase; cc(CC_BREATHING_RATE,0); run(0.021,inv); CHECK(std::min(fabs(breathPhase-ph),1-fabs(breathPhase-ph))<0.02,"phase jump %f->%f",ph,breathPhase);
  // shutoff: blower stops at once, vent waits out the spin-down, then opens
  cc(CC_BREATHE,0); cc(CC_SHUTOFF,0); run(1.0,inv); CHECK(!blowerStopped(),"steady before shutoff");
  cc(CC_SHUTOFF,127); run(0.05,inv); CHECK(blowerStopped() && g_pin[SOLENOID_PIN]==LOW,"shutoff: blower stops, vent still shut");
  run(SPINDOWN_WAIT-0.2,inv); CHECK(g_pin[SOLENOID_PIN]==LOW,"vent waits for spin-down");
  run(0.3,inv); CHECK(g_pin[SOLENOID_PIN]==HIGH,"vent opens after spin-down");
  // shutoff off: vent shuts at once, blower waits VENT_CLOSE_LEAD
  cc(CC_SHUTOFF,0); run(0.05,inv); CHECK(g_pin[SOLENOID_PIN]==LOW && blowerStopped(),"vent shuts first");
  run(VENT_CLOSE_LEAD+0.05,inv); CHECK(!blowerStopped(),"then blower back to steady");
  // breathe re-enable restarts on inhale
  cc(CC_BREATHE,127); run(0.5,inv); CHECK(g_pin[SOLENOID_PIN]==LOW && !blowerStopped(),"starts with inhale");
  CHECK(!spinGuardBroken && !leadGuardBroken,"interlocks held throughout");
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

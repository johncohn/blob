#pragma once
#include "Arduino.h"
struct midiEventPacket_t{uint8_t header,byte1,byte2,byte3;};
struct MidiUSB_{std::deque<midiEventPacket_t> q; midiEventPacket_t read(){if(q.empty())return {0,0,0,0}; auto p=q.front(); q.pop_front(); return p;} void sendMIDI(midiEventPacket_t){} void flush(){}};
extern MidiUSB_ MidiUSB;
inline void cc(uint8_t c,uint8_t v){MidiUSB.q.push_back({0x0B,0xB0,c,v});}

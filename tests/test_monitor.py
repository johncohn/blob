import sys, threading, time, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import blob_monitor as bm, mido

class FakeOut:
    def __init__(s): s.sent=[]
    def send_message(s,m): s.sent.append(tuple(m))
    def close_port(s): pass

def make():
    m = bm.BlobMonitor.__new__(bm.BlobMonitor)
    m.lock=threading.Lock(); m.mode="IDLE"; m.events=[]; m.play_pos=0.0; m.rec_start=0.0
    m.filename=""; m.log=[]; m.loop_mode=False; m._last_servo_cc=None; m._last_servo_val=0
    m.rec_duration=0.0; m._wired_count=0; m._osc_peers={}; m._osc_sock=None
    m._rec_custom_name=""; m._env_state={}; m.stop_evt=threading.Event(); m._play_thr=None
    m.mid_out=FakeOut(); m.mid_fb=FakeOut(); m._out_needs_reconnect=False
    return m

tmp=Path(tempfile.mkdtemp()); bm.REC_DIR=tmp
m=make()
# live iPad input on ch2: env + servo
for cc,v in [(34,40),(35,100),(33,127),(16,90)]:
    m._on_midi_inner(([0xB1,cc,v],0))
assert m._env_state=={34:40,35:100,33:127}, m._env_state
assert (0xB0,34,40) in m.mid_out.sent, "forwarded to M4 on ch1"
# record: snapshot at t=0, then a servo move and an env change
m._start_record()
assert [(e["t"],e["cc"],e["val"]) for e in m.events]==[(0.0,33,127),(0.0,34,40),(0.0,35,100)], m.events
time.sleep(0.05); m._on_midi_inner(([0xB1,16,100],0)); m._on_midi_inner(([0xB1,35,20],0))
m._stop_record()
f=tmp/"latest.mid"; assert f.exists()
evs,dur=bm.midi_to_events(mido.MidiFile(str(f)))
assert [(e["cc"],e["val"]) for e in evs if e["t"]==0.0]==[(33,127),(34,40),(35,100)], evs
assert any(e["cc"]==35 and e["val"]==20 for e in evs)
# change live state, then play back: the t=0 snapshot must restore the recorded state
m._on_midi_inner(([0xB1,35,5],0)); m._on_midi_inner(([0xB1,33,0],0))
m.mid_out.sent.clear()
m.events, m.rec_duration = evs, dur
m.loop_mode=False; m.stop_evt.clear(); m.mode="PLAYING"
m._play_fn(evs, dur)
first=m.mid_out.sent[:3]
assert first==[(0xB0,33,127),(0xB0,34,40),(0xB0,35,100)], first
assert m._env_state[35]==20 and m._env_state[33]==127, m._env_state   # tracks playback too
# recording with no env ever touched → no snapshot events
m2=make(); m2._start_record(); assert m2.events==[]
# reconnect resend: simulate the loop body
class FakeRt:
    def __init__(s): s.sent=[]
    def get_ports(s): return ["Feather M4 CAN:0"]
    def open_port(s,i): pass
    def send_message(s,msg): s.sent.append(tuple(msg))
fake=FakeRt(); bm.rtmidi.MidiOut=lambda *a,**k: fake
m._out_keywords=["feather"]; m._out_needs_reconnect=True
orig_sleep=bm.time.sleep; calls=[0]
def sl(x):
    calls[0]+=1
    if calls[0]>1: raise SystemExit
bm.time.sleep=sl
try: m._reconnect_out_loop()
except SystemExit: pass
bm.time.sleep=orig_sleep
assert sorted(fake.sent)==sorted((0xB0,c,v) for c,v in m._env_state.items()), fake.sent
assert m._out_needs_reconnect is False
# concurrency: snapshot while another thread hammers _env_state
m3=make(); stop=threading.Event()
def hammer():
    i=0
    while not stop.is_set(): m3._send_cc(32+(i%11),i%128); i+=1
t=threading.Thread(target=hammer); t.start()
for _ in range(2000):
    m3.mode="IDLE"; m3._start_record()
stop.set(); t.join()
# dropped ALSA subscription (M4 replugged) is detected from `aconnect -l`
ACON = """client 20: 'Feather M4 CAN' [type=kernel,card=1]
    0 'Feather M4 CAN MIDI 1'
client 130: 'RtMidiOut Client' [type=user,pid=4242]
    0 'RtMidi output   '
%sclient 131: 'BlobFeedback' [type=user,pid=4242]
    0 'BlobFeedback    '
"""
class _R: pass
def _acon(txt):
    def run(*a, **k):
        r=_R(); r.stdout=txt; return r
    return run
o_run,o_pid,o_which=bm.subprocess.run,bm.os.getpid,bm.shutil.which
bm.os.getpid=lambda:4242; bm.shutil.which=lambda x:"/usr/bin/aconnect"
bm.subprocess.run=_acon(ACON % "\tConnecting To: 20:0\n")
assert m3._out_link_dropped() is False
bm.subprocess.run=_acon(ACON % "")
assert m3._out_link_dropped() is True
bm.subprocess.run,bm.os.getpid,bm.shutil.which=o_run,o_pid,o_which
print("ALL MONITOR TESTS PASSED")

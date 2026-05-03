import rtmidi
import time

def find_port(ports, keywords):
    for i, name in enumerate(ports):
        if any(k.lower() in name.lower() for k in keywords):
            return i, name
    return None, None

def main():
    midi_in = rtmidi.MidiIn()
    midi_out = rtmidi.MidiOut()

    in_ports = midi_in.get_ports()
    out_ports = midi_out.get_ports()

    print("MIDI inputs:")
    for i, p in enumerate(in_ports):
        print(f"  {i}: {p}")
    print("\nMIDI outputs:")
    for i, p in enumerate(out_ports):
        print(f"  {i}: {p}")
    print()

    feather_in, feather_name = find_port(in_ports, ["feather", "m4", "samd"])
    if feather_in is None:
        feather_in = int(input("Feather input port index: "))
        feather_name = in_ports[feather_in]

    twister_out, twister_name = find_port(out_ports, ["twister", "fighter"])
    if twister_out is None:
        twister_out = int(input("Twister output port index: "))
        twister_name = out_ports[twister_out]

    print(f"\nRouting: {feather_name} → {twister_name}")

    midi_in.open_port(feather_in)
    midi_out.open_port(twister_out)

    MSG_TYPES = {0x80: "Note Off", 0x90: "Note On", 0xA0: "Aftertouch",
                 0xB0: "CC", 0xC0: "Prog", 0xD0: "ChanPress", 0xE0: "PitchBend"}

    def on_message(event, _):
        message, _ = event
        midi_out.send_message(message)
        msg_type = message[0] & 0xF0
        channel  = (message[0] & 0x0F) + 1
        label    = MSG_TYPES.get(msg_type, f"0x{msg_type:02X}")
        if msg_type == 0xB0:
            print(f"  → {twister_name}: Ch{channel} {label} {message[1]} = {message[2]}")
        else:
            print(f"  → {twister_name}: Ch{channel} {label} {message[1:]}")

    midi_in.set_callback(on_message)
    midi_in.ignore_types(sysex=False, timing=False, active_sense=True)

    print("Active — echoing all routed messages below.")
    print(f"  Format: Ch<channel> CC <cc_number> = <value>")
    print(f"  Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        midi_in.close_port()
        midi_out.close_port()
        print("Stopped.")

if __name__ == "__main__":
    main()

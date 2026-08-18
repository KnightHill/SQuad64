import time
import mido


# ------------------------------------------------------------
# SQ-64 protocol
# ------------------------------------------------------------

KORG_ID = 0x42
SQ64_ID = [0x00, 0x01, 0x60]

FUNC_CURRENT_PROJECT_REQUEST = 0x11
FUNC_CURRENT_PROJECT_DUMP    = 0x41
FUNC_MELODY_PATTERN_DUMP     = 0x48
FUNC_FINALIZE                = 0x70

FUNC_ACK         = 0x23
FUNC_BUSY_ERROR  = 0x24
FUNC_PARAM_ERROR = 0x25
FUNC_FORMAT_ERROR = 0x26
FUNC_NO_DATA     = 0x30


# SQ-64 Global MIDI channel.
# Channel 1 = 0 here, channel 16 = 15.
GLOBAL_CHANNEL = 0


# ------------------------------------------------------------
# MIDI ports
# ------------------------------------------------------------

def find_sq64_ports():
    inputs = [p for p in mido.get_input_names() if "SQ-64" in p.upper()]
    outputs = [p for p in mido.get_output_names() if "SQ-64" in p.upper()]

    print("Inputs:")
    for p in mido.get_input_names():
        print(" ", p)

    print("\nOutputs:")
    for p in mido.get_output_names():
        print(" ", p)

    if not inputs:
        raise RuntimeError("No SQ-64 MIDI input port found")

    if not outputs:
        raise RuntimeError("No SQ-64 MIDI output port found")

    return inputs[0], outputs[0]


# ------------------------------------------------------------
# Korg SysEx
# ------------------------------------------------------------

def sq64_sysex(function, extra=()):
    device_id = 0x30 + GLOBAL_CHANNEL

    return mido.Message(
        "sysex",
        data=[
            KORG_ID,
            device_id,
            *SQ64_ID,
            function,
            *extra,
        ],
    )


def get_function(msg):
    if msg.type != "sysex":
        return None

    d = list(msg.data)

    if len(d) < 6:
        return None

    expected = [
        KORG_ID,
        0x30 + GLOBAL_CHANNEL,
        *SQ64_ID,
    ]

    if d[:5] != expected:
        return None

    return d[5]


def wait_for_function(port, wanted, timeout=5.0):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        msg = port.poll()

        if msg is None:
            time.sleep(0.001)
            continue

        func = get_function(msg)

        if func is None:
            continue

        if func in (
            FUNC_BUSY_ERROR,
            FUNC_PARAM_ERROR,
            FUNC_FORMAT_ERROR,
            FUNC_NO_DATA,
        ):
            raise RuntimeError(
                f"SQ-64 returned error function 0x{func:02X}"
            )

        if func == wanted:
            return msg

    raise TimeoutError(
        f"Timed out waiting for SQ-64 function 0x{wanted:02X}"
    )


def wait_for_ack(port):
    wait_for_function(port, FUNC_ACK)


# ------------------------------------------------------------
# Korg 8-bit -> MIDI 7-bit conversion
# ------------------------------------------------------------

def pack_7bit(data):
    """
    Convert arbitrary 8-bit SQ-64 data into Korg's MIDI-safe
    7-bit representation.

    Seven source bytes become eight MIDI bytes.
    """

    result = []

    for start in range(0, len(data), 7):
        block = data[start:start + 7]

        msbs = 0

        for i, value in enumerate(block):
            if value & 0x80:
                msbs |= 1 << i

        result.append(msbs)

        for value in block:
            result.append(value & 0x7F)

    return result


def unpack_7bit(data, expected_size):
    result = []

    i = 0

    while i < len(data) and len(result) < expected_size:
        msbs = data[i]
        i += 1

        for bit in range(7):
            if i >= len(data):
                break

            value = data[i]
            i += 1

            if msbs & (1 << bit):
                value |= 0x80

            result.append(value)

            if len(result) == expected_size:
                break

    return bytearray(result)


# ------------------------------------------------------------
# Read current SQ-64 project header
# ------------------------------------------------------------

def read_current_project_header(inport, outport):
    # Request current project.
    outport.send(
        sq64_sysex(FUNC_CURRENT_PROJECT_REQUEST)
    )

    msg = wait_for_function(
        inport,
        FUNC_CURRENT_PROJECT_DUMP
    )

    packed = list(msg.data)[6:]

    if len(packed) != 586:
        raise RuntimeError(
            f"Expected 586 project bytes, got {len(packed)}"
        )

    project = unpack_7bit(packed, 512)

    if project[:4] != b"PROJ":
        raise RuntimeError("Invalid SQ-64 project data")

    # End the read-project transaction.
    outport.send(sq64_sysex(FUNC_FINALIZE))
    wait_for_ack(inport)

    return project


# ------------------------------------------------------------
# Build one melodic pattern
# ------------------------------------------------------------

def build_pattern():
    data = bytearray(3104)

    # Pattern header
    data[0:4] = b"PATT"

    name = b"PYTHON TEST"
    data[4:20] = name.ljust(16, b" ")

    # Pattern length
    data[20] = 16

    # Scale type = Equal
    data[21] = 0

    # Root = C
    data[22] = 0

    # MONO mode
    data[23] = 0

    # Remaining pattern parameters stay at zero.
    #
    # Our simple sequence:
    #
    # C3  -  E3  -  G3  -  E3  -
    # C4  -  G3  -  E3  -  D3  -
    #
    # MIDI convention:
    # C3 = 48

    notes = [
        48, None,
        52, None,
        55, None,
        52, None,
        60, None,
        55, None,
        52, None,
        50, None,
    ]

    for step_number, note in enumerate(notes):
        if note is None:
            continue

        step_offset = 32 + step_number * 48

        # Note Event 1 occupies bytes 0..4 inside each step.
        note_offset = step_offset

        # MIDI note number
        data[note_offset + 0] = note

        # SQ-64 velocity uses 0.5 increments.
        # 200 => velocity 100.
        data[note_offset + 1] = 200

        # Gate offset = 0%
        data[note_offset + 2] = 0

        # Gate length = 80%
        data[note_offset + 3] = 80

        # Event flags:
        #
        # bit 0 = Trigger
        # bit 2 = Gate
        # bit 3 = Note
        # bit 4 = Event Exists
        #
        data[note_offset + 4] = (
            (1 << 0) |
            (1 << 2) |
            (1 << 3) |
            (1 << 4)
        )

        # Step event offset 47:
        # bit 0 = step enabled
        data[step_offset + 47] = 1

    return data


# ------------------------------------------------------------
# Send project + pattern
# ------------------------------------------------------------

def send_pattern(inport, outport, project, pattern):
    #
    # 1. CURRENT PROJECT DATA DUMP
    #
    project_packed = pack_7bit(project)

    assert len(project_packed) == 586

    outport.send(
        sq64_sysex(
            FUNC_CURRENT_PROJECT_DUMP,
            project_packed
        )
    )

    wait_for_ack(inport)

    #
    # 2. MELODY PATTERN DATA DUMP
    #
    # tt = 0 -> Track A
    # pp = 0 -> Pattern 1
    #
    track = 0
    pattern_number = 0

    selector = (track << 4) | pattern_number

    pattern_packed = pack_7bit(pattern)

    assert len(pattern) == 3104
    assert len(pattern_packed) == 3548

    outport.send(
        sq64_sysex(
            FUNC_MELODY_PATTERN_DUMP,
            [selector, *pattern_packed]
        )
    )

    wait_for_ack(inport)

    #
    # 3. Finalize project transfer
    #
    outport.send(
        sq64_sysex(FUNC_FINALIZE)
    )

    wait_for_ack(inport)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    input_name, output_name = find_sq64_ports()

    print()
    print("SQ-64 input :", input_name)
    print("SQ-64 output:", output_name)

    with (
        mido.open_input(input_name) as inp,
        mido.open_output(output_name) as out
    ):
        print("\nReading current project header...")
        project = read_current_project_header(inp, out)

        print("Building test pattern...")
        pattern = build_pattern()

        print("Sending Track A / Pattern 1...")
        send_pattern(inp, out, project, pattern)

        print("Done.")


if __name__ == "__main__":
    main()


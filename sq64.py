import time
import mido


# ------------------------------------------------------------
# SQ-64 protocol
# ------------------------------------------------------------

KORG_ID = 0x42
SQ64_ID = [0x00, 0x01, 0x60]

FUNC_CURRENT_PROJECT_REQUEST = 0x11
FUNC_MELODY_PATTERN_REQUEST  = 0x18
FUNC_RHYTHM_PATTERN_REQUEST  = 0x19
FUNC_CURRENT_PROJECT_DUMP    = 0x41
FUNC_MELODY_PATTERN_DUMP     = 0x48
FUNC_RHYTHM_PATTERN_DUMP     = 0x49
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
    """Find the ALSA MIDI endpoints used for SQ-64 SysEx transfers."""
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

    # On this SQ-64 ALSA USB layout, MIDI OUT 2 carries SysEx responses
    # from the device, while SEQ is the endpoint used to send sequencer
    # and SysEx data to it. ALSA exposes the OUT endpoints in both lists,
    # so selecting the first matching port silently routes requests nowhere.
    sequence_outputs = [p for p in outputs if "SEQ" in p.upper()]

    if not sequence_outputs:
        raise RuntimeError("No SQ-64 SEQ MIDI output port found")

    midi_out_2_inputs = [
        p for p in inputs
        if "MIDI OUT 2" in p.upper()
    ]
    input_name = midi_out_2_inputs[0] if midi_out_2_inputs else inputs[-1]

    return input_name, sequence_outputs[0]


# ------------------------------------------------------------
# Korg SysEx
# ------------------------------------------------------------

def sq64_sysex(function, extra=()):
    """Build an SQ-64 Korg SysEx message."""
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
    """Return the function ID from a valid SQ-64 SysEx message."""
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
    """Wait for an SQ-64 SysEx function or raise on timeout or NAK."""
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
    """Wait for the SQ-64 data-load acknowledgement."""
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
    """Decode Korg MIDI-safe 7-bit data into its original bytes."""
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

def read_pattern_dump(inport, outport, request_func, dump_func,
                      selector, packed_size, unpacked_size,
                      expected_signature):
    """Request, validate, and unpack one SQ-64 pattern."""
    outport.send(sq64_sysex(request_func, [selector]))
    msg = wait_for_function(inport, dump_func)

    response = list(msg.data)[6:]

    if not response or response[0] != selector:
        actual = response[0] if response else None
        raise RuntimeError(
            f"Expected pattern selector 0x{selector:02X}, got {actual!r}"
        )

    packed = response[1:]

    if len(packed) != packed_size:
        raise RuntimeError(
            f"Expected {packed_size} pattern bytes, got {len(packed)}"
        )

    pattern = unpack_7bit(packed, unpacked_size)

    if len(pattern) != unpacked_size:
        raise RuntimeError(
            f"Expected {unpacked_size} unpacked pattern bytes, "
            f"got {len(pattern)}"
        )

    if pattern[:4] != expected_signature:
        raise RuntimeError(
            f"Invalid SQ-64 pattern signature {bytes(pattern[:4])!r}; "
            f"expected {expected_signature!r}"
        )

    return pattern


def read_current_project(inport, outport):
    """Read the current project and all patterns marked as present."""
    # Request current project.
    outport.send(
        sq64_sysex(FUNC_CURRENT_PROJECT_REQUEST)
    )

    def finalize_transaction():
        """Leave the SQ-64 project-read transaction."""
        outport.send(sq64_sysex(FUNC_FINALIZE))

        try:
            wait_for_ack(inport)
        except TimeoutError:
            # Some SQ-64 v2.x units leave transmitting-project mode without
            # returning the documented ACK. The finalize message was still
            # sent, and a missing response is safe to tolerate for a read.
            print(
                "Warning: SQ-64 did not acknowledge project-read finalize"
            )

    try:
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

        if len(project) != 512 or project[:4] != b"PROJ":
            raise RuntimeError("Invalid SQ-64 project data")

        melody_patterns = {}

        for track in range(3):
            for pattern_number in range(16):
                presence_offset = 40 + track * 2 + pattern_number // 8
                presence_bit = pattern_number % 8

                if not project[presence_offset] & (1 << presence_bit):
                    continue

                selector = (track << 4) | pattern_number
                print(
                    f"  Dumping Track {chr(ord('A') + track)} / "
                    f"Pattern {pattern_number + 1}..."
                )
                melody_patterns[(track, pattern_number)] = read_pattern_dump(
                    inport,
                    outport,
                    FUNC_MELODY_PATTERN_REQUEST,
                    FUNC_MELODY_PATTERN_DUMP,
                    selector,
                    3548,
                    3104,
                    b"PATT",
                )

        rhythm_patterns = {}

        for pattern_number in range(16):
            presence_offset = 46 + pattern_number // 8
            presence_bit = pattern_number % 8

            if not project[presence_offset] & (1 << presence_bit):
                continue

            print(f"  Dumping Track D / Pattern {pattern_number + 1}...")
            rhythm_patterns[pattern_number] = read_pattern_dump(
                inport,
                outport,
                FUNC_RHYTHM_PATTERN_REQUEST,
                FUNC_RHYTHM_PATTERN_DUMP,
                pattern_number,
                7059,
                6176,
                b"PATR",
            )
    except BaseException:
        # Preserve the original read/validation failure if cleanup also fails.
        try:
            finalize_transaction()
        except Exception as cleanup_error:
            print(
                "Warning: failed to finalize SQ-64 project read: "
                f"{cleanup_error}"
            )
        raise
    else:
        finalize_transaction()

    return project, melody_patterns, rhythm_patterns


def decode_name(data):
    """Decode a fixed-width SQ-64 name field."""
    return bytes(data[4:20]).decode("ascii", errors="replace").rstrip()


def render_melody_steps(pattern):
    """Render melodic notes and rests as rows of step symbols."""
    symbols = []

    for step_number in range(pattern[20]):
        step_offset = 32 + step_number * 48
        step_enabled = bool(pattern[step_offset + 47] & 1)
        has_note = any(
            pattern[step_offset + note_number * 5 + 4] & (1 << 3)
            for note_number in range(8)
        )
        symbols.append("■" if step_enabled and has_note else " ")

    return [
        "".join(symbols[start:start + 16])
        for start in range(0, len(symbols), 16)
    ]


def render_rhythm_steps(pattern, subtrack_number):
    """Render one drum sub-track as rows of trigger symbols."""
    symbols = []
    subtrack_offset = 32 + subtrack_number * 384

    for step_number in range(pattern[20]):
        step_offset = subtrack_offset + step_number * 6
        trigger_enabled = bool(pattern[step_offset + 3] & (1 << 7))
        symbols.append("■" if trigger_enabled else " ")

    return [
        "".join(symbols[start:start + 16])
        for start in range(0, len(symbols), 16)
    ]


def print_project_dump(project, melody_patterns, rhythm_patterns):
    """Print a concise summary of a dumped SQ-64 project."""
    project_name = decode_name(project)
    tempo = (project[20] | project[21] << 8) / 10

    print("\nProject dump:")
    print("  Name   :", project_name or "(unnamed)")
    print(f"  Tempo  : {tempo:.1f} BPM")
    print("  Header : 512 bytes")

    if not melody_patterns and not rhythm_patterns:
        print("  Patterns: none")
        return

    print("  Patterns:")

    for (track, pattern_number), pattern in sorted(
        melody_patterns.items()
    ):
        name = decode_name(pattern) or "(unnamed)"
        print(
            f"    Track {chr(ord('A') + track)} / "
            f"Pattern {pattern_number + 1}: {name}, "
            f"{pattern[20]} steps, {len(pattern)} bytes"
        )

        for row in render_melody_steps(pattern):
            print(f"      |{row:<16}|")

    for pattern_number, pattern in sorted(rhythm_patterns.items()):
        name = decode_name(pattern) or "(unnamed)"
        print(
            f"    Track D / Pattern {pattern_number + 1}: {name}, "
            f"{pattern[20]} steps, {len(pattern)} bytes"
        )

        for subtrack_number in range(16):
            rows = render_rhythm_steps(pattern, subtrack_number)

            if not any("■" in row for row in rows):
                continue

            for row_number, row in enumerate(rows):
                label = (
                    f"D{subtrack_number + 1:02}"
                    if row_number == 0
                    else "   "
                )
                print(f"      {label} |{row:<16}|")


# ------------------------------------------------------------
# Build one melodic pattern
# ------------------------------------------------------------

def build_reference_structure():
    """Reproduce the initialized melodic structure captured from the SQ-64."""
    data = bytearray(3104)
    data[0:4] = b"PATT"
    data[4:20] = b"Init Pattern".ljust(16, b"\0")
    data[20] = 16
    data[23] = 0
    data[24] = 2
    data[26] = 0x60
    data[28] = 0x10

    for step_number in range(64):
        step_offset = 32 + step_number * 48
        note_offset = step_offset
        data[note_offset:note_offset + 5] = bytes([
            48,   # C3
            255,  # Captured modulation/velocity
            0,    # Gate offset
            75,   # Gate length
            0x11, # Trigger + event exists; note is initially off
        ])

        # Step control offset 40: values 19~38 represent probability
        # 100%~5%. Zero selects the **.* alternation pattern, which mutes
        # every third pass rather than playing unconditionally.
        data[step_offset + 40] = 19

    return data


def build_pattern():
    """Build the local 16-step monophonic C-major test pattern."""
    # Start with the replicated SQ-64 structure, then overlay the sequence
    # generated entirely on the laptop.
    data = build_reference_structure()

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

    # Keep the remaining replicated SQ-64 pattern parameters. In particular,
    # this firmware stores the selected 1/16 timing as 0x10 at
    # byte 28 rather than the 0x20 implied by Korg's published bit table.
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
        step_offset = 32 + step_number * 48

        if note is None:
            # Preserve the replicated initialized event data, but disable
            # this step and its note value.
            data[step_offset + 4] &= ~(1 << 3)
            data[step_offset + 47] &= ~1
            continue

        # Note Event 1 occupies bytes 0..4 inside each step.
        note_offset = step_offset

        # MIDI note number
        data[note_offset + 0] = note

        # Note Event flags byte, bit 3 = note enabled.
        data[note_offset + 4] |= 1 << 3

        # Velocity, gate, flags, and all other event fields retain the values
        # captured from the reference pattern.

        # Step event offset 47, bit 0 = step enabled. Preserve the remaining
        # variation-range bits.
        data[step_offset + 47] |= 1

    return data


# ------------------------------------------------------------
# Send project + pattern
# ------------------------------------------------------------

def send_pattern(inport, outport, project, pattern,
                 melody_patterns, rhythm_patterns):
    """Replace A1 while retransmitting all preserved project patterns."""
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
    melody_patterns[(0, 0)] = pattern

    for (track, pattern_number), melody_pattern in sorted(
        melody_patterns.items()
    ):
        selector = (track << 4) | pattern_number
        pattern_packed = pack_7bit(melody_pattern)

        if len(melody_pattern) != 3104 or len(pattern_packed) != 3548:
            raise RuntimeError("Invalid melodic pattern size")

        outport.send(
            sq64_sysex(
                FUNC_MELODY_PATTERN_DUMP,
                [selector, *pattern_packed]
            )
        )

        wait_for_ack(inport)

    for pattern_number, rhythm_pattern in sorted(rhythm_patterns.items()):
        pattern_packed = pack_7bit(rhythm_pattern)

        if len(rhythm_pattern) != 6176 or len(pattern_packed) != 7059:
            raise RuntimeError("Invalid rhythm pattern size")

        outport.send(
            sq64_sysex(
                FUNC_RHYTHM_PATTERN_DUMP,
                [pattern_number, *pattern_packed]
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

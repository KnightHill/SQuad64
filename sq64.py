import time

import mido

from progress import PatternDumpIndicator


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


# MIDI Universal Device Inquiry. The all-call device ID lets the SQ-64 reply
# even when its configured global channel is not known yet.
DEVICE_INQUIRY_REQUEST = [0x7E, 0x7F, 0x06, 0x01]
DEVICE_INQUIRY_REPLY = [0x06, 0x02]
SQ64_FAMILY_ID = [0x60, 0x01]
SQ64_MEMBER_ID = [0x00, 0x00]


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


def get_firmware_version(inport, outport, timeout=5.0):
    """Request and return the connected SQ-64 firmware version."""
    outport.send(mido.Message("sysex", data=DEVICE_INQUIRY_REQUEST))
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        msg = inport.poll()

        if msg is None:
            time.sleep(0.001)
            continue

        if msg.type != "sysex":
            continue

        data = list(msg.data)

        if (
            len(data) < 4
            or data[0] != 0x7E
            or data[2:4] != DEVICE_INQUIRY_REPLY
        ):
            continue

        identity = [KORG_ID, *SQ64_FAMILY_ID, *SQ64_MEMBER_ID]

        if len(data) >= 9 and data[4:9] != identity:
            continue

        if len(data) != 13:
            raise RuntimeError(
                f"Invalid SQ-64 device inquiry reply length {len(data)}"
            )

        minor = data[9] | data[10] << 7
        major = data[11] | data[12] << 7

        return f"{major}.{minor:02d}"

    raise TimeoutError("Timed out waiting for SQ-64 firmware version")


# ------------------------------------------------------------
# Korg SysEx
# ------------------------------------------------------------

def sq64_sysex(function, extra=(), global_channel=None):
    """Build an SQ-64 Korg SysEx message."""
    if global_channel is None:
        global_channel = GLOBAL_CHANNEL

    device_id = 0x30 + global_channel

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


def get_function(msg, global_channel=None):
    """Return the function ID from a valid SQ-64 SysEx message."""
    if global_channel is None:
        global_channel = GLOBAL_CHANNEL

    if msg.type != "sysex":
        return None

    d = list(msg.data)

    if len(d) < 6:
        return None

    expected = [
        KORG_ID,
        0x30 + global_channel,
        *SQ64_ID,
    ]

    if d[:5] != expected:
        return None

    return d[5]


def wait_for_function(port, wanted, timeout=5.0, *, global_channel=None,
                      progress=None):
    """Wait for an SQ-64 SysEx function or raise on timeout or NAK."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if progress is not None:
            progress()

        msg = port.poll()

        if msg is None:
            time.sleep(0.001)
            continue

        func = get_function(msg, global_channel)

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


def wait_for_ack(port, context="data transfer", timeout=10.0, *,
                 global_channel=None):
    """Wait for an SQ-64 acknowledgement with transfer context."""
    try:
        wait_for_function(
            port,
            FUNC_ACK,
            timeout,
            global_channel=global_channel,
        )
    except TimeoutError as error:
        raise TimeoutError(
            f"Timed out waiting for SQ-64 ACK after {context}"
        ) from error


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
                      expected_signature, *, global_channel=None,
                      progress=None):
    """Request, validate, and unpack one SQ-64 pattern."""
    outport.send(sq64_sysex(request_func, [selector], global_channel))
    msg = wait_for_function(
        inport,
        dump_func,
        global_channel=global_channel,
        progress=progress,
    )

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


def read_current_project(inport, outport, *, global_channel=None):
    """Read the current project and all patterns marked as present."""
    # Request current project.
    outport.send(
        sq64_sysex(
            FUNC_CURRENT_PROJECT_REQUEST,
            global_channel=global_channel,
        )
    )

    def finalize_transaction():
        """Leave the SQ-64 project-read transaction."""
        outport.send(sq64_sysex(
            FUNC_FINALIZE,
            global_channel=global_channel,
        ))

        try:
            wait_for_ack(inport, global_channel=global_channel)
        except TimeoutError:
            # Some SQ-64 v2.x units leave transmitting-project mode without
            # returning the documented ACK. The finalize message was still
            # sent, and a missing response is safe to tolerate for a read.
            print(
                "Warning: SQ-64 did not acknowledge project-read finalize"
            )

    indicator = PatternDumpIndicator()

    try:
        msg = wait_for_function(
            inport,
            FUNC_CURRENT_PROJECT_DUMP,
            global_channel=global_channel,
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
                indicator.start(
                    f"Track {chr(ord('A') + track)} / "
                    f"Pattern {pattern_number + 1}"
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
                    global_channel=global_channel,
                    progress=indicator.update,
                )
                indicator.complete()

        rhythm_patterns = {}

        for pattern_number in range(16):
            presence_offset = 46 + pattern_number // 8
            presence_bit = pattern_number % 8

            if not project[presence_offset] & (1 << presence_bit):
                continue

            indicator.start(f"Track D / Pattern {pattern_number + 1}")
            rhythm_patterns[pattern_number] = read_pattern_dump(
                inport,
                outport,
                FUNC_RHYTHM_PATTERN_REQUEST,
                FUNC_RHYTHM_PATTERN_DUMP,
                pattern_number,
                7059,
                6176,
                b"PATR",
                global_channel=global_channel,
                progress=indicator.update,
            )
            indicator.complete()
    except BaseException:
        indicator.finish(success=False)
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
        indicator.finish()
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


def print_project_dump(project, melody_patterns, rhythm_patterns, *,
                       track=None, pattern_number=None):
    """Print a concise summary of a dumped SQ-64 project."""
    if track is not None:
        track = track.upper()

    filtered_melodies = [
        ((track_index, number), pattern)
        for (track_index, number), pattern in sorted(
            melody_patterns.items()
        )
        if (
            track in (None, chr(ord("A") + track_index))
            and pattern_number in (None, number + 1)
        )
    ]
    filtered_rhythms = [
        (number, pattern)
        for number, pattern in sorted(rhythm_patterns.items())
        if (
            track in (None, "D")
            and pattern_number in (None, number + 1)
        )
    ]

    project_name = decode_name(project)
    tempo = (project[20] | project[21] << 8) / 10

    print("\nProject dump:")
    print("  Name   :", project_name or "(unnamed)")
    print(f"  Tempo  : {tempo:.1f} BPM")
    print("  Header : 512 bytes")

    if not filtered_melodies and not filtered_rhythms:
        print("  Patterns: none")
        return

    print("  Patterns:")

    for (track_index, number), pattern in filtered_melodies:
        name = decode_name(pattern) or "(unnamed)"
        print(
            f"    Track {chr(ord('A') + track_index)} / "
            f"Pattern {number + 1}: {name}, "
            f"{pattern[20]} steps, {len(pattern)} bytes"
        )

        for row in render_melody_steps(pattern):
            print(f"      |{row:<16}|")

    for number, pattern in filtered_rhythms:
        name = decode_name(pattern) or "(unnamed)"
        print(
            f"    Track D / Pattern {number + 1}: {name}, "
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
                 melody_patterns, rhythm_patterns, *, global_channel=None):
    """Replace A1 while retransmitting all preserved project patterns."""
    # Validate and pack everything before putting the SQ-64 into receiving
    # project mode.
    project_packed = pack_7bit(project)

    if len(project) != 512 or len(project_packed) != 586:
        raise RuntimeError("Invalid project size")

    prepared_melodies = []
    updated_melodies = {**melody_patterns, (0, 0): pattern}
    for (track, pattern_number), melody_pattern in sorted(
        updated_melodies.items()
    ):
        selector = (track << 4) | pattern_number
        pattern_packed = pack_7bit(melody_pattern)

        if len(melody_pattern) != 3104 or len(pattern_packed) != 3548:
            raise RuntimeError("Invalid melodic pattern size")

        label = (
            f"Track {chr(ord('A') + track)} / "
            f"Pattern {pattern_number + 1}"
        )
        prepared_melodies.append((label, selector, pattern_packed))

    prepared_rhythms = []
    for pattern_number, rhythm_pattern in sorted(rhythm_patterns.items()):
        pattern_packed = pack_7bit(rhythm_pattern)

        if len(rhythm_pattern) != 6176 or len(pattern_packed) != 7059:
            raise RuntimeError("Invalid rhythm pattern size")

        label = f"Track D / Pattern {pattern_number + 1}"
        prepared_rhythms.append((label, pattern_number, pattern_packed))

    transfer_error = None

    try:
        print("  Sending current project header...")
        outport.send(
            sq64_sysex(
                FUNC_CURRENT_PROJECT_DUMP,
                project_packed,
                global_channel,
            )
        )
        wait_for_ack(
            inport,
            "current project header",
            global_channel=global_channel,
        )

        for label, selector, pattern_packed in prepared_melodies:
            print(f"  Sending {label}...")
            outport.send(
                sq64_sysex(
                    FUNC_MELODY_PATTERN_DUMP,
                    [selector, *pattern_packed],
                    global_channel,
                )
            )
            wait_for_ack(
                inport,
                label,
                global_channel=global_channel,
            )

        for label, pattern_number, pattern_packed in prepared_rhythms:
            print(f"  Sending {label}...")
            outport.send(
                sq64_sysex(
                    FUNC_RHYTHM_PATTERN_DUMP,
                    [pattern_number, *pattern_packed],
                    global_channel,
                )
            )
            wait_for_ack(
                inport,
                label,
                global_channel=global_channel,
            )
    except BaseException as error:
        transfer_error = error
        raise
    finally:
        # Once the header send has been attempted, always send finalize so a
        # timeout, NAK, interruption, or backend error cannot knowingly leave
        # the SQ-64 in receiving-project mode.
        try:
            print("  Finalizing project transfer...")
            outport.send(sq64_sysex(
                FUNC_FINALIZE,
                global_channel=global_channel,
            ))
            wait_for_ack(
                inport,
                "project finalize",
                global_channel=global_channel,
            )
        except Exception as cleanup_error:
            if transfer_error is None:
                raise
            print(
                "Warning: failed to finalize SQ-64 project transfer: "
                f"{cleanup_error}"
            )

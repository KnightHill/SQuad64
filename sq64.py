import sys
import time
from pathlib import Path
from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)

import mido

from progress import PatternDumpIndicator


class MidiMessage(Protocol):
    """Message attributes used by the SQ-64 protocol helpers."""

    type: str
    data: Sequence[int]


class InputPort(Protocol):
    """Minimal interface required from a MIDI input port."""

    def poll(self) -> Optional[MidiMessage]: ...


class OutputPort(Protocol):
    """Minimal interface required from a MIDI output port."""

    def send(self, message: MidiMessage) -> None: ...


ByteData = Sequence[int]
MelodyKey = Tuple[int, int]
MelodyPatternMap = Mapping[MelodyKey, ByteData]
RhythmPatternMap = Mapping[int, ByteData]
MelodyPatterns = Dict[MelodyKey, bytearray]
RhythmPatterns = Dict[int, bytearray]
ProjectDump = Tuple[bytearray, MelodyPatterns, RhythmPatterns]
ProgressCallback = Callable[[], None]


# VELOCITY_CYAN_COLORS = (23, 24, 31, 37, 38, 44, 45, 51)

# ANSI 256-color grayscale shades, ordered from quietest to loudest.
# Colors are only emitted for interactive terminals so project dumps remain
# pipeable and easy to test as plain text.
VELOCITY_GRAY_COLORS = (238, 240, 242, 244, 246, 248, 250, 255)


def _colorize_velocity(symbol: str, velocity: int) -> str:
    """Color a note symbol with a grayscale shade based on its velocity."""
    color_index = velocity * (len(VELOCITY_GRAY_COLORS) - 1) // 255
    color = VELOCITY_GRAY_COLORS[color_index]
    return f"\033[38;5;{color}m{symbol}\033[0m"


# ------------------------------------------------------------
# SQ-64 protocol
# ------------------------------------------------------------

KORG_ID = 0x42
SQ64_ID = [0x00, 0x01, 0x60]

FUNC_CURRENT_PROJECT_REQUEST = 0x11
FUNC_MELODY_PATTERN_REQUEST  = 0x18
FUNC_RHYTHM_PATTERN_REQUEST  = 0x19
FUNC_GLOBAL_DATA_REQUEST     = 0x0E
FUNC_CURRENT_PROJECT_DUMP    = 0x41
FUNC_MELODY_PATTERN_DUMP     = 0x48
FUNC_RHYTHM_PATTERN_DUMP     = 0x49
FUNC_GLOBAL_DATA_DUMP        = 0x50
FUNC_FINALIZE                = 0x70

FUNC_ACK         = 0x23
FUNC_BUSY_ERROR  = 0x24
FUNC_PARAM_ERROR = 0x25
FUNC_FORMAT_ERROR = 0x26
FUNC_NO_DATA     = 0x30

ALSA_SEQ_OUTPUT_BUFFER = Path(
    "/sys/module/snd_seq_midi/parameters/output_buffer_size"
)
MIN_ALSA_SEQ_OUTPUT_BUFFER = 8192


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

def find_sq64_ports(*, verbose: bool = False) -> Tuple[str, str]:
    """Find the ALSA MIDI endpoints used for SQ-64 SysEx transfers."""
    inputs = [p for p in mido.get_input_names() if "SQ-64" in p.upper()]
    outputs = [p for p in mido.get_output_names() if "SQ-64" in p.upper()]

    if verbose:
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


def ensure_large_sysex_output(outport: OutputPort) -> None:
    """Reject an ALSA sequencer port that would truncate rhythm dumps."""
    if getattr(outport, "_device_type", None) != "RtMidi/LINUX_ALSA":
        return

    try:
        buffer_size = int(
            ALSA_SEQ_OUTPUT_BUFFER.read_text(encoding="ascii").strip()
        )
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "Unable to check the ALSA MIDI output buffer size"
        ) from error

    if buffer_size < MIN_ALSA_SEQ_OUTPUT_BUFFER:
        raise RuntimeError(
            f"ALSA MIDI output buffer is {buffer_size} bytes; SQ-64 Track D "
            f"transfers require at least {MIN_ALSA_SEQ_OUTPUT_BUFFER}. Run:\n"
            "  ./setup-midi-buffer.sh"
        )


def get_firmware_version(
    inport: InputPort,
    outport: OutputPort,
    timeout: float = 5.0,
) -> str:
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

def sq64_sysex(
    function: int,
    extra: ByteData = (),
    global_channel: Optional[int] = None,
) -> MidiMessage:
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


def get_function(
    msg: MidiMessage,
    global_channel: Optional[int] = None,
) -> Optional[int]:
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


def wait_for_function(
    port: InputPort,
    wanted: int,
    timeout: float = 5.0,
    *,
    global_channel: Optional[int] = None,
    progress: Optional[ProgressCallback] = None,
) -> MidiMessage:
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


def wait_for_ack(
    port: InputPort,
    context: str = "data transfer",
    timeout: float = 10.0,
    *,
    global_channel: Optional[int] = None,
) -> None:
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

def pack_7bit(data: ByteData) -> List[int]:
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


def unpack_7bit(data: ByteData, expected_size: int) -> bytearray:
    """Decode Korg MIDI-safe 7-bit data into its original bytes."""
    result: List[int] = []

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
# Read SQ-64 global data
# ------------------------------------------------------------

def read_global_data(
    inport: InputPort,
    outport: OutputPort,
    *,
    global_channel: Optional[int] = None,
) -> bytearray:
    """Request, validate, and unpack the SQ-64 global settings."""
    outport.send(sq64_sysex(
        FUNC_GLOBAL_DATA_REQUEST,
        global_channel=global_channel,
    ))
    msg = wait_for_function(
        inport,
        FUNC_GLOBAL_DATA_DUMP,
        global_channel=global_channel,
    )
    packed = list(msg.data)[6:]

    if len(packed) != 586:
        raise RuntimeError(
            f"Expected 586 global data bytes, got {len(packed)}"
        )

    global_data = unpack_7bit(packed, 512)

    if len(global_data) != 512 or global_data[:4] != b"GLOB":
        raise RuntimeError("Invalid SQ-64 global data")

    return global_data


def _format_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> str:
    """Format rows as a compact terminal-friendly table."""
    widths = [len(header) for header in headers]

    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def format_row(row: Sequence[str]) -> str:
        return " | ".join(
            value.ljust(widths[index])
            for index, value in enumerate(row)
        )

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join([
        format_row(headers),
        separator,
        *(format_row(row) for row in rows),
    ])


def print_global_data(global_data: ByteData) -> None:
    """Print decoded SQ-64 global settings as readable tables."""
    if len(global_data) != 512 or bytes(global_data[:4]) != b"GLOB":
        raise RuntimeError("Invalid SQ-64 global data")

    def choice(value: int, choices: Sequence[str]) -> str:
        if 0 <= value < len(choices):
            return choices[value]
        return f"Unknown ({value})"

    def on_off(value: int) -> str:
        return choice(value, ("Off", "On"))

    def channel(value: int) -> str:
        return f"CH{value + 1}"

    def optional_channel(value: int) -> str:
        return "Subtracks" if value == 0 else f"CH{value}"

    def note_name(value: int) -> str:
        names = (
            "C", "C#", "D", "D#", "E", "F",
            "F#", "G", "G#", "A", "A#", "B",
        )
        return f"{names[value % 12]}{value // 12 - 1} ({value})"

    global_rows = [
        ("Clock source", choice(global_data[4],
                                 ("Auto", "Internal", "USB", "MIDI"))),
        ("Sync in rate", choice(global_data[5],
                                ("Unknown (0)", "4 PPQN", "12 PPQN",
                                 "24 PPQN", "48 PPQN"))),
        ("Sync in polarity", choice(global_data[6],
                                    ("Active high", "Active low"))),
        ("Sync out rate", choice(global_data[7],
                                 ("2 PPQN", "4 PPQN", "12 PPQN",
                                  "24 PPQN", "48 PPQN"))),
        ("Sync out polarity", choice(global_data[8],
                                     ("Active high", "Active low"))),
        ("Sync out transport", on_off(global_data[9])),
        ("RX transport USB", on_off(global_data[10])),
        ("RX transport MIDI", on_off(global_data[11])),
        ("RX program channel",
         "Any" if global_data[12] == 0 else f"CH{global_data[12]}"),
        ("RX program USB", on_off(global_data[13])),
        ("RX program MIDI", on_off(global_data[14])),
        ("TX transport USB", on_off(global_data[15])),
        ("TX transport MIDI1", on_off(global_data[16])),
        ("TX transport MIDI2", on_off(global_data[17])),
        ("TX program channel", channel(global_data[18])),
        ("TX program USB", on_off(global_data[19])),
        ("TX program MIDI1", on_off(global_data[20])),
        ("TX program MIDI2", on_off(global_data[21])),
        ("MIDI thru", on_off(global_data[22])),
        ("Keyboard layout", choice(global_data[23],
                                   ("Keys", "Isomorphic", "Octaves"))),
        ("Display brightness", str(global_data[24] + 1)),
        ("Auto power off", choice(global_data[25],
                                  ("Disabled", "Enabled"))),
        ("USB power", choice(global_data[26], ("500 mA", "2 A"))),
        ("Add gate", on_off(global_data[27])),
        ("Keyboard behavior", choice(global_data[28],
                                     ("Transpose", "Overdub", "Overwrite"))),
        ("Mod display", choice(global_data[29], ("Gates", "Values"))),
        ("Drum pad layout", choice(global_data[30],
                                   ("4x4-A", "4x4-B", "16+velocity", "8x2"))),
        ("Track D gate polarity", choice(global_data[148],
                                         ("Subtracks", "V-Trig", "S-Trig"))),
        ("Track D gate range", choice(global_data[149], ("5 V", "10 V"))),
        ("Track D record quantize", choice(
            global_data[157],
            ("Unknown (0)", "None", "1/8 step", "1/4 step",
             "1/2 step", "1/1 step"),
        )),
        ("Control mapping", f"Mapping {global_data[486] + 1}"),
    ]

    midi_rows = []
    for track_index, track in enumerate("ABC"):
        base = 48 + track_index * 32
        midi_rows.append((
            track,
            channel(global_data[base + 13]),
            on_off(global_data[base + 14]),
            on_off(global_data[base + 15]),
            channel(global_data[base + 16]),
            on_off(global_data[base + 17]),
            on_off(global_data[base + 18]),
            on_off(global_data[base + 19]),
        ))

    midi_rows.append((
        "D",
        optional_channel(global_data[150]),
        on_off(global_data[151]),
        on_off(global_data[152]),
        optional_channel(global_data[153]),
        on_off(global_data[154]),
        on_off(global_data[155]),
        on_off(global_data[156]),
    ))

    control_ports = global_data[485]
    midi_rows.append((
        "Control", "—", "—", "—", channel(global_data[484]),
        on_off(control_ports & 1),
        on_off((control_ports >> 1) & 1),
        on_off((control_ports >> 2) & 1),
    ))

    drum_rows = []
    for subtrack in range(16):
        base = 176 + subtrack * 19
        rx_note = global_data[base + 6]
        drum_rows.append((
            f"D{subtrack + 1}",
            choice(global_data[base + 4], ("V-Trig", "S-Trig")),
            channel(global_data[base + 5]),
            "Any" if rx_note == 0 else note_name(rx_note - 1),
            channel(global_data[base + 7]),
            note_name(global_data[base + 8]),
        ))

    print("Global settings:")
    print(_format_table(("Parameter", "Value"), global_rows))
    print("\nMIDI routing:")
    print(_format_table(
        ("Track", "RX ch", "RX USB", "RX MIDI", "TX ch",
         "TX USB", "TX MIDI1", "TX MIDI2"),
        midi_rows,
    ))
    print("\nDrum subtracks:")
    print(_format_table(
        ("Track", "Gate", "RX ch", "RX note", "TX ch", "TX note"),
        drum_rows,
    ))


# ------------------------------------------------------------
# Read current SQ-64 project header
# ------------------------------------------------------------

def read_pattern_dump(
    inport: InputPort,
    outport: OutputPort,
    request_func: int,
    dump_func: int,
    selector: int,
    packed_size: int,
    unpacked_size: int,
    expected_signature: bytes,
    *,
    global_channel: Optional[int] = None,
    progress: Optional[ProgressCallback] = None,
) -> bytearray:
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


def read_current_project(
    inport: InputPort,
    outport: OutputPort,
    *,
    global_channel: Optional[int] = None,
) -> ProjectDump:
    """Read the current project and all patterns marked as present."""
    # Request current project.
    outport.send(
        sq64_sysex(
            FUNC_CURRENT_PROJECT_REQUEST,
            global_channel=global_channel,
        )
    )

    def finalize_transaction() -> None:
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


def decode_name(data: Sequence[int]) -> str:
    """Decode a fixed-width SQ-64 name field."""
    return bytes(data[4:20]).decode("ascii", errors="replace").rstrip(" \0")


def render_melody_steps(
    pattern: ByteData,
    *,
    color: bool = False,
) -> List[str]:
    """Render all melodic steps as one row with 16-step separators."""
    symbols = []

    for step_number in range(pattern[20]):
        step_offset = 32 + step_number * 48
        step_enabled = bool(pattern[step_offset + 47] & 1)
        velocities = [
            pattern[step_offset + note_number * 5 + 1]
            for note_number in range(8)
            if pattern[step_offset + note_number * 5 + 4] & (1 << 3)
        ]
        if step_enabled and velocities:
            symbol = "■"
            symbols.append(
                _colorize_velocity(symbol, max(velocities))
                if color else symbol
            )
        else:
            symbols.append(" ")

    return [
        "|".join(
            "".join(symbols[start:start + 16])
            for start in range(0, len(symbols), 16)
        )
    ]


def render_rhythm_steps(
    pattern: ByteData,
    subtrack_number: int,
    *,
    color: bool = False,
) -> List[str]:
    """Render one drum sub-track with 16-step separators."""
    symbols = []
    subtrack_offset = 32 + subtrack_number * 384

    for step_number in range(pattern[20]):
        step_offset = subtrack_offset + step_number * 6
        trigger_enabled = bool(pattern[step_offset + 3] & (1 << 7))
        if trigger_enabled:
            symbol = "■"
            symbols.append(
                _colorize_velocity(symbol, pattern[step_offset])
                if color else symbol
            )
        else:
            symbols.append(" ")

    return [
        "|".join(
            "".join(symbols[start:start + 16])
            for start in range(0, len(symbols), 16)
        )
    ]


def print_project_dump(
    project: ByteData,
    melody_patterns: MelodyPatternMap,
    rhythm_patterns: RhythmPatternMap,
    *,
    track: Optional[str] = None,
    pattern_number: Optional[int] = None,
) -> None:
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
    print(
        f"  Name: {project_name or '(unnamed)'}"
        f" | BPM: {tempo:.1f}"
    )

    if not filtered_melodies and not filtered_rhythms:
        print("  Patterns: none")
        return

    print("  Patterns:")
    use_color = sys.stdout.isatty()

    for (track_index, number), pattern in filtered_melodies:
        name = decode_name(pattern) or "(unnamed)"
        print(
            f"    Track {chr(ord('A') + track_index)} / "
            f"Pattern {number + 1}: {name}, "
            f"{pattern[20]} steps"
        )

        for row in render_melody_steps(pattern, color=use_color):
            print(f"      |{row}|")

    for number, pattern in filtered_rhythms:
        name = decode_name(pattern) or "(unnamed)"
        print(
            f"    Track D / Pattern {number + 1}: {name}, "
            f"{pattern[20]} steps"
        )

        for subtrack_number in range(16):
            rows = render_rhythm_steps(
                pattern,
                subtrack_number,
                color=use_color,
            )

            if not any("■" in row for row in rows):
                continue

            for row_number, row in enumerate(rows):
                label = (
                    f"D{subtrack_number + 1:02}"
                    if row_number == 0
                    else "   "
                )
                print(f"      {label} |{row}|")


# ------------------------------------------------------------
# Build one melodic pattern
# ------------------------------------------------------------

def build_reference_structure() -> bytearray:
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


def build_pattern(
    notes: Iterable[Optional[int]],
    velocities: Optional[Iterable[int]] = None,
    *,
    name: str = "SQUAD64 TEST",
) -> bytearray:
    """Build a melodic pattern from MIDI note numbers and rests."""
    notes = list(notes)
    if velocities is None:
        velocities = [None] * len(notes)
    else:
        velocities = list(velocities)

    if len(velocities) != len(notes):
        raise ValueError("Pattern notes and velocities must have equal lengths")

    if not 1 <= len(notes) <= 64:
        raise ValueError("Pattern must contain between 1 and 64 steps")

    for note in notes:
        if note is not None and (
            not isinstance(note, int)
            or not 0 <= note <= 127
        ):
            raise ValueError(
                "Pattern notes must be MIDI note numbers from 0 to 127 "
                "or None"
            )

    for velocity in velocities:
        if velocity is not None and (
            not isinstance(velocity, int)
            or not 0 <= velocity <= 255
        ):
            raise ValueError("Pattern velocities must be raw bytes from 0 to 255")

    # Start with the replicated SQ-64 structure, then overlay the sequence
    # generated entirely on the laptop.
    data = build_reference_structure()

    # Pattern header
    data[0:4] = b"PATT"

    encoded_name = name.encode("ascii")
    if not 1 <= len(encoded_name) <= 16:
        raise ValueError("Pattern name must contain between 1 and 16 ASCII bytes")
    data[4:20] = encoded_name.ljust(16, b" ")

    # Pattern length
    data[20] = len(notes)

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
    # MIDI convention:
    # C3 = 48

    for step_number, (note, velocity) in enumerate(zip(notes, velocities)):
        step_offset = 32 + step_number * 48

        if velocity is not None:
            data[step_offset + 1] = velocity

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


def build_empty_pattern() -> bytearray:
    """Build a new 16-step rest pattern using the safe reference structure."""
    return build_pattern(
        [None] * 16,
        [255] * 16,
        name="SQUAD64 NEW",
    )


# ------------------------------------------------------------
# Send project + pattern
# ------------------------------------------------------------

def send_pattern(
    inport: InputPort,
    outport: OutputPort,
    project: ByteData,
    pattern: ByteData,
    melody_patterns: MelodyPatternMap,
    rhythm_patterns: RhythmPatternMap,
    *,
    target_track: int = 0,
    target_pattern: int = 0,
    global_channel: Optional[int] = None,
) -> None:
    """Replace one melodic pattern while preserving all other patterns."""
    # Linux's snd_seq_midi defaults to one 4096-byte page. It silently
    # truncates the 7068-byte Track D SysEx before F7, leaving the SQ-64
    # stuck on "Receiving...". Check before entering project-receive mode.
    ensure_large_sysex_output(outport)

    # Validate and pack everything before putting the SQ-64 into receiving
    # project mode.
    if len(project) != 512:
        raise RuntimeError("Invalid project size")

    updated_project = bytearray(project)
    if not 0 <= target_track <= 2 or not 0 <= target_pattern <= 15:
        raise ValueError("Invalid melodic pattern target")
    presence_offset = 40 + target_track * 2 + target_pattern // 8
    updated_project[presence_offset] |= 1 << (target_pattern % 8)
    project_packed = pack_7bit(updated_project)

    if len(project_packed) != 586:
        raise RuntimeError("Invalid project size")

    prepared_melodies = []
    # Korg's MIDI implementation requires a complete project transfer:
    # patterns omitted between the project header and finalize messages are
    # cleared by the SQ-64. Always retransmit every pattern read from it.
    updated_melodies = {
        **melody_patterns,
        (target_track, target_pattern): pattern,
    }
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

import unittest
from unittest.mock import ANY, Mock, patch

import mido

import sq64


class RecordingPort:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.sent = []

    def poll(self):
        return self.messages.pop(0) if self.messages else None

    def send(self, message):
        self.sent.append(message)


def response(function, extra=()):
    return sq64.sq64_sysex(function, extra)


class MidiPortTests(unittest.TestCase):
    @patch("sq64.mido.get_output_names")
    @patch("sq64.mido.get_input_names")
    def test_find_sq64_ports_prefers_midi_out_2_and_seq(
        self, get_inputs, get_outputs
    ):
        get_inputs.return_value = [
            "Other Port",
            "SQ-64 MIDI OUT 1",
            "SQ-64 MIDI OUT 2",
        ]
        get_outputs.return_value = [
            "SQ-64 MIDI OUT 1",
            "SQ-64 SEQ",
        ]

        self.assertEqual(
            sq64.find_sq64_ports(),
            ("SQ-64 MIDI OUT 2", "SQ-64 SEQ"),
        )

    @patch("sq64.mido.get_output_names", return_value=["SQ-64 SEQ"])
    @patch("sq64.mido.get_input_names", return_value=[])
    def test_find_sq64_ports_requires_input(self, _get_inputs, _get_outputs):
        with self.assertRaisesRegex(RuntimeError, "input port"):
            sq64.find_sq64_ports()

    @patch("sq64.mido.get_output_names", return_value=["SQ-64 MIDI OUT 1"])
    @patch("sq64.mido.get_input_names", return_value=["SQ-64 MIDI OUT 2"])
    def test_find_sq64_ports_requires_seq_output(
        self, _get_inputs, _get_outputs
    ):
        with self.assertRaisesRegex(RuntimeError, "SEQ MIDI output"):
            sq64.find_sq64_ports()

    def test_get_firmware_version_sends_inquiry_and_decodes_reply(self):
        reply = mido.Message(
            "sysex",
            data=[
                0x7E,
                0x30,
                0x06,
                0x02,
                0x42,
                0x60,
                0x01,
                0x00,
                0x00,
                0x04,
                0x00,
                0x02,
                0x00,
            ],
        )
        inport = RecordingPort([mido.Message("clock"), reply])
        outport = RecordingPort()

        version = sq64.get_firmware_version(inport, outport)

        self.assertEqual(version, "2.04")
        self.assertEqual(
            outport.sent,
            [mido.Message("sysex", data=[0x7E, 0x7F, 0x06, 0x01])],
        )

    def test_get_firmware_version_ignores_other_devices(self):
        other_korg = mido.Message(
            "sysex",
            data=[
                0x7E, 0x30, 0x06, 0x02, 0x42,
                0x59, 0x01, 0x00, 0x00,
                0x01, 0x00, 0x01, 0x00,
            ],
        )
        sq64_reply = mido.Message(
            "sysex",
            data=[
                0x7E, 0x3F, 0x06, 0x02, 0x42,
                0x60, 0x01, 0x00, 0x00,
                0x03, 0x00, 0x02, 0x00,
            ],
        )

        version = sq64.get_firmware_version(
            RecordingPort([other_korg, sq64_reply]), RecordingPort()
        )

        self.assertEqual(version, "2.03")

    def test_get_firmware_version_rejects_truncated_sq64_reply(self):
        reply = mido.Message(
            "sysex",
            data=[
                0x7E, 0x30, 0x06, 0x02, 0x42,
                0x60, 0x01, 0x00, 0x00,
            ],
        )

        with self.assertRaisesRegex(RuntimeError, "reply length 9"):
            sq64.get_firmware_version(
                RecordingPort([reply]), RecordingPort()
            )

    @patch("sq64.time.sleep")
    @patch("sq64.time.monotonic", side_effect=[10.0, 10.0, 10.6])
    def test_get_firmware_version_times_out(self, _monotonic, sleep):
        with self.assertRaisesRegex(TimeoutError, "firmware version"):
            sq64.get_firmware_version(
                RecordingPort(), RecordingPort(), timeout=0.5
            )

        sleep.assert_called_once_with(0.001)


class SysexTests(unittest.TestCase):
    def test_sq64_sysex_builds_protocol_header_and_payload(self):
        with patch.object(sq64, "GLOBAL_CHANNEL", 4):
            message = sq64.sq64_sysex(0x18, [0x21, 0x7F])

        self.assertEqual(message.type, "sysex")
        self.assertEqual(
            list(message.data),
            [0x42, 0x34, 0x00, 0x01, 0x60, 0x18, 0x21, 0x7F],
        )

    def test_get_function_accepts_only_sq64_sysex(self):
        self.assertEqual(
            sq64.get_function(response(sq64.FUNC_ACK)),
            sq64.FUNC_ACK,
        )
        self.assertIsNone(sq64.get_function(mido.Message("clock")))
        self.assertIsNone(sq64.get_function(mido.Message("sysex", data=[1])))
        self.assertIsNone(
            sq64.get_function(
                mido.Message(
                    "sysex",
                    data=[0x41, 0x30, 0x00, 0x01, 0x60, sq64.FUNC_ACK],
                )
            )
        )

    def test_wait_for_function_ignores_unrelated_messages(self):
        port = RecordingPort(
            [
                mido.Message("clock"),
                response(sq64.FUNC_CURRENT_PROJECT_DUMP),
                response(sq64.FUNC_ACK),
            ]
        )

        message = sq64.wait_for_function(port, sq64.FUNC_ACK)

        self.assertEqual(message, response(sq64.FUNC_ACK))

    def test_wait_for_function_raises_for_device_error(self):
        port = RecordingPort([response(sq64.FUNC_FORMAT_ERROR)])

        with self.assertRaisesRegex(RuntimeError, "0x26"):
            sq64.wait_for_function(port, sq64.FUNC_ACK)

    @patch("sq64.time.sleep")
    @patch("sq64.time.monotonic", side_effect=[10.0, 10.0, 10.6])
    def test_wait_for_function_times_out(self, _monotonic, sleep):
        with self.assertRaisesRegex(TimeoutError, "0x23"):
            sq64.wait_for_function(RecordingPort(), sq64.FUNC_ACK, timeout=0.5)

        sleep.assert_called_once_with(0.001)

    @patch("sq64.wait_for_function", side_effect=TimeoutError)
    def test_wait_for_ack_adds_transfer_context(self, wait_for_function):
        with self.assertRaisesRegex(TimeoutError, "after melody pattern"):
            sq64.wait_for_ack(Mock(), "melody pattern", timeout=2.0)

        wait_for_function.assert_called_once_with(ANY, sq64.FUNC_ACK, 2.0)


class PackingTests(unittest.TestCase):
    def test_pack_7bit_extracts_high_bits(self):
        source = [0x80, 0x01, 0xFF, 0x7F, 0xA5, 0x00, 0x81]

        self.assertEqual(
            sq64.pack_7bit(source),
            [0b1010101, 0, 1, 127, 127, 37, 0, 1],
        )

    def test_pack_and_unpack_round_trip_full_and_partial_blocks(self):
        source = bytearray(range(256))
        packed = sq64.pack_7bit(source)

        self.assertTrue(all(value < 0x80 for value in packed))
        self.assertEqual(sq64.unpack_7bit(packed, len(source)), source)

    def test_unpack_respects_expected_size(self):
        packed = sq64.pack_7bit([0x80, 0x81, 0x82])

        self.assertEqual(sq64.unpack_7bit(packed, 2), bytearray([0x80, 0x81]))


class ReadTests(unittest.TestCase):
    def test_read_pattern_dump_sends_selector_and_returns_pattern(self):
        pattern = bytearray(15)
        pattern[:4] = b"PATT"
        packed = sq64.pack_7bit(pattern)
        inport = RecordingPort(
            [response(sq64.FUNC_MELODY_PATTERN_DUMP, [0x12, *packed])]
        )
        outport = RecordingPort()

        result = sq64.read_pattern_dump(
            inport,
            outport,
            sq64.FUNC_MELODY_PATTERN_REQUEST,
            sq64.FUNC_MELODY_PATTERN_DUMP,
            0x12,
            len(packed),
            len(pattern),
            b"PATT",
        )

        self.assertEqual(result, pattern)
        self.assertEqual(
            outport.sent,
            [response(sq64.FUNC_MELODY_PATTERN_REQUEST, [0x12])],
        )

    def test_read_pattern_dump_rejects_wrong_selector(self):
        inport = RecordingPort(
            [response(sq64.FUNC_MELODY_PATTERN_DUMP, [0x11])]
        )

        with self.assertRaisesRegex(RuntimeError, "selector"):
            sq64.read_pattern_dump(
                inport,
                RecordingPort(),
                sq64.FUNC_MELODY_PATTERN_REQUEST,
                sq64.FUNC_MELODY_PATTERN_DUMP,
                0x12,
                0,
                0,
                b"PATT",
            )

    def test_read_pattern_dump_rejects_size_and_signature(self):
        bad_size = RecordingPort(
            [response(sq64.FUNC_MELODY_PATTERN_DUMP, [0x00, 1])]
        )
        with self.assertRaisesRegex(RuntimeError, "Expected 2 pattern bytes"):
            sq64.read_pattern_dump(
                bad_size,
                RecordingPort(),
                0x18,
                0x48,
                0,
                2,
                1,
                b"PATT",
            )

        packed = sq64.pack_7bit(b"NOPE")
        bad_signature = RecordingPort(
            [response(sq64.FUNC_MELODY_PATTERN_DUMP, [0x00, *packed])]
        )
        with self.assertRaisesRegex(RuntimeError, "signature"):
            sq64.read_pattern_dump(
                bad_signature,
                RecordingPort(),
                0x18,
                0x48,
                0,
                len(packed),
                4,
                b"PATT",
            )

    @patch("sq64.wait_for_ack")
    @patch("sq64.read_pattern_dump")
    @patch("sq64.wait_for_function")
    def test_read_current_project_reads_present_patterns_and_finalizes(
        self, wait_for_function, read_pattern_dump, wait_for_ack
    ):
        project = bytearray(512)
        project[:4] = b"PROJ"
        project[40] = 1 << 2  # Track A, Pattern 3
        project[43] = 1 << 1  # Track B, Pattern 10
        project[46] = 1 << 4  # Track D, Pattern 5
        wait_for_function.return_value = response(
            sq64.FUNC_CURRENT_PROJECT_DUMP,
            sq64.pack_7bit(project),
        )
        melody_a = bytearray(b"PATT")
        melody_b = bytearray(b"PATT")
        rhythm = bytearray(b"PATR")
        read_pattern_dump.side_effect = [melody_a, melody_b, rhythm]
        outport = RecordingPort()

        result = sq64.read_current_project(Mock(), outport)

        self.assertEqual(
            result,
            (project, {(0, 2): melody_a, (1, 9): melody_b}, {4: rhythm}),
        )
        self.assertEqual(
            [sq64.get_function(message) for message in outport.sent],
            [sq64.FUNC_CURRENT_PROJECT_REQUEST, sq64.FUNC_FINALIZE],
        )
        self.assertEqual(
            [args.args[4] for args in read_pattern_dump.call_args_list],
            [0x02, 0x19, 0x04],
        )
        wait_for_ack.assert_called_once()

    @patch("sq64.wait_for_ack")
    @patch("sq64.wait_for_function")
    def test_read_current_project_finalizes_after_invalid_dump(
        self, wait_for_function, wait_for_ack
    ):
        wait_for_function.return_value = response(
            sq64.FUNC_CURRENT_PROJECT_DUMP, [0]
        )
        outport = RecordingPort()

        with self.assertRaisesRegex(RuntimeError, "Expected 586"):
            sq64.read_current_project(Mock(), outport)

        self.assertEqual(sq64.get_function(outport.sent[-1]), sq64.FUNC_FINALIZE)
        wait_for_ack.assert_called_once()


class PatternTests(unittest.TestCase):
    def test_decode_name_strips_trailing_spaces(self):
        data = bytearray(20)
        data[4:20] = b"A PATTERN".ljust(16, b" ")

        self.assertEqual(sq64.decode_name(data), "A PATTERN")

    def test_render_melody_steps_marks_enabled_note_events(self):
        pattern = bytearray(32 + 20 * 48)
        pattern[20] = 20
        for step in (0, 17):
            offset = 32 + step * 48
            pattern[offset + 4] = 1 << 3
            pattern[offset + 47] = 1
        # A note without an enabled step is a rest.
        pattern[32 + 1 * 48 + 4] = 1 << 3

        self.assertEqual(
            sq64.render_melody_steps(pattern),
            ["■               ", " ■  "],
        )

    def test_render_rhythm_steps_uses_selected_subtrack(self):
        pattern = bytearray(32 + 2 * 384)
        pattern[20] = 4
        pattern[32 + 384 + 2 * 6 + 3] = 1 << 7

        self.assertEqual(sq64.render_rhythm_steps(pattern, 0), ["    "])
        self.assertEqual(sq64.render_rhythm_steps(pattern, 1), ["  ■ "])

    def test_build_reference_structure_has_expected_layout(self):
        pattern = sq64.build_reference_structure()

        self.assertEqual(len(pattern), 3104)
        self.assertEqual(pattern[:4], b"PATT")
        self.assertEqual(pattern[20], 16)
        for step in range(64):
            offset = 32 + step * 48
            self.assertEqual(pattern[offset:offset + 5], bytes([48, 255, 0, 75, 0x11]))
            self.assertEqual(pattern[offset + 40], 19)

    def test_build_pattern_encodes_notes_and_rests(self):
        pattern = sq64.build_pattern()
        expected_notes = [48, 52, 55, 52, 60, 55, 52, 50]

        self.assertEqual(len(pattern), 3104)
        self.assertEqual(sq64.decode_name(pattern), "PYTHON TEST")
        self.assertEqual(sq64.render_melody_steps(pattern), ["■ ■ ■ ■ ■ ■ ■ ■ "])
        for step in range(16):
            offset = 32 + step * 48
            if step % 2 == 0:
                self.assertEqual(pattern[offset], expected_notes[step // 2])
                self.assertTrue(pattern[offset + 4] & (1 << 3))
                self.assertTrue(pattern[offset + 47] & 1)
            else:
                self.assertFalse(pattern[offset + 4] & (1 << 3))
                self.assertFalse(pattern[offset + 47] & 1)


class SendTests(unittest.TestCase):
    @patch("sq64.wait_for_ack")
    def test_send_pattern_sends_all_data_in_order_and_finalizes(self, wait_for_ack):
        project = bytearray(512)
        pattern = sq64.build_pattern()
        preserved = bytearray(3104)
        rhythm = bytearray(6176)
        outport = RecordingPort()

        sq64.send_pattern(
            Mock(),
            outport,
            project,
            pattern,
            {(1, 2): preserved},
            {3: rhythm},
        )

        self.assertEqual(
            [sq64.get_function(message) for message in outport.sent],
            [
                sq64.FUNC_CURRENT_PROJECT_DUMP,
                sq64.FUNC_MELODY_PATTERN_DUMP,
                sq64.FUNC_MELODY_PATTERN_DUMP,
                sq64.FUNC_RHYTHM_PATTERN_DUMP,
                sq64.FUNC_FINALIZE,
            ],
        )
        self.assertEqual(outport.sent[1].data[6], 0x00)
        self.assertEqual(outport.sent[2].data[6], 0x12)
        self.assertEqual(outport.sent[3].data[6], 0x03)
        self.assertEqual(
            [args.args[1] for args in wait_for_ack.call_args_list],
            [
                "current project header",
                "Track A / Pattern 1",
                "Track B / Pattern 3",
                "Track D / Pattern 4",
                "project finalize",
            ],
        )

    @patch("sq64.wait_for_ack")
    def test_send_pattern_finalizes_after_transfer_error(self, wait_for_ack):
        wait_for_ack.side_effect = [TimeoutError("failed"), None]
        outport = RecordingPort()

        with self.assertRaises(TimeoutError):
            sq64.send_pattern(
                Mock(),
                outport,
                bytearray(512),
                sq64.build_pattern(),
                {},
                {},
            )

        self.assertEqual(
            [sq64.get_function(message) for message in outport.sent],
            [sq64.FUNC_CURRENT_PROJECT_DUMP, sq64.FUNC_FINALIZE],
        )

    def test_send_pattern_rejects_invalid_data_before_sending(self):
        outport = RecordingPort()

        with self.assertRaisesRegex(RuntimeError, "project size"):
            sq64.send_pattern(
                Mock(), outport, bytearray(511), sq64.build_pattern(), {}, {}
            )

        self.assertEqual(outport.sent, [])


if __name__ == "__main__":
    unittest.main()

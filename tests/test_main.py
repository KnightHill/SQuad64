import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import main


class ArgumentTests(unittest.TestCase):
    def test_track_and_pattern_filters(self):
        with patch.object(
            sys,
            "argv",
            ["main.py", "-t", "b", "-p", "3"],
        ):
            args = main.parse_args()

        self.assertEqual(args.track, "B")
        self.assertEqual(args.pattern, 3)
        self.assertFalse(args.update)
        self.assertFalse(args.show_global)
        self.assertFalse(args.verbose)

    def test_filters_are_optional(self):
        with patch.object(sys, "argv", ["main.py"]):
            args = main.parse_args()

        self.assertIsNone(args.track)
        self.assertIsNone(args.pattern)

    def test_verbose_option(self):
        with patch.object(sys, "argv", ["main.py", "--verbose"]):
            args = main.parse_args()

        self.assertTrue(args.verbose)

    def test_global_option_has_short_and_long_forms(self):
        for option in ("-g", "--global"):
            with self.subTest(option=option):
                with patch.object(sys, "argv", ["main.py", option]):
                    args = main.parse_args()

                self.assertTrue(args.show_global)
                self.assertFalse(args.update)

    def test_global_and_update_are_mutually_exclusive(self):
        with patch.object(
            sys,
            "argv",
            ["main.py", "--global", "--update"],
        ):
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main.parse_args()

    def test_version_uses_project_name(self):
        output = io.StringIO()

        with patch.object(sys, "argv", ["main.py", "--version"]):
            with redirect_stdout(output):
                with self.assertRaises(SystemExit) as exit_result:
                    main.parse_args()

        self.assertEqual(exit_result.exception.code, 0)
        self.assertEqual(output.getvalue(), "squad64 0.2.3\n")

    def test_pattern_must_be_between_one_and_sixteen(self):
        for value in ("0", "17", "not-a-number"):
            with self.subTest(value=value):
                with patch.object(
                    sys,
                    "argv",
                    ["main.py", "--pattern", value],
                ):
                    with redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit):
                            main.parse_args()


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        self.args = main.argparse.Namespace(
            update=False,
            show_global=False,
            verbose=False,
            track=None,
            pattern=None,
        )

    @patch("main.sq64.find_sq64_ports")
    @patch("main.parse_args")
    def test_missing_midi_ports_prints_error_without_traceback(
        self, parse_args, find_ports
    ):
        parse_args.return_value = self.args
        find_ports.side_effect = RuntimeError(
            "No SQ-64 MIDI input port found"
        )
        errors = io.StringIO()

        with redirect_stderr(errors):
            status = main.main()

        self.assertEqual(status, 1)
        find_ports.assert_called_once_with(verbose=False)
        self.assertEqual(
            errors.getvalue(),
            "Error: No SQ-64 MIDI input port found\n",
        )
        self.assertNotIn("Traceback", errors.getvalue())

    @patch("main.mido.open_input", side_effect=OSError("MIDI unavailable"))
    @patch("main.sq64.find_sq64_ports", return_value=("input", "output"))
    @patch("main.parse_args")
    def test_midi_backend_errors_are_user_facing(
        self, parse_args, _find_ports, _open_input
    ):
        parse_args.return_value = self.args
        errors = io.StringIO()

        with redirect_stdout(io.StringIO()):
            with redirect_stderr(errors):
                status = main.main()

        self.assertEqual(status, 1)
        self.assertEqual(errors.getvalue(), "Error: MIDI unavailable\n")

    @patch("main.sq64.find_sq64_ports", side_effect=KeyboardInterrupt)
    @patch("main.parse_args")
    def test_keyboard_interrupt_is_clean(self, parse_args, _find_ports):
        parse_args.return_value = self.args
        errors = io.StringIO()

        with redirect_stderr(errors):
            status = main.main()

        self.assertEqual(status, 130)
        self.assertEqual(errors.getvalue(), "\nCancelled.\n")

    @patch("main.sq64.find_sq64_ports", side_effect=ValueError("bug"))
    @patch("main.parse_args")
    def test_unexpected_errors_are_not_hidden(self, parse_args, _find_ports):
        parse_args.return_value = self.args

        with self.assertRaisesRegex(ValueError, "bug"):
            main.main()


class RunTests(unittest.TestCase):
    @patch("main.sq64.print_global_data")
    @patch("main.SQ64Client")
    @patch("main.mido.open_output")
    @patch("main.mido.open_input")
    @patch("main.sq64.find_sq64_ports", return_value=("input", "output"))
    def test_global_mode_prints_firmware_and_global_data_then_exits(
        self,
        _find_ports,
        open_input,
        open_output,
        client_class,
        print_global_data,
    ):
        inport = Mock()
        outport = Mock()
        open_input.return_value.__enter__.return_value = inport
        open_output.return_value.__enter__.return_value = outport
        client = client_class.return_value
        client.get_firmware_version.return_value = "2.04"
        global_data = bytearray(b"GLOB")
        client.read_global_data.return_value = global_data
        args = main.argparse.Namespace(
            update=False,
            show_global=True,
            verbose=False,
            track=None,
            pattern=None,
        )
        output = io.StringIO()

        with redirect_stdout(output):
            main.run(args)

        self.assertIn("Firmware version: 2.04", output.getvalue())
        client.get_firmware_version.assert_called_once_with()
        client.read_global_data.assert_called_once_with()
        print_global_data.assert_called_once_with(global_data)
        client.read_current_project.assert_not_called()
        client.send_pattern.assert_not_called()


if __name__ == "__main__":
    unittest.main()

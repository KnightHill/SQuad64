import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import dump
import edit


class DumpArgumentTests(unittest.TestCase):
    def test_filters_are_optional_and_normalized(self):
        with patch.object(
            sys,
            "argv",
            ["squad64-dump", "-t", "b", "-p", "3"],
        ):
            args = dump.parse_args()

        self.assertEqual(args.track, "B")
        self.assertEqual(args.pattern, 3)
        self.assertFalse(args.show_global)
        self.assertFalse(args.verbose)

    def test_global_option_has_short_and_long_forms(self):
        for option in ("-g", "--global"):
            with self.subTest(option=option):
                with patch.object(sys, "argv", ["squad64-dump", option]):
                    args = dump.parse_args()

                self.assertTrue(args.show_global)

    def test_version_uses_dump_name(self):
        output = io.StringIO()

        with patch.object(sys, "argv", ["squad64-dump", "--version"]):
            with redirect_stdout(output):
                with self.assertRaises(SystemExit) as exit_result:
                    dump.parse_args()

        self.assertEqual(exit_result.exception.code, 0)
        self.assertEqual(output.getvalue(), "squad64-dump 0.3.1\n")


class EditArgumentTests(unittest.TestCase):
    def test_track_and_pattern_are_required(self):
        with patch.object(
            sys,
            "argv",
            ["squad64-edit", "-t", "c", "-p", "16"],
        ):
            args = edit.parse_args()

        self.assertEqual(args.track, "C")
        self.assertEqual(args.pattern, 16)
        self.assertFalse(args.verbose)

    def test_track_is_limited_to_a_through_c(self):
        with patch.object(
            sys,
            "argv",
            ["squad64-edit", "-t", "D", "-p", "1"],
        ):
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    edit.parse_args()

    def test_track_and_pattern_cannot_be_omitted(self):
        for arguments in (("-p", "1"), ("-t", "A")):
            with self.subTest(arguments=arguments):
                with patch.object(
                    sys,
                    "argv",
                    ["squad64-edit", *arguments],
                ):
                    with redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit):
                            edit.parse_args()

    def test_global_option_is_not_available(self):
        with patch.object(
            sys,
            "argv",
            ["squad64-edit", "--global", "-t", "A", "-p", "1"],
        ):
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    edit.parse_args()

    def test_version_uses_edit_name(self):
        output = io.StringIO()

        with patch.object(sys, "argv", ["squad64-edit", "--version"]):
            with redirect_stdout(output):
                with self.assertRaises(SystemExit) as exit_result:
                    edit.parse_args()

        self.assertEqual(exit_result.exception.code, 0)
        self.assertEqual(output.getvalue(), "squad64-edit 0.3.1\n")


class EditPatternTests(unittest.TestCase):
    def test_empty_pattern_steps_are_rests_with_default_velocity(self):
        steps = edit.pattern_steps(edit.sq64.build_empty_pattern())

        self.assertEqual(steps, [(None, 255)] * 16)

    def test_velocity_display_matches_sq64_half_step_scale(self):
        self.assertEqual(edit.velocity_text(1), "0")
        self.assertEqual(edit.velocity_text(100), "49.5")
        self.assertEqual(edit.velocity_text(255), "127")

    def test_chord_and_arp_patterns_are_rejected(self):
        for mode in (1, 2):
            with self.subTest(mode=mode):
                pattern = edit.sq64.build_pattern([60])
                pattern[23] = mode

                with self.assertRaisesRegex(RuntimeError, "MONO"):
                    edit.pattern_steps(pattern)

    def test_hidden_additional_note_events_are_rejected(self):
        pattern = edit.sq64.build_pattern([60])
        pattern[32 + 5 + 4] |= 1 << 3

        with self.assertRaisesRegex(RuntimeError, "additional note events"):
            edit.pattern_steps(pattern)

        with self.assertRaisesRegex(RuntimeError, "additional note events"):
            edit.apply_steps(pattern, [(60, 255)])


if __name__ == "__main__":
    unittest.main()

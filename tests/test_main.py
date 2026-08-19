import io
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

import main


class ArgumentTests(unittest.TestCase):
    def test_track_and_pattern_filters(self):
        with patch.object(
            sys,
            "argv",
            ["main.py", "--track", "b", "--pattern", "3"],
        ):
            args = main.parse_args()

        self.assertEqual(args.track, "B")
        self.assertEqual(args.pattern, 3)
        self.assertFalse(args.update)

    def test_filters_are_optional(self):
        with patch.object(sys, "argv", ["main.py"]):
            args = main.parse_args()

        self.assertIsNone(args.track)
        self.assertIsNone(args.pattern)

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


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

import file_io


class FileIOTests(unittest.TestCase):
    def test_load_file_parses_notes_rests_commas_and_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pattern.pat"
            path.write_text(
                "48, None, 52 - 55 rest  # intro\n60\n",
                encoding="utf-8",
            )

            self.assertEqual(
                file_io.load_file(path),
                [48, None, 52, None, 55, None, 60],
            )

    def test_save_file_round_trips(self):
        notes = [48, None, 52, None, 55, None, 60]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pattern.pat"
            file_io.save_file(path, notes)

            self.assertEqual(path.read_text(encoding="utf-8"), "48\nNone\n52\nNone\n55\nNone\n60\n")
            self.assertEqual(file_io.load_file(path), notes)

    def test_pattern_file_round_trips_velocities(self):
        steps = [(48, 201), (None, 1), (60, 255), (64, 161)]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pattern.pat"
            file_io.save_pattern(path, steps)

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "48 100\nNone 0\n60 127\n64 80\n",
            )
            self.assertEqual(file_io.load_pattern(path), steps)

    def test_pattern_file_defaults_legacy_velocity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pattern.pat"
            path.write_text("48\nNone\n52\n55\n", encoding="utf-8")

            self.assertEqual(
                file_io.load_pattern(path),
                [(48, 255), (None, 255), (52, 255), (55, 255)],
            )

    def test_length_must_be_between_four_and_sixty_four(self):
        for notes in ([48, None, 52], list(range(65))):
            with self.subTest(length=len(notes)):
                with self.assertRaises(ValueError):
                    file_io.save_file("unused.pat", notes)

    def test_notes_must_be_valid_midi_values_or_rests(self):
        for notes in ([128, None, 52, 55], [-1, 52, 55, 60], ["48", 52, 55, 60]):
            with self.subTest(notes=notes):
                with self.assertRaises(ValueError):
                    file_io.save_file("unused.pat", notes)

    def test_load_file_rejects_invalid_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pattern.pat"
            path.write_text("48, bananas, 52, 55\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "line 1"):
                file_io.load_file(path)

    def test_load_file_rejects_notes_outside_midi_range(self):
        for value in ("128", "-1"):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "pattern.pat"
                    path.write_text(
                        f"{value}, 52, 55, 60\n",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(ValueError, "MIDI note"):
                        file_io.load_file(path)


if __name__ == "__main__":
    unittest.main()

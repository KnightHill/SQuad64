import unittest

from squad64 import protocol
from squad64.output import melody_pattern_as_strudel


class StrudelOutputTests(unittest.TestCase):
    def test_formats_notes_rests_and_tempo(self):
        pattern = protocol.build_pattern([60, None, 64, 67])

        self.assertEqual(
            melody_pattern_as_strudel(pattern, 123.5),
            'setcpm(123.5/4)\n'
            'note("<60 ~ 64 67>*16")\n'
            '.sound("supersaw")',
        )

    def test_formats_multiple_notes_in_one_step_as_a_chord(self):
        pattern = protocol.build_pattern([60])
        step_offset = 32
        pattern[step_offset + 5] = 64
        pattern[step_offset + 5 + 4] |= 1 << 3
        pattern[step_offset + 10] = 67
        pattern[step_offset + 10 + 4] |= 1 << 3

        self.assertIn(
            'note("<[60,64,67]>*16")',
            melody_pattern_as_strudel(pattern, 120),
        )

    def test_treats_enabled_step_without_notes_as_a_rest(self):
        pattern = protocol.build_pattern([60])
        pattern[32 + 4] &= ~(1 << 3)

        self.assertIn(
            'note("<~>*16")',
            melody_pattern_as_strudel(pattern, 120),
        )


if __name__ == "__main__":
    unittest.main()

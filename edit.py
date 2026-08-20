#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from typing import Callable, Optional

import mido
from blessed import Terminal

import file_io as io
import sq64
from sq64_client import SQ64Client
from version import __version__

PAGE_SIZE = 16
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
NOTE_PATTERN = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")


def pattern_number(value):
    """Parse a user-facing SQ-64 pattern number."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("pattern must be an integer") from error
    if not 1 <= number <= 16:
        raise argparse.ArgumentTypeError("pattern must be between 1 and 16")
    return number


def note_name(note: Optional[int]) -> str:
    """Return a compact scientific-pitch name, or blank for a rest."""
    if note is None:
        return ""
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


def parse_note(value: str) -> Optional[int]:
    """Parse C4, F#3, Bb2, or - into a MIDI note/rest."""
    value = value.strip()
    if value in ("", "-"):
        return None
    match = NOTE_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("note must look like C4, F#3, Bb2, or -")
    letter, accidental, octave_text = match.groups()
    semitones = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    value = semitones[letter.upper()] + (int(octave_text) + 1) * 12
    if accidental == "#":
        value += 1
    elif accidental == "b":
        value -= 1
    if not 0 <= value <= 127:
        raise ValueError("note is outside the MIDI range 0-127")
    return value


def pattern_steps(pattern: sq64.ByteData) -> list[io.PatternStep]:
    """Extract editable notes and clamped velocities from a SQ-64 pattern."""
    steps = []
    for step_number in range(pattern[20]):
        offset = 32 + step_number * 48
        enabled = bool(pattern[offset + 4] & (1 << 3)) and bool(
            pattern[offset + 47] & 1
        )
        note = pattern[offset] if enabled else None
        steps.append((note, min(pattern[offset + 1], 127)))
    return steps


def apply_steps(
    pattern: sq64.ByteData, steps: list[io.PatternStep]
) -> bytearray:
    """Apply editable note/velocity values to a retrieved pattern."""
    if len(steps) != pattern[20]:
        raise ValueError("edited pattern length does not match retrieved pattern")
    result = bytearray(pattern)
    for step_number, (note, velocity) in enumerate(steps):
        offset = 32 + step_number * 48
        result[offset + 1] = velocity
        if note is None:
            result[offset + 4] &= ~(1 << 3)
            result[offset + 47] &= ~1
        else:
            result[offset] = note
            result[offset + 4] |= 1 << 3
            result[offset + 47] |= 1
    return result


def parse_args():
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        prog="squad64-edit",
        description="Edit one melodic SQ-64 pattern in a one-page terminal UI.",
    )
    parser.add_argument("-u", "--update", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true", help="list MIDI ports")
    parser.add_argument("-t", "--track", type=str.upper, choices=("A", "B", "C"), required=True)
    parser.add_argument("-p", "--pattern", type=pattern_number, metavar="1-16", required=True)
    parser.add_argument("-o", "--output", default="retrieved.pat", help="local pattern file")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args()


class PatternEditor:
    """Blessed one-page editor for one melodic pattern."""

    def __init__(
        self,
        term: Terminal,
        steps: list[io.PatternStep],
        output: str,
        *,
        is_new: bool = False,
        on_send: Optional[Callable[[], None]] = None,
    ):
        self.term = term
        self.steps = steps
        self.output = output
        self.cursor = 0
        self.page = 0
        self.message = ""
        self.is_new = is_new
        self.on_send = on_send
        self.clipboard: Optional[io.PatternStep] = None

    @property
    def page_count(self) -> int:
        return max(1, (len(self.steps) + PAGE_SIZE - 1) // PAGE_SIZE)

    def draw(self) -> None:
        term = self.term
        start = self.page * PAGE_SIZE
        visible = self.steps[start:start + PAGE_SIZE]
        print(term.clear + term.home, end="")
        print(term.bold("SQuad64 Editor"), end="")
        if self.is_new:
            print(term.bold_yellow("  EMPTY / NEW PATTERN"), end="")
        print(
            f"  length {len(self.steps)} steps  "
            f"visible {start + 1}-{start + len(visible)}  "
            f"page {self.page + 1}/{self.page_count}"
        )
        print(
            f"{'Step':>6} "
            + "  ".join(
                f"{number:^5}"
                for number in range(start + 1, start + len(visible) + 1)
            )
        )
        self._draw_row(
            "Note",
            [note_name(note) for note, _velocity in visible],
            start,
        )
        self._draw_row(
            "Vel.",
            [str(velocity) if note is not None else "" for note, velocity in visible],
            start,
        )
        print()
        print("  [←/→] step  [PgUp/PgDn] page  [n] note  [r] rest  [c] copy  [p] paste")
        print("  [↑/↓] velocity  [S] save  [W] send  [q/Esc] quit")
        if self.message:
            print(f"\n  {self.message}")

    def _draw_row(
        self, label: str, values: list[str], start: int
    ) -> None:
        rendered = []
        for index, value in enumerate(values):
            selected = start + index == self.cursor
            text = f"{value:^5}" if value else "     "
            rendered.append(self.term.reverse(text) if selected else text)
        print(f"{label:>6} " + "  ".join(rendered))

    def edit_note(self) -> None:
        buffer = ""
        while True:
            self.message = f"Note for step {self.cursor + 1}: {buffer or '_'}"
            self.draw()
            key = self.term.inkey()
            if key.name == "ESCAPE":
                self.message = ""
                return
            if key.name in ("ENTER", "KEY_ENTER"):
                try:
                    self.steps[self.cursor] = (parse_note(buffer), self.steps[self.cursor][1])
                except ValueError as error:
                    self.message = str(error)
                    continue
                self.message = ""
                return
            if key.name in ("KEY_BACKSPACE", "BACKSPACE") or str(key) == "\x7f":
                buffer = buffer[:-1]
            elif str(key).isprintable() and len(buffer) < 5:
                buffer += str(key)

    def save(self) -> None:
        if self.is_empty:
            self.message = "Cannot save an empty pattern; enter at least one note."
            return
        io.save_pattern(self.output, self.steps)
        self.message = f"Saved {self.output}"

    @property
    def is_empty(self) -> bool:
        return not any(note is not None for note, _velocity in self.steps)

    def run(self) -> str:
        with (
            self.term.fullscreen(),
            self.term.cbreak(),
            self.term.hidden_cursor(),
        ):
            while True:
                self.draw()
                key = self.term.inkey()
                if key.name == "ESCAPE" or str(key).lower() == "q":
                    return "quit"
                if str(key) == "S":
                    self.save()
                elif str(key) == "W":
                    if self.is_empty:
                        self.message = "Cannot send an empty pattern; enter at least one note."
                        continue
                    if self.on_send is None:
                        self.message = "Send is unavailable."
                    else:
                        self.on_send()
                        self.message = "Pattern sent to the SQ-64."
                elif key.name == "KEY_RIGHT" or str(key) == "l":
                    self.cursor = min(self.cursor + 1, len(self.steps) - 1)
                    self.page = self.cursor // PAGE_SIZE
                elif key.name == "KEY_LEFT" or str(key) == "h":
                    self.cursor = max(self.cursor - 1, 0)
                    self.page = self.cursor // PAGE_SIZE
                elif key.name in (
                    "KEY_PGDN",
                    "KEY_PGDOWN",
                    "KEY_NPAGE",
                    "KEY_KP_PAGE_DOWN",
                    "NPage",
                    "PAGEDOWN",
                    "PAGE_DOWN",
                ) or str(key) in ("]", "\x06"):
                    self.page = min(self.page + 1, self.page_count - 1)
                    self.cursor = min(self.page * PAGE_SIZE, len(self.steps) - 1)
                elif key.name in (
                    "KEY_PGUP",
                    "KEY_PPAGE",
                    "KEY_KP_PAGE_UP",
                    "PPage",
                    "PAGEUP",
                    "PAGE_UP",
                ) or str(key) in ("[", "\x02"):
                    self.page = max(self.page - 1, 0)
                    self.cursor = self.page * PAGE_SIZE
                elif str(key).lower() == "n":
                    self.edit_note()
                elif str(key).lower() == "r":
                    self.steps[self.cursor] = (None, self.steps[self.cursor][1])
                elif str(key).lower() == "c":
                    self.clipboard = self.steps[self.cursor]
                    self.message = f"Copied step {self.cursor + 1}."
                elif str(key).lower() == "p":
                    if self.clipboard is None:
                        self.message = "Nothing to paste."
                    else:
                        self.steps[self.cursor] = self.clipboard
                        self.message = f"Pasted to step {self.cursor + 1}."
                elif key.name == "KEY_UP" or str(key) == "+":
                    note, velocity = self.steps[self.cursor]
                    self.steps[self.cursor] = (note, min(127, velocity + 1))
                elif key.name == "KEY_DOWN" or str(key) == "-":
                    note, velocity = self.steps[self.cursor]
                    self.steps[self.cursor] = (note, max(0, velocity - 1))
        return "quit"


def run(args):
    """Read, edit, and optionally send one SQ-64 pattern."""
    input_name, output_name = sq64.find_sq64_ports(verbose=args.verbose)
    track = ord(args.track) - ord("A")
    pattern_number = args.pattern - 1
    with mido.open_input(input_name) as inp, mido.open_output(output_name) as out:
        client = SQ64Client(inp, out)
        print("Reading current project and existing patterns...")
        project, melody_patterns, rhythm_patterns = client.read_current_project()
        key = (track, pattern_number)
        is_new = key not in melody_patterns
        original = melody_patterns.get(key)
        if original is None:
            original = sq64.build_empty_pattern()
        def send_edited_pattern() -> None:
            updated = apply_steps(original, editor.steps)
            client.send_pattern(
                project,
                updated,
                melody_patterns,
                rhythm_patterns,
                target_track=track,
                target_pattern=pattern_number,
            )

        editor = PatternEditor(
            Terminal(),
            pattern_steps(original),
            args.output,
            is_new=is_new,
        )
        editor.on_send = send_edited_pattern
        editor.run()


def main():
    """Run the editor with concise operational errors."""
    args = parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error or type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

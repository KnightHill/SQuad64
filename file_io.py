"""Read and write editable SQ-64 note lists."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional


PatternStep = tuple[Optional[int], int]


MIN_NOTES = 4
MAX_NOTES = 64
MIN_MIDI_NOTE = 0
MAX_MIDI_NOTE = 127
REST_TOKENS = frozenset(("-", "none", "rest"))


def _validate_notes(notes: list[Optional[int]]) -> None:
    if not MIN_NOTES <= len(notes) <= MAX_NOTES:
        raise ValueError(
            f"pattern must contain between {MIN_NOTES} and {MAX_NOTES} "
            f"notes/rests, got {len(notes)}"
        )

    for position, note in enumerate(notes, start=1):
        if note is None:
            continue
        if isinstance(note, bool) or not isinstance(note, int):
            raise ValueError(
                f"item {position} must be a MIDI note number or rest, got "
                f"{note!r}"
            )
        if not MIN_MIDI_NOTE <= note <= MAX_MIDI_NOTE:
            raise ValueError(
                f"item {position} must be a MIDI note number from "
                f"{MIN_MIDI_NOTE} to {MAX_MIDI_NOTE}, got {note}"
            )


def load_file(filename: str | os.PathLike[str]) -> list[Optional[int]]:
    """Load and validate a note/rest list from a text file.

    Tokens may be separated by whitespace or commas. MIDI note numbers are
    integers from 0 through 127. ``None``, ``rest``, and ``-`` represent a
    rest. Text after ``#`` on a line is ignored.
    """
    path = Path(filename)
    values: list[Optional[int]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        content = line.split("#", 1)[0]
        for token in re.split(r"[\s,]+", content.strip()):
            if not token:
                continue
            if token.lower() in REST_TOKENS:
                values.append(None)
                continue
            try:
                values.append(int(token, 10))
            except ValueError as error:
                raise ValueError(
                    f"line {line_number}: invalid note/rest {token!r}"
                ) from error
    _validate_notes(values)
    return values


def load_pattern(filename: str | os.PathLike[str]) -> list[PatternStep]:
    """Load note/rest and velocity pairs from a pattern file.

    Each line may contain a note/rest followed by an optional velocity. The
    velocity defaults to 255 so existing note-only files remain valid. File
    velocities use the SQ-64 display scale from 0 through 127.5 in 0.5 steps.
    """
    path = Path(filename)
    steps: list[PatternStep] = []

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        content = line.split("#", 1)[0].strip()
        if not content:
            continue
        tokens = [token for token in re.split(r"[\s,]+", content) if token]
        pairs = [tokens] if len(tokens) == 2 else [[token] for token in tokens]
        for pair in pairs:
            token = pair[0]
            if token.lower() in REST_TOKENS:
                note = None
            else:
                try:
                    note = int(token, 10)
                except ValueError as error:
                    raise ValueError(
                        f"line {line_number}: invalid note/rest {token!r}"
                    ) from error

            velocity = 255
            if len(pair) == 2:
                try:
                    display_velocity = float(pair[1])
                except ValueError as error:
                    raise ValueError(
                        f"line {line_number}: invalid velocity {pair[1]!r}"
                    ) from error
                if display_velocity < 0 or display_velocity > 127.5:
                    raise ValueError(
                        f"line {line_number}: velocity must be from 0 to 127.5"
                    )
                raw_velocity = round(display_velocity * 2)
                if display_velocity != raw_velocity / 2:
                    raise ValueError(
                        f"line {line_number}: velocity must use 0.5 steps"
                    )
                velocity = raw_velocity
            if not 0 <= velocity <= 255:
                raise ValueError(
                    f"line {line_number}: velocity must be from 0 to 127.5"
                )
            steps.append((note, velocity))

    _validate_notes([note for note, _velocity in steps])
    return steps


def save_file(
    filename: str | os.PathLike[str], notes: list[Optional[int]]
) -> None:
    """Validate and save a note/rest list as one token per line."""
    _validate_notes(notes)
    path = Path(filename)
    path.write_text(
        "".join("None\n" if note is None else f"{note}\n" for note in notes),
        encoding="utf-8",
    )


def save_pattern(
    filename: str | os.PathLike[str], steps: list[PatternStep]
) -> None:
    """Save note/rest and velocity pairs, one step per line."""
    _validate_notes([note for note, _velocity in steps])
    for position, (_note, velocity) in enumerate(steps, start=1):
        if not isinstance(velocity, int) or not 0 <= velocity <= 255:
            raise ValueError(
                f"item {position} raw velocity must be from 0 to 255, got "
                f"{velocity!r}"
            )
    path = Path(filename)
    path.write_text(
        "".join(
            f"{'None' if note is None else note} "
            f"{velocity / 2:g}\n"
            for note, velocity in steps
        ),
        encoding="utf-8",
    )

"""Read and write editable SQ-64 note lists."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional


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
                note = int(token, 10)
            except ValueError as error:
                raise ValueError(
                    f"line {line_number}: invalid note/rest {token!r}"
                ) from error
            values.append(note)

    _validate_notes(values)
    return values


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

"""Alternative output formats for SQ-64 pattern data."""

from __future__ import annotations

from .protocol import ByteData


def melody_pattern_as_strudel(pattern: ByteData, bpm: float) -> str:
    """Return one melodic SQ-64 pattern as pasteable Strudel code."""
    tokens: list[str] = []

    for step_number in range(pattern[20]):
        step_offset = 32 + step_number * 48
        if not pattern[step_offset + 47] & 1:
            tokens.append("~")
            continue

        notes = [
            str(pattern[step_offset + note_number * 5])
            for note_number in range(8)
            if pattern[step_offset + note_number * 5 + 4] & (1 << 3)
        ]
        if not notes:
            tokens.append("~")
        elif len(notes) == 1:
            tokens.append(notes[0])
        else:
            tokens.append(f"[{','.join(notes)}]")

    notation = " ".join(tokens)
    return (
        f"setcpm({bpm:g}/4)\n"
        f'note("<{notation}>*16")\n'
        '.sound("supersaw")'
    )

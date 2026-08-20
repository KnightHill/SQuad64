# SQuad64

SQuad64 is a Python utility for inspecting and editing projects on the Korg
SQ-64. It communicates with the sequencer over MIDI SysEx.

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Korg Inc. in
any way. It is experimental software provided as-is and used entirely at your
own risk. Back up important SQ-64 projects before using development features.

## Applications

The repository contains two command-line applications:

- `squad64-dump` (`dump.py`) reads and displays the current SQ-64 project. It
  is read-only and cannot update the device.
- `squad64-edit` (`edit.py`) is the developing pattern editor. It currently
  reads a selected melodic track and pattern; editing behavior is still under
  development.

The applications share their version in [`version.py`](version.py).

## Edit buffer and saved projects

The SQ-64 keeps the project currently being edited in a temporary **edit
buffer**. This buffer contains the active project settings and its melodic and
rhythm patterns. The SQ-64 also has 64 **saved project slots** in internal
memory. Those stored slots are separate from the active edit buffer.

The tools use the Current Project SysEx messages (`0x11` and `0x41`). They do
not write a saved project slot with the ROM Project message (`0x4D`). Reloading
a saved project or restarting the SQ-64 may discard edit-buffer changes.

## Requirements

- Korg SQ-64 running system version 2.x
- Python 3
- A working MIDI connection to the SQ-64
- [`mido`](https://mido.readthedocs.io/)
- [`python-rtmidi`](https://pypi.org/project/python-rtmidi/)
- [`blessed`](https://pypi.org/project/blessed/)

Install the Python dependencies in a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install mido python-rtmidi
.venv/bin/python -m pip install blessed
```

## Usage

Connect and power on the SQ-64, then dump the current project:

```bash
./dump.py
```

Display the dump application's version:

```bash
./dump.py --version
```

Display firmware and global settings without downloading the current project:

```bash
./dump.py --global
```

Filter the displayed project by track, pattern number, or both:

```bash
./dump.py --track B
./dump.py --pattern 3
./dump.py --track D --pattern 8
```

Dump tracks are `A` through `D`, and pattern numbers are `1` through `16`.
Filters affect only the printed output; the complete project is still read
from the SQ-64.

To use the editor, provide both a melodic track and a pattern:

```bash
./edit.py --track A --pattern 1
```

The editor accepts tracks `A` through `C` and pattern numbers `1` through
`16`. It displays one editable page of up to 16 steps at a time. Use the
arrow keys to move, `n` to enter a note such as `C4` or `F#3`, `r` for a rest,
and the up/down arrows to adjust velocity. Use `S` to save and `W` to send
the selected pattern to the SQ-64. Empty patterns cannot be saved or sent;
enter at least one note first. Use `--verbose` with either application to list
available MIDI ports while connecting.

Velocities are displayed on the SQ-64 half-step scale from `0` to `127`;
values may include `.5` (for example, `49.5`), and the up/down arrows change
velocity by `0.5`.

If the selected melodic pattern does not exist on the SQ-64, the editor opens
an `EMPTY / NEW PATTERN` editor with 16 rest steps. Saving writes the new
pattern locally; sending creates it at the selected track and pattern.

## Pattern files

[`file_io.py`](file_io.py) provides `load_file(filename)` and
`save_file(filename, notes)` for legacy note-only files, plus
`load_pattern(filename)` and `save_pattern(filename, steps)` for note/rest and
velocity pairs. A pattern must contain between 4 and 64 entries. Notes are
MIDI numbers from `0` through `127`; a rest can be written as `None`, `rest`,
or `-`. Pattern-file velocities use the same `0` through `127` half-step
scale. Entries may be separated by spaces or commas, and `#` starts a comment.

For example:

```text
48, None, 52, None
55, rest, 60, -
```

## MIDI configuration

The SQ-64 global MIDI channel is currently set by `GLOBAL_CHANNEL` in
[`sq64.py`](sq64.py). Its value is zero-based: `0` means MIDI channel 1 and
`15` means MIDI channel 16.

On the SQ-64 ALSA USB interface the program prefers `MIDI OUT 2` for device
responses and the `SEQ` endpoint for data sent to the sequencer.

## Official Korg documentation

The implementation follows Korg's official SQ-64 MIDI Implementation,
Revision 1.00 (2023-01-24), published for the version 2.x firmware generation:

- [SQ-64 product page](https://www.korg.com/us/products/dj/sq_64/)
- [SQ-64 owner's manual](https://www.korg.com/us/support/download/manual/0/872/4676/)
- [System version 2.0 owner's manual](https://www.korg.com/us/support/download/manual/0/872/4926/)
- [Detailed SQ-64 MIDI Implementation](https://www.korg.com/us/support/download/manual/0/872/5143/)
- [MIDI Implementation Chart](https://www.korg.com/us/support/download/manual/0/872/4947/)
- [All SQ-64 support downloads](https://www.korg.com/us/support/download/product/0/872/)

The relevant SysEx functions are:

| Function | ID |
| --- | ---: |
| Current project dump request | `0x11` |
| Melody pattern dump request | `0x18` |
| Rhythm pattern dump request | `0x19` |
| Current project dump | `0x41` |
| Melody pattern dump | `0x48` |
| Rhythm pattern dump | `0x49` |
| Project dump finalize | `0x70` |
| Acknowledgement | `0x23` |

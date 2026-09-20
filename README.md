# SQuad64

SQuad64 is a Python utility for inspecting and editing projects on the Korg
SQ-64. It communicates with the sequencer over MIDI SysEx.

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Korg Inc. in
any way. It is experimental software provided as-is and used entirely at your
own risk. Back up important SQ-64 projects before using development features.

## Applications

The repository contains two command-line applications:

- `squad64-dump` reads and displays the current SQ-64 project. It
  is read-only and cannot update the device.
- `squad64-edit` reads, edits, and sends one selected melodic pattern.

Both applications are installed from the `squad64` Python package. The current
application version is `0.4.0`.

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
- Python 3.10 or newer
- A working MIDI connection to the SQ-64
- [`mido`](https://mido.readthedocs.io/)
- [`python-rtmidi`](https://pypi.org/project/python-rtmidi/)
- [`blessed`](https://pypi.org/project/blessed/)

Install the project and its command-line applications in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Activating the environment places `squad64-dump` and `squad64-edit` on the
current shell's command path. Verify the installation with:

```bash
squad64-dump --version
squad64-edit --version
```

The installed commands are named `squad64-dump` and `squad64-edit`, not
`dump` and `edit`. If the virtual environment is not activated, invoke them by
their complete paths instead:

```bash
.venv/bin/squad64-dump --version
.venv/bin/squad64-edit --version
```

## Usage

Connect and power on the SQ-64, then dump the current project:

```bash
squad64-dump
```

Display the dump application's version:

```bash
squad64-dump --version
```

Display firmware and global settings without downloading the current project:

```bash
squad64-dump --global
```

Filter the displayed project by track, pattern number, or both:

```bash
squad64-dump --track B
squad64-dump --pattern 3
squad64-dump --track D --pattern 8
```

Dump tracks are `A` through `D`, and pattern numbers are `1` through `16`.
Filters affect only the printed output; the complete project is still read
from the SQ-64.

Export one melodic pattern as code for the
[Strudel web editor](https://strudel.cc/) by specifying its track and pattern:

```bash
squad64-dump -strudel --track A --pattern 1
```

`--strudel` is also accepted. Strudel export supports melodic tracks `A`
through `C`; Track `D` is not supported. The generated code uses the project
tempo, MIDI note numbers, `~` for rests, and bracketed comma-separated notes
for chords. For example:

```javascript
setcpm(120/4)
note("<60 ~ [64,67] 72>*16")
.sound("supersaw")
```

Status and MIDI progress messages are written to standard error in this mode,
so the Strudel code can be redirected directly to a file:

```bash
squad64-dump -strudel -t A -p 1 > pattern.strudel
```

The exporter represents the SQ-64 step grid and enabled notes. It does not
currently export velocity, gate length, automation, or arpeggiator behavior.

To use the editor, provide both a melodic track and a pattern:

```bash
squad64-edit --track A --pattern 1
```

The editor accepts tracks `A` through `C` and pattern numbers `1` through
`16`. It displays one page of up to 16 steps at a time and shows the complete
pattern length on the top line.

- Use left/right arrows or `h`/`l` to select a step.
- Use Page Up/Page Down or `[`/`]` to change pages.
- Use `n` to enter a note such as `C4` or `F#3`, and `r` to enter a rest.
- Use up/down arrows or `+`/`-` to adjust velocity by `0.5`.
- Use `c` to copy the current step and `p` to paste it.
- Use uppercase `W` to send the pattern to the SQ-64.
- Use `q` or Escape to quit.

Empty patterns cannot be sent; enter at least one note first. Use `--verbose`
with either application to list available MIDI ports while connecting.

The one-note-per-step editor supports MONO patterns only. It refuses CHORD,
ARP, or patterns containing additional hidden note events so those events
cannot be lost or misrepresented during editing.

Velocities are displayed on the SQ-64 half-step scale from `0` to `127`;
values may include `.5` (for example, `49.5`), and the up/down arrows change
velocity by `0.5`.

If the selected melodic pattern does not exist on the SQ-64, the editor opens
an `EMPTY / NEW PATTERN` editor with 16 rest steps. Sending creates it at the
selected track and pattern.

## MIDI configuration

The SQ-64 global MIDI channel is currently set by `GLOBAL_CHANNEL` in
[`squad64/protocol.py`](squad64/protocol.py). Its value is zero-based: `0`
means MIDI channel 1 and `15` means MIDI channel 16.

On the SQ-64 ALSA USB interface the program prefers `MIDI OUT 2` for device
responses and the `SEQ` endpoint for data sent to the sequencer.

### Linux SysEx output buffer

Linux's `snd_seq_midi` bridge defaults to a 4,096-byte output buffer. Melody
pattern dumps for tracks A-C are about 3.5 KB and fit, but a Track D rhythm
pattern dump is 7,068 bytes. With the default buffer, Linux truncates the
Track D message before its terminating `F7` byte. The SQ-64 then remains on
`Receiving...`, cannot acknowledge the pattern, and ignores the project
finalize message.

Increase the buffer to 8,192 bytes before starting the editor:

```bash
./setup-midi-buffer.sh
```

The script checks the current value, requests administrator access only when
the buffer needs changing, and verifies the new value. The editor also checks
the buffer before sending, so it will refuse an unsafe transfer rather than
leave the SQ-64 in receive mode.

The setting lasts until reboot or until `snd_seq_midi` is reloaded. Run the
script again after either event. If the SQ-64 is already stuck on
`Receiving...`, power-cycle it before retrying the transfer.

To make the 8,192-byte buffer permanent, create a modprobe configuration:

```bash
echo 'options snd_seq_midi output_buffer_size=8192' \
  | sudo tee /etc/modprobe.d/sq64-midi-buffer.conf
```

Reboot, then verify that the setting was applied:

```bash
cat /sys/module/snd_seq_midi/parameters/output_buffer_size
```

The command should print `8192`. With this configuration in place, the setup
script does not need to be run after each reboot.

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

Korg requires project dumps to use the fixed `0x41`, pattern dumps, `0x70`
sequence. A `0x48` pattern dump cannot be sent independently, and patterns
omitted from a project transfer are cleared. Pattern updates therefore always
retransmit every existing melodic and rhythm pattern.

## Development

The installable source is organized as follows:

- `squad64.dump` and `squad64.edit` implement the two command-line apps.
- `squad64.protocol` implements SQ-64 SysEx encoding and transfers.
- `squad64.client` provides the stateful client used by both apps.
- `squad64.progress` renders project-download progress.

Run the standard-library `unittest` suite with:

```bash
python -m unittest discover -s tests -v
```

The protocol helpers can also be imported independently through
`squad64.protocol`.

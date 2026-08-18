# Korg SQ-64 Pattern Sender

This small Python utility generates a 16-step monophonic C-major test pattern
and writes it to **Track A, Pattern 1** on a connected Korg SQ-64.

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Korg Inc. in
any way. It is experimental software provided as-is and used entirely at your
own risk. The author is not liable for damage to equipment, loss or corruption
of projects or other data, or any other direct or indirect damages resulting
from its use. Back up important SQ-64 projects before enabling updates.

## License

This project is source-available under the
[PolyForm Noncommercial License 1.0.0](LICENSE.md). You may use, study, modify,
and redistribute the software for permitted noncommercial purposes, subject to
the complete license terms and notice requirements.

Commercial use is not granted by this license. This project should therefore
not be described as OSI-approved open-source software; it is source-available
software for noncommercial use. Contact the author if you need separate
permission for commercial use.

The SQ-64 SysEx protocol transfers patterns as part of a project transaction;
it does not provide an isolated single-pattern write operation. To avoid
clearing unrelated patterns, the utility first downloads every existing
melodic and rhythm pattern, replaces A1 locally, and uploads the complete set
again.

## Edit buffer and saved projects

The SQ-64 keeps the project currently being edited in a temporary **edit
buffer**. This buffer contains the active project settings and its melodic and
rhythm patterns. The SQ-64 also has 64 **saved project slots** in internal
memory. Those stored slots are separate from the active edit buffer.

This app reads and writes only the current edit buffer, using the Current
Project SysEx messages (`0x11` and `0x41`). It does not write a saved project
slot with the ROM Project message (`0x4D`). Consequently, an update can be
returned by a subsequent dump while the SQ-64's saved project name and pattern
name remain unchanged. Reloading a saved project or restarting the SQ-64 may
discard the edit-buffer changes.

Use the SQ-64's own project-save workflow if you want to preserve an updated
edit buffer in internal memory. Back up important projects before doing so.

## Generated pattern

The pattern is named `PYTHON TEST`, uses 16 steps, and is configured for equal
temperament with C as its root in MONO mode.

```text
C3  -  E3  -  G3  -  E3  -
C4  -  G3  -  E3  -  D3  -
```

Velocity, gate, timing, and other event parameters reproduce the reference
Track A, Pattern 1 structure captured from the SQ-64. The pattern is generated
locally and does not clone an existing pattern at runtime. MIDI note numbers
are used, with C3 represented as note 48.

## Requirements

- Korg SQ-64 running system version 2.x
- Python 3
- A working MIDI connection to the SQ-64
- [`mido`](https://mido.readthedocs.io/)
- [`python-rtmidi`](https://pypi.org/project/python-rtmidi/)

Install the Python dependencies in a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/pip install mido python-rtmidi
```

## Usage

Connect and power on the SQ-64, then run:

```bash
.venv/bin/python main.py
```

This is read-only: it dumps and displays the current project without writing
to the SQ-64. To replace Track A, Pattern 1, run:

```bash
.venv/bin/python main.py --update
```

The short form `-u` is equivalent.

Display the application version with:

```bash
.venv/bin/python main.py --version
```

The program lists the available MIDI ports. On the SQ-64 ALSA USB interface it
prefers `MIDI OUT 2` for device responses and the `SEQ` endpoint for data sent
to the sequencer. It then:

1. Downloads the current project header.
2. Downloads all patterns marked as present in the project.
3. If `--update` is supplied, builds the test pattern and replaces Track A,
   Pattern 1 in memory.
4. In update mode, uploads the project header and every preserved pattern.
5. Finalizes each project transfer.

Do not disconnect or power off the SQ-64 during the transfer. Although the
utility preserves other patterns according to Korg's documented protocol,
backing up important projects before testing is recommended.

## MIDI configuration

The SQ-64 global MIDI channel is currently set by `GLOBAL_CHANNEL` in
[`sq64.py`](sq64.py). Its value is zero-based: `0` means MIDI channel 1 and
`15` means MIDI channel 16.

The destination is currently fixed to Track A (`0`) and Pattern 1 (`0`).

## Official Korg documentation

The implementation follows Korg's official SQ-64 MIDI Implementation,
Revision 1.00 (2023-01-24), published for the version 2.x firmware generation:

- [SQ-64 product page](https://www.korg.com/us/products/dj/sq_64/)
- [SQ-64 owner's manual](https://www.korg.com/us/support/download/manual/0/872/4676/)
- [System version 2.0 owner's manual](https://www.korg.com/us/support/download/manual/0/872/4926/)
- [Detailed SQ-64 MIDI Implementation](https://www.korg.com/us/support/download/manual/0/872/5143/)
- [MIDI Implementation Chart](https://www.korg.com/us/support/download/manual/0/872/4947/)
- [SQ-64 system updater 2.03 for Windows](https://www.korg.com/us/support/download/software/0/872/4737/)
- [SQ-64 system updater 2.03 for macOS](https://www.korg.com/us/support/download/software/0/872/4738/)
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

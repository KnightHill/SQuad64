# Korg SQ-64 Pattern Sender

This small Python utility generates a 16-step monophonic C-major test pattern
and writes it to **Track A, Pattern 1** on a connected Korg SQ-64.

The SQ-64 SysEx protocol transfers patterns as part of a project transaction;
it does not provide an isolated single-pattern write operation. To avoid
clearing unrelated patterns, the utility first downloads every existing
melodic and rhythm pattern, replaces A1 locally, and uploads the complete set
again.

## Generated pattern

The pattern is named `PYTHON TEST`, uses 16 steps, and is configured for equal
temperament with C as its root in MONO mode.

```text
C3  -  E3  -  G3  -  E3  -
C4  -  G3  -  E3  -  D3  -
```

Each note has velocity 100 and an 80% gate length. MIDI note numbers are used,
with C3 represented as note 48.

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

The program lists the available MIDI ports. On the SQ-64 ALSA USB interface it
prefers `MIDI OUT 2` for device responses and the `SEQ` endpoint for data sent
to the sequencer. It then:

1. Downloads the current project header.
2. Downloads all patterns marked as present in the project.
3. Builds the test pattern and replaces Track A, Pattern 1 in memory.
4. Uploads the project header and every preserved pattern.
5. Finalizes the project transfer.

Do not disconnect or power off the SQ-64 during the transfer. Although the
utility preserves other patterns according to Korg's documented protocol,
backing up important projects before testing is recommended.

## MIDI configuration

The SQ-64 global MIDI channel is currently set by `GLOBAL_CHANNEL` in
[`main.py`](main.py). Its value is zero-based: `0` means MIDI channel 1 and
`15` means MIDI channel 16.

The destination is currently fixed to Track A (`0`) and Pattern 1 (`0`).

## Protocol reference

The implementation follows Korg's official SQ-64 MIDI Implementation,
Revision 1.00 (2023-01-24), published for the version 2.x firmware generation:

- [SQ-64 MIDI Implementation download page](https://www.korg.com/us/support/download/manual/0/872/5143/)
- [SQ-64 support downloads](https://www.korg.com/us/support/download/product/0/872/)

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

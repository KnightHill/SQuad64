#!/usr/bin/env bash

set -euo pipefail

buffer_path=/sys/module/snd_seq_midi/parameters/output_buffer_size
required_size=8192

if [[ ! -e "$buffer_path" ]]; then
    echo "Error: snd_seq_midi is not loaded; connect the SQ-64 first." >&2
    exit 1
fi

current_size=$(<"$buffer_path")
if (( current_size >= required_size )); then
    echo "ALSA MIDI output buffer is already $current_size bytes."
    exit 0
fi

echo "Increasing ALSA MIDI output buffer from $current_size to $required_size bytes..."
printf '%s\n' "$required_size" | sudo tee "$buffer_path" >/dev/null

updated_size=$(<"$buffer_path")
if (( updated_size < required_size )); then
    echo "Error: ALSA MIDI output buffer is still $updated_size bytes." >&2
    exit 1
fi

echo "ALSA MIDI output buffer is now $updated_size bytes."
echo "This setting lasts until reboot or snd_seq_midi is reloaded."

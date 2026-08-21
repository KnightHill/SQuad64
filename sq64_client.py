from typing import Optional

import sq64


class SQ64Client:
    """Operate one SQ-64 through an open pair of MIDI ports."""

    def __init__(
        self,
        inport: sq64.InputPort,
        outport: sq64.OutputPort,
        global_channel: Optional[int] = None,
    ) -> None:
        if global_channel is None:
            global_channel = sq64.GLOBAL_CHANNEL

        if (
            not isinstance(global_channel, int)
            or not 0 <= global_channel <= 15
        ):
            raise ValueError("SQ-64 global channel must be between 0 and 15")

        self.inport = inport
        self.outport = outport
        self.global_channel = global_channel

    def sysex(
        self,
        function: int,
        extra: sq64.ByteData = (),
    ) -> sq64.MidiMessage:
        """Build a SysEx message addressed to this SQ-64."""
        return sq64.sq64_sysex(function, extra, self.global_channel)

    def wait_for_function(
        self,
        wanted: int,
        timeout: float = 5.0,
        progress: Optional[sq64.ProgressCallback] = None,
    ) -> sq64.MidiMessage:
        """Wait for a function response from this SQ-64."""
        return sq64.wait_for_function(
            self.inport,
            wanted,
            timeout,
            global_channel=self.global_channel,
            progress=progress,
        )

    def wait_for_ack(
        self,
        context: str = "data transfer",
        timeout: float = 10.0,
    ) -> None:
        """Wait for an acknowledgement from this SQ-64."""
        return sq64.wait_for_ack(
            self.inport,
            context,
            timeout,
            global_channel=self.global_channel,
        )

    def get_firmware_version(self, timeout: float = 5.0) -> str:
        """Request and return this SQ-64's firmware version."""
        return sq64.get_firmware_version(
            self.inport,
            self.outport,
            timeout,
        )

    def read_pattern_dump(
        self,
        request_func: int,
        dump_func: int,
        selector: int,
        packed_size: int,
        unpacked_size: int,
        expected_signature: bytes,
        progress: Optional[sq64.ProgressCallback] = None,
    ) -> bytearray:
        """Request, validate, and unpack one pattern from this SQ-64."""
        return sq64.read_pattern_dump(
            self.inport,
            self.outport,
            request_func,
            dump_func,
            selector,
            packed_size,
            unpacked_size,
            expected_signature,
            global_channel=self.global_channel,
            progress=progress,
        )

    def read_current_project(self) -> sq64.ProjectDump:
        """Read this SQ-64's current project and populated patterns."""
        return sq64.read_current_project(
            self.inport,
            self.outport,
            global_channel=self.global_channel,
        )

    def read_global_data(self) -> bytearray:
        """Read this SQ-64's global settings."""
        return sq64.read_global_data(
            self.inport,
            self.outport,
            global_channel=self.global_channel,
        )

    def send_pattern(
        self,
        project: sq64.ByteData,
        pattern: sq64.ByteData,
        melody_patterns: sq64.MelodyPatternMap,
        rhythm_patterns: sq64.RhythmPatternMap,
        *,
        target_track: int = 0,
        target_pattern: int = 0,
        include_existing: bool = True,
    ) -> None:
        """Replace one melodic pattern while preserving other patterns."""
        if target_track == 0 and target_pattern == 0:
            return sq64.send_pattern(
                self.inport,
                self.outport,
                project,
                pattern,
                melody_patterns,
                rhythm_patterns,
                global_channel=self.global_channel,
            )
        return sq64.send_pattern(
            self.inport,
            self.outport,
            project,
            pattern,
            melody_patterns,
            rhythm_patterns,
            target_track=target_track,
            target_pattern=target_pattern,
            include_existing=include_existing,
            global_channel=self.global_channel,
        )

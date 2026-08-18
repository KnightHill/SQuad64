import sq64


class SQ64Client:
    """Operate one SQ-64 through an open pair of MIDI ports."""

    def __init__(self, inport, outport, global_channel=None):
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

    def sysex(self, function, extra=()):
        """Build a SysEx message addressed to this SQ-64."""
        return sq64.sq64_sysex(function, extra, self.global_channel)

    def wait_for_function(self, wanted, timeout=5.0, progress=None):
        """Wait for a function response from this SQ-64."""
        return sq64.wait_for_function(
            self.inport,
            wanted,
            timeout,
            global_channel=self.global_channel,
            progress=progress,
        )

    def wait_for_ack(self, context="data transfer", timeout=10.0):
        """Wait for an acknowledgement from this SQ-64."""
        return sq64.wait_for_ack(
            self.inport,
            context,
            timeout,
            global_channel=self.global_channel,
        )

    def get_firmware_version(self, timeout=5.0):
        """Request and return this SQ-64's firmware version."""
        return sq64.get_firmware_version(
            self.inport,
            self.outport,
            timeout,
        )

    def read_pattern_dump(self, request_func, dump_func, selector,
                          packed_size, unpacked_size, expected_signature,
                          progress=None):
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

    def read_current_project(self):
        """Read this SQ-64's current project and populated patterns."""
        return sq64.read_current_project(
            self.inport,
            self.outport,
            global_channel=self.global_channel,
        )

    def send_pattern(self, project, pattern,
                     melody_patterns, rhythm_patterns):
        """Replace A1 while preserving this SQ-64's other patterns."""
        return sq64.send_pattern(
            self.inport,
            self.outport,
            project,
            pattern,
            melody_patterns,
            rhythm_patterns,
            global_channel=self.global_channel,
        )

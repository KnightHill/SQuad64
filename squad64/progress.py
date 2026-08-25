import sys
import time


class PatternDumpIndicator:
    """Render pattern download progress without filling the terminal."""

    frames = (
        "⠋", "⠙", "⠹", "⠸", "⠼",
        "⠴", "⠦", "⠧", "⠇", "⠏",
    )

    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.stdout
        self.interactive = bool(
            getattr(self.stream, "isatty", lambda: False)()
        )
        self.label = None
        self.frame = 0
        self.completed = 0
        self.last_width = 0
        self.next_update = 0.0

    def start(self, label):
        """Start or replace the current pattern label."""
        self.label = label

        if self.interactive:
            self.update(force=True)
        else:
            print(f"  Dumping {label}...", file=self.stream)

    def update(self, force=False):
        """Advance the spinner when its refresh interval has elapsed."""
        if not self.interactive or self.label is None:
            return

        now = time.monotonic()

        if not force and now < self.next_update:
            return

        text = f"  {self.frames[self.frame]} Dumping {self.label}..."
        print(
            f"\r{text:<{self.last_width}}",
            end="",
            flush=True,
            file=self.stream,
        )
        self.last_width = max(self.last_width, len(text))
        self.frame = (self.frame + 1) % len(self.frames)
        self.next_update = now + 0.08

    def complete(self):
        """Count the current pattern as downloaded."""
        self.completed += 1

    def finish(self, success=True):
        """Finish the live line, leaving one compact status message."""
        if self.label is None or not self.interactive:
            return

        if success:
            noun = "pattern" if self.completed == 1 else "patterns"
            text = f"  ✓ Dumped {self.completed} {noun}."
        else:
            text = "  ✗ Pattern dump failed."

        print(
            f"\r{text:<{self.last_width}}",
            flush=True,
            file=self.stream,
        )
        self.label = None

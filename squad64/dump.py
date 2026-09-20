#!/usr/bin/env python3

import argparse
import sys
from contextlib import redirect_stdout

import mido

from . import __version__
from . import protocol as sq64
from .client import SQ64Client
from .output import melody_pattern_as_strudel

def pattern_number(value):
    """Parse a user-facing SQ-64 pattern number."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("pattern must be an integer") from error

    if not 1 <= number <= 16:
        raise argparse.ArgumentTypeError("pattern must be between 1 and 16")

    return number


def parse_args():
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        prog="squad64-dump",
        description="SQuad64 dumps the current SQ-64 project."
    )
    parser.add_argument(
        "-g",
        "--global",
        dest="show_global",
        action="store_true",
        help="show firmware version and global settings, then exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="list all available MIDI input and output ports",
    )
    parser.add_argument(
        "-t",
        "--track",
        type=str.upper,
        choices=("A", "B", "C", "D"),
        help="show only the selected track in the project dump",
    )
    parser.add_argument(
        "-p",
        "--pattern",
        type=pattern_number,
        metavar="1-16",
        help="show only the selected pattern number in the project dump",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-strudel",
        "--strudel",
        action="store_true",
        help="print one selected melodic pattern as Strudel code",
    )

    args = parser.parse_args()
    if args.strudel:
        if args.show_global:
            parser.error("-strudel cannot be combined with --global")
        if args.track is None or args.pattern is None:
            parser.error("-strudel requires --track and --pattern")
        if args.track == "D":
            parser.error("-strudel supports melodic tracks A through C")
    return args


def run(args):
    """Run one SQ-64 read-only dump operation."""
    if args.strudel:
        with redirect_stdout(sys.stderr):
            input_name, output_name = sq64.find_sq64_ports(
                verbose=args.verbose
            )
    else:
        input_name, output_name = sq64.find_sq64_ports(verbose=args.verbose)

    status = sys.stderr if args.strudel else sys.stdout
    print(file=status)
    print("SQ-64 input :", input_name, file=status)
    print("SQ-64 output:", output_name, file=status)

    with (
        mido.open_input(input_name) as inp,
        mido.open_output(output_name) as out
    ):
        client = SQ64Client(inp, out)

        if args.show_global:
            firmware_version = client.get_firmware_version()
            print(f"\nFirmware version: {firmware_version}")
            print("\nReading global data...")
            global_data = client.read_global_data()
            print()
            sq64.print_global_data(global_data)
            return

        print(
            "\nReading current project and existing patterns...",
            file=status,
        )
        if args.strudel:
            with redirect_stdout(sys.stderr):
                project, melody_patterns, rhythm_patterns = (
                    client.read_current_project()
                )
        else:
            project, melody_patterns, rhythm_patterns = (
                client.read_current_project()
            )

        if args.strudel:
            track = ord(args.track) - ord("A")
            pattern_number = args.pattern - 1
            pattern = melody_patterns.get((track, pattern_number))
            if pattern is None:
                raise RuntimeError(
                    f"Track {args.track} / Pattern {args.pattern} "
                    "does not exist"
                )
            bpm = (project[20] | project[21] << 8) / 10
            print(melody_pattern_as_strudel(pattern, bpm))
            return

        sq64.print_project_dump(
            project,
            melody_patterns,
            rhythm_patterns,
            track=args.track,
            pattern_number=args.pattern,
        )
        print("\nDone (read-only).")


def main():
    """Run the command-line app with concise operational errors."""
    args = parse_args()

    try:
        run(args)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except (ImportError, OSError, RuntimeError) as error:
        message = str(error) or type(error).__name__
        print(f"Error: {message}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

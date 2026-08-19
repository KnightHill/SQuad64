#!/usr/bin/env python3

import argparse
import sys

import mido

import sq64
from sq64_client import SQ64Client


__version__ = "0.2.2"

TEST_PATTERN_NOTES = [
    48, None,
    52, None,
    55, None,
    52, None,
    60, None,
    55, None,
    52, None,
    50, None,
]


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
        prog="squad64",
        description=(
            "SQuad64 dumps the current SQ-64 project and optionally replaces "
            "Track A / Pattern 1."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-u",
        "--update",
        action="store_true",
        help="update Track A / Pattern 1 after dumping the project",
    )
    mode.add_argument(
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
    return parser.parse_args()


def run(args):
    """Run one SQ-64 dump or update operation."""
    input_name, output_name = sq64.find_sq64_ports(verbose=args.verbose)

    print()
    print("SQ-64 input :", input_name)
    print("SQ-64 output:", output_name)

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

        print("\nReading current project and existing patterns...")
        project, melody_patterns, rhythm_patterns = (
            client.read_current_project()
        )
        sq64.print_project_dump(
            project,
            melody_patterns,
            rhythm_patterns,
            track=args.track,
            pattern_number=args.pattern,
        )

        if not args.update:
            print("\nDone (read-only; use --update to write the pattern).")
            return

        print("Building replicated test pattern locally...")
        pattern = sq64.build_pattern(TEST_PATTERN_NOTES)

        print("Sending Track A / Pattern 1...")
        client.send_pattern(
            project,
            pattern,
            melody_patterns,
            rhythm_patterns,
        )

        print("Done.")


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

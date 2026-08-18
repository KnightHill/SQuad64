import argparse

import mido

import sq64


__version__ = "0.1.0"


def parse_args():
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Dump the current SQ-64 project and optionally replace "
            "Track A / Pattern 1."
        )
    )
    parser.add_argument(
        "-u",
        "--update",
        action="store_true",
        help="update Track A / Pattern 1 after dumping the project",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args()


def main():
    """Dump the current project and optionally update Track A, Pattern 1."""
    args = parse_args()
    input_name, output_name = sq64.find_sq64_ports()

    print()
    print("SQ-64 input :", input_name)
    print("SQ-64 output:", output_name)

    with (
        mido.open_input(input_name) as inp,
        mido.open_output(output_name) as out
    ):
        print("\nReading current project and existing patterns...")
        project, melody_patterns, rhythm_patterns = sq64.read_current_project(
            inp,
            out,
        )
        sq64.print_project_dump(project, melody_patterns, rhythm_patterns)

        if not args.update:
            print("\nDone (read-only; use --update to write the pattern).")
            return

        print("Building replicated test pattern locally...")
        pattern = sq64.build_pattern()

        print("Sending Track A / Pattern 1...")
        sq64.send_pattern(
            inp,
            out,
            project,
            pattern,
            melody_patterns,
            rhythm_patterns,
        )

        print("Done.")


if __name__ == "__main__":
    main()

import argparse
import logging
import sys

from src.gtfs.models.ConvertConfig import ConvertConfig
from src.PipelineConverter import PipelineConverter
from src.Version import Version


class CommandLineInterface:
    """Command-line interface for raptor-gtfs-pipeline."""

    @staticmethod
    def setup_logging(verbose: bool = False) -> None:
        """Configure logging."""
        level = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    @staticmethod
    def cmd_convert(args: argparse.Namespace) -> int:
        """Execute convert command."""
        CommandLineInterface.setup_logging(args.verbose)

        config = ConvertConfig(
            input_path=args.input,
            output_path=args.output,
            format=args.format,
            compression=args.compression,
            debug_json=args.debug_json,
            gen_transfers=args.gen_transfers,
            allow_partial_trips=args.allow_partial_trips,
            speed_walk=args.speed_walk,
            transfer_cutoff=args.transfer_cutoff,
            jobs=args.jobs,
            split_by_periods=args.split_by_periods,
        )

        try:
            manifest = PipelineConverter.convert(args.input, args.output, config)
            print("\nConversion successful!")
            print(f"Output: {args.output}")
            print(f"Stats: {manifest.stats}")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            logging.exception("Conversion failed")
            return 1

    @staticmethod
    def main() -> None:
        """Main CLI entry point."""
        parser = argparse.ArgumentParser(
            prog="raptor-gtfs",
            description="Convert GTFS datasets to RAPTOR binary format",
        )
        parser.add_argument("--version", action="version", version=f"%(prog)s {Version.VERSION}")
        parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

        subparsers = parser.add_subparsers(dest="command", help="Command to execute")

        # Convert command
        convert_parser = subparsers.add_parser("convert", help="Convert GTFS to binary format")
        convert_parser.add_argument("--input", required=True, help="Path to GTFS directory")
        convert_parser.add_argument(
            "--output", default="./raptor_data", help="Output directory (default: ./raptor_data)"
        )
        convert_parser.add_argument(
            "--format",
            choices=["binary", "json", "both"],
            default="binary",
            help="Output format (default: binary)",
        )
        convert_parser.add_argument(
            "--compression",
            type=lambda x: x.lower() == "true",
            default=True,
            help="Enable delta compression (default: true)",
        )
        convert_parser.add_argument(
            "--debug-json",
            type=lambda x: x.lower() == "true",
            default=False,
            help="Generate debug JSON files (default: false)",
        )
        convert_parser.add_argument(
            "--gen-transfers",
            type=lambda x: x.lower() == "true",
            default=False,
            help="Generate walking transfers (default: false)",
        )
        convert_parser.add_argument(
            "--allow-partial-trips",
            type=lambda x: x.lower() == "true",
            default=False,
            help="Allow partial trips (default: false)",
        )
        convert_parser.add_argument(
            "--speed-walk",
            type=float,
            default=1.33,
            help="Walking speed in m/s (default: 1.33)",
        )
        convert_parser.add_argument(
            "--transfer-cutoff",
            type=int,
            default=500,
            help="Transfer generation cutoff in meters (default: 500)",
        )
        convert_parser.add_argument(
            "--jobs",
            type=int,
            default=1,
            help="Number of parallel jobs (default: 1)",
        )
        convert_parser.add_argument(
            "--split-by-periods",
            type=lambda x: x.lower() == "true",
            default=False,
            help="Generate separate folders per service period "
                 "(weekday/saturday/sunday) (default: false)",
        )
        convert_parser.set_defaults(func=CommandLineInterface.cmd_convert)

        # Parse and execute
        args = parser.parse_args()

        if not args.command:
            parser.print_help()
            sys.exit(1)

        sys.exit(args.func(args))


if __name__ == "__main__":
    CommandLineInterface.main()

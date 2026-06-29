import argparse
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

from src.PipelineConverter import PipelineConverter
from src.gtfs.models.ConvertConfig import ConvertConfig


class PipelineRunner:
    """Generic standalone runner for the RAPTOR GTFS conversion pipeline."""

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
    def run_conversion(
        input_path_str: str,
        output_path_str: str,
        split_by_periods: bool = True,
        verbose: bool = False,
    ) -> None:
        """Run the generic conversion pipeline, extracting ZIP files if necessary."""
        PipelineRunner.setup_logging(verbose)
        logger = logging.getLogger(__name__)

        input_path = Path(input_path_str)
        output_path = Path(output_path_str)

        temp_dir = None
        try:
            # Check if input is a ZIP file
            if input_path.is_file() and input_path.suffix.lower() == ".zip":
                logger.info(f"Extracting GTFS ZIP file: {input_path}")
                temp_dir = tempfile.mkdtemp(prefix="raptor_gtfs_")

                with zipfile.ZipFile(input_path, "r") as zip_ref:
                    zip_ref.extractall(temp_dir)

                # Find the directory containing the GTFS .txt files
                temp_path = Path(temp_dir)
                txt_files = list(temp_path.glob("**/*.txt"))
                if not txt_files:
                    raise FileNotFoundError("No .txt files found inside the GTFS ZIP archive.")

                actual_input = str(txt_files[0].parent)
                logger.info(f"Using extracted GTFS directory: {actual_input}")
            else:
                actual_input = str(input_path)

            config = ConvertConfig(
                input_path=actual_input,
                output_path=str(output_path),
                format="binary",
                compression=True,
                debug_json=False,
                gen_transfers=False,
                allow_partial_trips=False,
                split_by_periods=split_by_periods,
            )

            manifest = PipelineConverter.convert(actual_input, str(output_path), config)
            logger.info("\nConversion successful!")
            logger.info(f"Output directory: {output_path}")
            logger.info(f"Stats: {manifest.stats}")

        finally:
            if temp_dir:
                logger.info(f"Cleaning up temporary directory: {temp_dir}")
                shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def main() -> None:
        """Main runner CLI entry point (generic mode only)."""
        parser = argparse.ArgumentParser(
            description="Generic runner for RAPTOR GTFS conversion pipeline."
        )
        parser.add_argument(
            "--input",
            required=True,
            help="Path to GTFS directory or ZIP file",
        )
        parser.add_argument(
            "--output",
            default="./raptor_data",
            help="Output directory (default: ./raptor_data)",
        )
        parser.add_argument(
            "--split-by-periods",
            action="store_true",
            default=True,
            help="Generate separate folders per service period (default: true)",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Verbose logging output",
        )

        args = parser.parse_args()
        PipelineRunner.run_conversion(
            input_path_str=args.input,
            output_path_str=args.output,
            split_by_periods=args.split_by_periods,
            verbose=args.verbose,
        )


if __name__ == "__main__":
    PipelineRunner.main()

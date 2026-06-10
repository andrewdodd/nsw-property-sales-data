from textwrap import dedent
import argparse
import logging
import sys
from pathlib import Path
from contextlib import ExitStack

from nsw_property_sales_data.sync_db import (
    sync_db,
    SqliteDestinationProvider,
    CsvOutProvider,
)

from nsw_property_sales_data.protocols import MultipleDestinations, DestinationProvider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sync_db",
        description="Create or update a NSW property sales database.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("db_path", type=Path, help="Path to the SQLite database file")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".nsw_property_sales_data"),
        help=dedent("""\
        Directory to cache downloaded zips.
        Provide a temporary location like /tmp/%(default)s to not retain ZIPs.
        (default: %(default)s)"""),
    )
    parser.add_argument(
        "--skip-web-check",
        action="store_true",
        help="skip checking the NSW Valuer General website and just process cached files",
    )
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="If doing a full rebuild, pass this to disable index updating until the end.",
    )
    parser.add_argument(
        "--import-from-year",
        type=int,
        default=1900,
        help="If passed, this will be converted to a year, and only files >= to this will be included.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable verbose logging",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        help="Also output sales to CSV if provided.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("nsw_property_sales_data").setLevel(
        logging.DEBUG if args.verbose else logging.INFO
    )

    providers: list[DestinationProvider] = [
        SqliteDestinationProvider(args.db_path, args.full_rebuild)
    ]
    if args.csv_output:
        providers.append(CsvOutProvider(args.csv_output, args.full_rebuild))
    with ExitStack() as stack:
        destinations = [stack.enter_context(provider) for provider in providers]

        return sync_db(
            MultipleDestinations(destinations),
            args.cache_dir,
            from_files_on_disk=args.skip_web_check,
            import_from_year=args.import_from_year,
        )


if __name__ == "__main__":
    sys.exit(main())

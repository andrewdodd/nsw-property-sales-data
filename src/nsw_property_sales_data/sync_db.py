import logging
import sqlite3
import io
from dataclasses import asdict
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple, Self
from dataclasses import astuple

from .protocols import Sale, Destination, DestinationProvider
from nsw_property_sales_data import db
from .ingest import ingest_zip
from .raw_data import (
    download_unsynced,
    fetch_zip_addresses,
    unsynced_zips,
)


logger = logging.getLogger(__name__)

# Above this many pending zips, drop the FTS triggers during ingest and rebuild
# the FTS index once at the end. Below the threshold, per-row trigger cost is
# cheaper than a full rebuild scan.
FTS_REBUILD_THRESHOLD = 20

_FTS_TRIGGERS_SQL = """
CREATE TRIGGER sale_after_insert AFTER INSERT ON sale BEGIN
    INSERT INTO sale_fts(rowid, street_name, locality, property_name)
    VALUES (new.rowid, new.street_name, new.locality, new.property_name);
END;

CREATE TRIGGER sale_after_delete AFTER DELETE ON sale BEGIN
    INSERT INTO sale_fts(sale_fts, rowid, street_name, locality, property_name)
    VALUES ('delete', old.rowid, old.street_name, old.locality, old.property_name);
END;

CREATE TRIGGER sale_after_update AFTER UPDATE ON sale BEGIN
    INSERT INTO sale_fts(sale_fts, rowid, street_name, locality, property_name)
    VALUES ('delete', old.rowid, old.street_name, old.locality, old.property_name);
    INSERT INTO sale_fts(rowid, street_name, locality, property_name)
    VALUES (new.rowid, new.street_name, new.locality, new.property_name);
END;
"""


class PendingZip(NamedTuple):
    url: str
    path: Path

    @classmethod
    def from_file_only(cls, path: Path) -> Self:
        base = "https://www.valuergeneral.nsw.gov.au/__psi"
        stem = path.name.removesuffix(".zip")
        url = (
            f"{base}/weekly/{path.name}"
            if len(stem) == 8 and stem.isdigit()
            else f"{base}/yearly/{path.name}"
        )
        return cls(url, path)

    def is_from_or_after_year(self, year: int) -> bool:
        file_year = int(self.path.stem[:4])
        return file_year >= year


class SqliteDestinationProvider(DestinationProvider):
    def __init__(self, db_path: Path, full_rebuild: bool = False):
        self.db_path = db_path
        self._context_depth = 0
        self._full_rebuild = full_rebuild
        self._conn: SqliteDestination | None = None

    def __enter__(self):
        self._context_depth += 1
        if self._context_depth > 1:
            assert self._conn is not None
            return self._conn

        assert self._conn is None
        if self.db_path.exists():
            logger.info("Using existing database at %s", self.db_path)
        else:
            logger.info("Creating new database at %s", self.db_path)
            db.create_database(self.db_path)

        conn = db.connect(self.db_path)
        if self._full_rebuild:
            conn.executescript(
                """
            DROP TRIGGER IF EXISTS sale_after_insert;
            DROP TRIGGER IF EXISTS sale_after_delete;
            DROP TRIGGER IF EXISTS sale_after_update;
            """
            )
        self._conn = SqliteDestination(conn)
        return self._conn

    def __exit__(self, *exc):
        assert self._conn is not None
        self._context_depth -= 1
        if self._context_depth > 0:
            return False

        conn = self._conn._conn
        if self._full_rebuild:
            conn.executescript(_FTS_TRIGGERS_SQL)
            logger.info("Rebuilding FTS index...")
            conn.execute("INSERT INTO sale_fts(sale_fts) VALUES('rebuild')")
        conn.commit()
        conn.close()
        self._conn = None
        return False


class SqliteDestination(Destination):
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def already_loaded_zips(self):
        return {row[0] for row in self._conn.execute("SELECT filename FROM loaded_zip")}

    def sale_count(self):
        return db.sale_count(self._conn)

    def upsert_districts(self, districts: set[tuple[str, str]]):
        if districts:
            self._conn.executemany(
                "INSERT OR IGNORE INTO district (code, name) VALUES (?, ?)", districts
            )

    def upsert_zones(self, zones: set[tuple[str, str]]):
        if zones:
            self._conn.executemany(
                "INSERT OR IGNORE INTO zone (code, name) VALUES (?, ?)", zones
            )

    def insert_sales(self, sales: list[Sale]):
        _SALE_UPSERT_SQL = """
            INSERT INTO sale (
                district_code, property_id, sale_counter,
                property_name, unit_number, house_number, street_name, locality, postcode,
                area_sqm, contract_date, settlement_date, purchase_price,
                zoning, nature, purpose, purpose_original,
                component_code, sale_code, percent_interest, dealing_number,
                legal_description, vendor_count, purchaser_count,
                source_format, download_datetime
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(transaction_key) DO UPDATE SET
                sale_counter      = excluded.sale_counter,
                property_name     = excluded.property_name,
                unit_number       = excluded.unit_number,
                house_number      = excluded.house_number,
                street_name       = excluded.street_name,
                locality          = excluded.locality,
                postcode          = excluded.postcode,
                area_sqm          = excluded.area_sqm,
                contract_date     = excluded.contract_date,
                settlement_date   = excluded.settlement_date,
                purchase_price    = excluded.purchase_price,
                zoning            = excluded.zoning,
                nature            = excluded.nature,
                purpose           = excluded.purpose,
                purpose_original  = excluded.purpose_original,
                component_code    = excluded.component_code,
                sale_code         = excluded.sale_code,
                percent_interest  = excluded.percent_interest,
                dealing_number    = excluded.dealing_number,
                legal_description = excluded.legal_description,
                vendor_count      = excluded.vendor_count,
                purchaser_count   = excluded.purchaser_count,
                source_format     = excluded.source_format,
                download_datetime = excluded.download_datetime
            WHERE sale.download_datetime IS NULL
               OR (excluded.download_datetime IS NOT NULL
                   AND excluded.download_datetime > sale.download_datetime)
        """
        self._conn.executemany(_SALE_UPSERT_SQL, (astuple(s) for s in sales))

    def insert_zip(self, zip_path: Path, url: str):
        self._conn.execute(
            "INSERT INTO loaded_zip (filename, url, loaded_at) VALUES (?, ?, ?)",
            (zip_path.name, url, datetime.now(timezone.utc).isoformat()),
        )

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


def sync_db(
    destination: Destination,
    cache_dir: Path,
    from_files_on_disk: bool = False,
    import_from_year: int = 1900,
) -> int:
    start = datetime.now()

    sales_before = destination.sale_count()
    try:
        already_loaded = destination.already_loaded_zips()

        if from_files_on_disk:
            pending = _ingestable_from_cache(already_loaded, cache_dir)
            logger.info("%d cached zips pending ingest", len(pending))
        else:
            pending = _fetch_and_download(already_loaded, cache_dir)

        pending_from_year = [
            p for p in pending if p.is_from_or_after_year(import_from_year)
        ]
        if len(pending_from_year) != len(pending):
            logger.debug(
                f"Only ingesting {len(pending_from_year)} of {len(pending)} zips from {import_from_year} onwards"
            )

        if pending_from_year:
            logger.info("Ingesting zips...")
            for entry in pending_from_year:
                logger.debug("Ingesting %s", entry.path.name)
                ingest_zip(destination, entry.path, entry.url)
            logger.info("  %d zips ingested", len(pending_from_year))

    except KeyboardInterrupt:
        logger.info("Cancelled by user")
    finally:
        sales_after = destination.sale_count()

    elapsed = timedelta(seconds=round((datetime.now() - start).total_seconds()))
    sales_inserted = sales_after - sales_before
    rate = int(round(sales_inserted / elapsed.total_seconds()))
    logger.info(
        f"Sync complete: {sales_inserted} sales added ({sales_before} -> {sales_after}) in {elapsed} ({rate} records/sec)"
    )

    return 0


def _fetch_and_download(loaded: set[str], cache_dir: Path) -> list[PendingZip]:
    logger.info("Fetching available zip URLs from NSW portal...")
    available = fetch_zip_addresses()
    logger.info("  %d zips available", len(available))

    pending = unsynced_zips(available, loaded)
    logger.info("  %d already loaded", len(available) - len(pending))
    logger.info("  %d pending download", len(pending))

    if not pending:
        return []

    logger.info("Downloading to %s", cache_dir)
    downloaded = download_unsynced(pending, cache_dir)
    cached = len(pending) - len(downloaded)
    logger.info("  %d downloaded, %d already cached", len(downloaded), cached)

    return [
        PendingZip(url=url, path=cache_dir / url.rsplit("/", 1)[-1]) for url in pending
    ]


def _ingestable_from_cache(loaded: set[str], cache_dir: Path) -> list[PendingZip]:
    if not cache_dir.exists():
        return []
    return [
        PendingZip.from_file_only(path)
        for path in sorted(cache_dir.glob("*.zip"))
        if path.name not in loaded
    ]


class CsvOutProvider(DestinationProvider):
    def __init__(self, path: Path, full_rebuild: bool = False):
        self.path = path
        self._full_rebuild = full_rebuild
        self._context_depth = 0
        self._csv: CsvDestination | None = None

    def __enter__(self):
        self._context_depth += 1
        if self._context_depth > 1:
            assert self._csv is not None
            return self._csv

        assert self._csv is None
        f = open(self.path, "w" if self._full_rebuild else "a", encoding="utf-8")
        self._csv = CsvDestination(f, self._full_rebuild)
        return self._csv

    def __exit__(self, *exc):
        assert self._csv is not None
        self._context_depth -= 1
        if self._context_depth > 0:
            return False

        f = self._csv._f
        f.close()
        self._csv = None
        return False


class CsvDestination(Destination):
    def __init__(self, f: io.TextIOWrapper, full_rebuild: bool):
        self._f = f
        self._full_rebuild = full_rebuild
        self._header_written = False
        self._current_zip = ""

    def already_loaded_zips(self):
        return set()

    def sale_count(self):
        return 0

    def upsert_districts(self, districts: set[tuple[str, str]]):
        pass

    def upsert_zones(self, zones: set[tuple[str, str]]):
        pass

    def insert_sales(self, sales: list[Sale]):
        writer = csv.DictWriter(
            self._f, fieldnames=list(Sale.__dataclass_fields__.keys()) + ["source_zip"]
        )
        if self._full_rebuild and not self._header_written:
            writer.writeheader()
            self._header_written = True

        for sale in sales:
            d = asdict(sale)
            d["source_zip"] = self._current_zip
            writer.writerow(d)

    def insert_zip(self, zip_path: Path, url: str):
        self._current_zip = zip_path.name

import csv
from functools import cache
from pathlib import Path
import sqlite3
from importlib import resources


# UPSERT (3.24) is the highest stdlib feature we use; FTS5 is compile-time.
_MIN_SQLITE_VERSION = (3, 24, 0)


@cache
def _assert_sqlite_capabilities() -> None:
    if sqlite3.sqlite_version_info < _MIN_SQLITE_VERSION:
        required = ".".join(str(n) for n in _MIN_SQLITE_VERSION)
        raise RuntimeError(
            f"libsqlite3 {required}+ required (for UPSERT); "
            f"this Python is linked against {sqlite3.sqlite_version}"
        )
    with sqlite3.connect(":memory:") as probe:
        try:
            probe.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                "sqlite3 was built without FTS5 support; "
                "rebuild Python against a libsqlite3 with -DSQLITE_ENABLE_FTS5"
            ) from exc


def create_database(path: Path) -> None:
    _assert_sqlite_capabilities()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_load_schema())
        conn.executemany(
            "INSERT INTO district (code, name) VALUES (?, ?)",
            _load_districts(),
        )
        conn.executemany(
            "INSERT INTO zone (code, name, category, legacy_code) VALUES (?, ?, ?, ?)",
            _load_zones(),
        )
        conn.commit()
    finally:
        conn.close()


def connect(path: Path) -> sqlite3.Connection:
    _assert_sqlite_capabilities()
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -200000")
    return conn


def _load_schema() -> str:
    return resources.files("nsw_property_sales_data").joinpath("schema.sql").read_text()


def _load_districts() -> list[list[str]]:
    text = (
        resources.files("nsw_property_sales_data")
        .joinpath("data/districts.csv")
        .read_text()
    )
    reader = csv.reader(text.splitlines())
    next(reader)
    return list(reader)


def _load_zones() -> list[tuple[str, str, str | None, str | None]]:
    text = (
        resources.files("nsw_property_sales_data")
        .joinpath("data/zones.csv")
        .read_text()
    )
    reader = csv.reader(text.splitlines())
    next(reader)
    return [
        (code, name, category or None, legacy_code or None)
        for code, name, category, legacy_code in reader
    ]


def sale_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM sale").fetchone()[0]

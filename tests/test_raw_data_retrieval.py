from io import BytesIO
import sqlite3
import pytest
from unittest.mock import patch
from pathlib import Path

from nsw_property_sales_data.raw_data import (
    download_unsynced,
    fetch_zip_addresses,
    unsynced_zips,
)


WEEKLY_BASE = "https://www.valuergeneral.nsw.gov.au/__psi/weekly"
YEARLY_BASE = "https://www.valuergeneral.nsw.gov.au/__psi/yearly"


def _preload_loaded_zips(conn: sqlite3.Connection) -> None:
    yearly_zips = [
        f"https://www.valuergeneral.nsw.gov.au/__psi/yearly/{year}.zip"
        for year in range(1990, 2026)
    ]
    weekly_zips = [
        f"https://www.valuergeneral.nsw.gov.au/__psi/weekly/{week}.zip"
        for week in [
            "20260105",
            "20260112",
            "20260119",
            "20260126",
            "20260202",
            "20260209",
            "20260216",
            "20260223",
            "20260302",
            "20260309",
            "20260316",
            "20260323",
            "20260330",
            "20260406",
            "20260413",
            "20260420",
            "20260427",
        ]
    ]

    rows = [
        (url.split("/")[-1], url, "1970-01-01T00:00:00")
        for url in yearly_zips + weekly_zips
    ]
    conn.executemany(
        "INSERT INTO loaded_zip (filename, url, loaded_at) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()


@pytest.fixture
def html_bytes() -> BytesIO:
    path = Path(__file__).parent / "pages" / "page_20260502.html"
    return BytesIO(path.read_bytes())


@patch("nsw_property_sales_data.raw_data.urlopen")
def test_fetch_zip_addresses_returns_expected_zip_links(urlopen, html_bytes):
    urlopen.return_value = html_bytes
    links = fetch_zip_addresses()
    assert f"{WEEKLY_BASE}/20260105.zip" in links
    assert f"{WEEKLY_BASE}/20260112.zip" in links
    assert f"{YEARLY_BASE}/1990.zip" in links
    assert f"{YEARLY_BASE}/2000.zip" in links


def test_unsynced_zips_empty_when_all_synced(db_path):
    available = [f"{YEARLY_BASE}/2020.zip", f"{WEEKLY_BASE}/20260105.zip"]
    assert unsynced_zips(available, {"2020.zip", "20260105.zip"}) == []


def test_unsynced_zips_returns_url_not_in_db(db_path):
    available = [
        f"{YEARLY_BASE}/2020.zip",
        f"{YEARLY_BASE}/2021.zip",
        f"{YEARLY_BASE}/1989.zip",
    ]
    assert unsynced_zips(available, {"2021.zip"}) == [
        f"{YEARLY_BASE}/2020.zip",
        f"{YEARLY_BASE}/1989.zip",
    ]


def _fake_download(url: str, target: Path) -> None:
    target.write_bytes(b"fake zip content")


@patch(
    "nsw_property_sales_data.raw_data.download_file_from_url",
    side_effect=_fake_download,
)
def test_download_unsynced_downloads_all_when_cache_empty(mock_dl, tmp_path):
    cache_dir = tmp_path / "cache"
    pending = [f"{YEARLY_BASE}/1989.zip", f"{YEARLY_BASE}/1988.zip"]

    result = download_unsynced(pending, cache_dir)

    assert mock_dl.call_count == 2
    assert sorted(p.name for p in result) == ["1988.zip", "1989.zip"]
    assert (cache_dir / "1988.zip").exists()
    assert (cache_dir / "1989.zip").exists()


@patch(
    "nsw_property_sales_data.raw_data.download_file_from_url",
    side_effect=_fake_download,
)
def test_download_unsynced_skips_files_already_on_disk(mock_dl, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "1989.zip").write_bytes(b"already cached")

    pending = [f"{YEARLY_BASE}/1989.zip", f"{YEARLY_BASE}/1988.zip"]

    result = download_unsynced(pending, cache_dir)

    mock_dl.assert_called_once_with(f"{YEARLY_BASE}/1988.zip", cache_dir / "1988.zip")
    assert [p.name for p in result] == ["1988.zip"]
    assert (cache_dir / "1989.zip").read_bytes() == b"already cached"


@patch(
    "nsw_property_sales_data.raw_data.download_file_from_url",
    side_effect=_fake_download,
)
def test_download_unsynced_creates_missing_cache_dir(mock_dl, tmp_path):
    cache_dir = tmp_path / "does" / "not" / "exist"
    pending = [f"{YEARLY_BASE}/1989.zip"]

    download_unsynced(pending, cache_dir)

    assert cache_dir.is_dir()
    assert (cache_dir / "1989.zip").exists()

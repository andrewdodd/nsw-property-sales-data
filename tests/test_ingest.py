import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from nsw_property_sales_data.sync_db import SqliteDestinationProvider
from nsw_property_sales_data.ingest import ingest_zip, clean_purpose_from_purpose


@pytest.fixture
def fake_zip(tmp_path) -> Path:
    zip_path = tmp_path / "fake.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("001.DAT", "A;RTSALEDATA;001;202601011200\n")
        zf.writestr("002.DAT", "A;RTSALEDATA;002;202601011200\n")
        zf.writestr("README.txt", "should be skipped")
    return zip_path


@pytest.fixture
def sql_dest(db_path):
    with SqliteDestinationProvider(db_path) as dest:
        yield dest


def test_ingest_zip_records_loaded_zip_row(sql_dest, fake_zip):
    url = "https://example.com/fake.zip"

    ingest_zip(sql_dest, fake_zip, url)

    row = sql_dest._conn.execute(
        "SELECT filename, url FROM loaded_zip WHERE filename = ?",
        (fake_zip.name,),
    ).fetchone()
    assert row == ("fake.zip", url)


@patch("nsw_property_sales_data.ingest._insert_sales_from_dat")
def test_ingest_zip_processes_only_dat_members(
    _insert_sales_from_dat, sql_dest, fake_zip
):
    seen: list[str] = []
    _insert_sales_from_dat.side_effect = lambda _conn, text, _old_format: seen.append(
        text
    )

    ingest_zip(sql_dest, fake_zip, "https://example.com/fake.zip")

    assert len(seen) == 2
    assert all("RTSALEDATA" in t for t in seen)


@patch("nsw_property_sales_data.ingest._insert_sales_from_dat")
def test_ingest_zip_rolls_back_on_parse_failure(
    _insert_sales_from_dat,
    sql_dest,
    fake_zip,
):
    _insert_sales_from_dat.side_effect = ValueError("error")

    with pytest.raises(ValueError):
        ingest_zip(sql_dest, fake_zip, "https://example.com/fake.zip")

    row = sql_dest._conn.execute(
        "SELECT filename FROM loaded_zip WHERE filename = ?",
        (fake_zip.name,),
    ).fetchone()
    assert row is None


WEEKLY_DAT_001 = """\
A;RTSALEDATA;001;20260105 12:00;TESTUSER
B;001;PROP001;1;20260105 12:00;;1A;42;ROAD RD;CESSNOCK;2325;500;M;20251215;20260105;750000;R1;R;;;;;;DEAL001
C;001;PROP001;1;20260105 12:00;NOTES
D;001;PROP001;1;20260105 12:00;P
D;001;PROP001;1;20260105 12:00;V
Z;5;1;1;2
"""

WEEKLY_DAT_708 = """\
A;RTSALEDATA;708;20260105 12:00;TESTUSER
B;708;PROP708A;1;20260105 12:00;;101;1;STREET ST;SYDNEY;2000;75;M;20251201;20260102;1500000;B3;3;OFFICE;;;;;DEAL002
C;708;PROP708A;1;20260105 12:00;NOTES 1
D;708;PROP708A;1;20260105 12:00;P
D;708;PROP708A;1;20260105 12:00;V
B;708;PROP708B;2;20260105 12:00;APARTMENTS;202;5;AVENUE AVE;SYDNEY;2000;120;M;20251210;20260103;2000000;R4;R;;;;;;DEAL003
C;708;PROP708B;2;20260105 12:00;NOTES 2
D;708;PROP708B;2;20260105 12:00;P
D;708;PROP708B;2;20260105 12:00;V
Z;10;2;2;4
"""


@pytest.fixture
def weekly_zip_file(tmp_path) -> Path:
    zip_path = tmp_path / "weekly_sample.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("001.DAT", WEEKLY_DAT_001)
        zf.writestr("708.DAT", WEEKLY_DAT_708)
    return zip_path


def test_it_ingests_data_from_weekly_zip_file(sql_dest, weekly_zip_file):
    url = "https://www.valuergeneral.nsw.gov.au/__psi/weekly/weekly_sample.zip"

    ingest_zip(sql_dest, weekly_zip_file, url)

    loaded = sql_dest._conn.execute(
        "SELECT filename FROM loaded_zip WHERE filename = 'weekly_sample.zip'"
    ).fetchone()
    assert loaded is not None

    count = sql_dest.sale_count()
    assert count == 3


def test_ingested_sale_has_b_record_fields(sql_dest, weekly_zip_file):
    ingest_zip(sql_dest, weekly_zip_file, "https://example.com/weekly_sample.zip")

    row = sql_dest._conn.execute(
        """
        SELECT district_code, sale_counter, postcode, street_name, locality,
               house_number, purchase_price, contract_date, settlement_date,
               zoning, nature, source_format
        FROM sale WHERE property_id = 'PROP001'
        """
    ).fetchone()
    assert row == (
        "001",
        "1",
        "2325",
        "ROAD RD",
        "CESSNOCK",
        "42",
        750000,
        "2025-12-15",
        "2026-01-05",
        "R1",
        "R",
        "new",
    )


def test_ingested_sale_has_legal_description_from_c_records(sql_dest, weekly_zip_file):
    ingest_zip(sql_dest, weekly_zip_file, "https://example.com/weekly_sample.zip")

    legal = sql_dest._conn.execute(
        "SELECT legal_description FROM sale WHERE property_id = 'PROP001'"
    ).fetchone()[0]
    assert legal == "NOTES"


def test_ingested_sale_has_vendor_and_purchaser_counts_from_d_records(
    sql_dest, weekly_zip_file
):
    ingest_zip(sql_dest, weekly_zip_file, "https://example.com/weekly_sample.zip")

    counts = sql_dest._conn.execute(
        "SELECT vendor_count, purchaser_count FROM sale WHERE property_id = 'PROP708A'"
    ).fetchone()
    assert counts == (1, 1)


def test_ingested_sales_searchable_via_fts(sql_dest, weekly_zip_file):
    ingest_zip(sql_dest, weekly_zip_file, "https://example.com/weekly_sample.zip")

    matches = sql_dest._conn.execute(
        """
        SELECT s.property_id
        FROM sale_fts f JOIN sale s ON s.rowid = f.rowid
        WHERE sale_fts MATCH 'STREET'
        """
    ).fetchall()
    assert matches == [("PROP708A",)]


@pytest.fixture
def annual_zip_file(tmp_path) -> Path:
    week_001_buf = BytesIO()
    with zipfile.ZipFile(week_001_buf, "w") as inner_zf:
        inner_zf.writestr("001.DAT", WEEKLY_DAT_001)

    week_708_buf = BytesIO()
    with zipfile.ZipFile(week_708_buf, "w") as inner_zf:
        inner_zf.writestr("708.DAT", WEEKLY_DAT_708)

    annual_path = tmp_path / "annual_sample.zip"
    with zipfile.ZipFile(annual_path, "w") as outer_zf:
        outer_zf.writestr("week_001.zip", week_001_buf.getvalue())
        outer_zf.writestr("week_708.zip", week_708_buf.getvalue())
    return annual_path


def test_ingest_zip_handles_annual_zips_containing_weekly_zips(
    sql_dest, annual_zip_file
):
    ingest_zip(sql_dest, annual_zip_file, "https://example.com/annual_sample.zip")

    count = sql_dest.sale_count()
    assert count == 3


OLD_DAT_001 = """\
B;001;VALNET1;0001234567890;42;;13;EXAMPLE ST;CESSNOCK;2325;01/01/1990;75000;NOTES;500;M;;;A;;;;
B;001;ARCHIVE;0009876543210;;;;PARISH RD;NOWHERE;2325;01/02/1990;120000;NOTES;250.5;M;;;A;;;;
Z;3;2;;
"""


@pytest.fixture
def old_format_zip_file(tmp_path) -> Path:
    zip_path = tmp_path / "1990.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("ARCHIVE_SALES_1990.DAT", OLD_DAT_001)
    return zip_path


def test_ingest_zip_handles_old_format_data(sql_dest, old_format_zip_file):
    ingest_zip(sql_dest, old_format_zip_file, "https://example.com/1990.zip")

    rows = sql_dest._conn.execute(
        "SELECT property_id, source_format, contract_date, purchase_price "
        "FROM sale ORDER BY property_id"
    ).fetchall()
    assert rows == [
        ("0009876543210", "old", "1990-02-01", 120000),
        ("42", "old", "1990-01-01", 75000),
    ]


UNKNOWN_DISTRICT_DAT = """\
B;999;VALNET1;0001234567890;42;;13;EXAMPLE ST;NOWHEREVILLE;2999;15/06/1990;75000;NOTES;500;M;;;A;;;;
Z;2;1;;
"""

UNKNOWN_DISTRICT_WITHOUT_LOCALITY_DAT = """\
B;225;ARCHIVE;0469270014000;;;;;;2176;23/07/1990;59000;LOT 1-8 SP 37404.;0;M;;;A;;;
Z;1;1;;
"""


def test_ingest_creates_district_if_missing(sql_dest, tmp_path):
    zip_path = tmp_path / "1990.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("ARCHIVE_SALES_1990.DAT", UNKNOWN_DISTRICT_DAT)

    ingest_zip(sql_dest, zip_path, "https://example.com/1990.zip")

    district = sql_dest._conn.execute(
        "SELECT code, name FROM district WHERE code = '999'"
    ).fetchone()
    sale_count = sql_dest.sale_count()

    assert district == ("999", "NOWHEREVILLE")
    assert sale_count == 1


def test_ingest_creates_district_if_missing_without_locality(sql_dest, tmp_path):
    zip_path = tmp_path / "1990.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("ARCHIVE_SALES_1990.DAT", UNKNOWN_DISTRICT_WITHOUT_LOCALITY_DAT)

    ingest_zip(sql_dest, zip_path, "https://example.com/1990.zip")

    district = sql_dest._conn.execute(
        "SELECT code, name FROM district WHERE code = '225'"
    ).fetchone()
    sale_count = sql_dest._conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]

    assert district == ("225", "225")
    assert sale_count == 1


def test_ingest_creates_zone_if_missing(sql_dest, tmp_path):
    zip_path = tmp_path / "1990.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "ARCHIVE_SALES_1990.DAT",
            "B;001;VALNET1;0001234567890;42;;13;EXAMPLE ST;CESSNOCK;2325;15/06/1990;75000;NOTES;500;M;;;ZZZ;;;;;\nZ;2;1;;\n",
        )

    ingest_zip(sql_dest, zip_path, "https://example.com/1990.zip")

    zone = sql_dest._conn.execute(
        "SELECT code, name FROM zone WHERE code = 'ZZZ'"
    ).fetchone()
    sale_count = sql_dest._conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]

    assert zone == ("ZZZ", "ZZZ")
    assert sale_count == 1


def test_ingest_old_format_handles_large_fields(sql_dest, tmp_path):
    zip_path = tmp_path / "1991.zip"
    long_legal_description = "X" * 200000
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "ARCHIVE_SALES_1991.DAT",
            f"B;001;ARCHIVE;0009876543210;;;;PARISH RD;NOWHERE;2325;01/02/1991;120000;{long_legal_description};250.5;M;;;A;;;;\nZ;1;1;;\n",
        )

    ingest_zip(sql_dest, zip_path, "https://example.com/1991.zip")

    row = sql_dest._conn.execute(
        "SELECT LENGTH(legal_description), property_id FROM sale"
    ).fetchone()

    assert row == (200000, "0009876543210")


def test_ingest_old_format_treats_quotes_as_literal(sql_dest, tmp_path):
    zip_path = tmp_path / "1991.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "ARCHIVE_SALES_1991.DAT",
            """\
B;001;VALNET1;0001234567890;42;;13;EXAMPLE ST;CESSNOCK;2325;01/01/1991;75000;NOTES WITH "QUOTE;500;M;;;A;;;;
B;001;ARCHIVE;0009876543210;;;;PARISH RD;NOWHERE;2325;01/02/1991;120000;NOTES;250.5;M;;;A;;;;
Z;2;2;;
""",
        )

    ingest_zip(sql_dest, zip_path, "https://example.com/1991.zip")

    rows = sql_dest._conn.execute(
        "SELECT property_id, legal_description FROM sale ORDER BY property_id"
    ).fetchall()

    assert rows == [
        ("0009876543210", "NOTES"),
        ("42", 'NOTES WITH "QUOTE'),
    ]


def test_ingest_new_format_keeps_distinct_sales_with_same_source_key(
    sql_dest, tmp_path
):
    zip_path = tmp_path / "2002.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "085.DAT",
            """\
A;RTSALEDATA;085;202601051200;TESTUSER
B;085;720968;3;20260105 12:00;;13;25;EXAMPLE ST;SYDNEY;2000;;M;20011206;20020117;382000;;R;RESIDENCE;;;XA;0;987654
C;085;720968;3;20260105 12:00;13/SP18756
D;085;720968;3;20260105 12:00;P
D;085;720968;3;20260105 12:00;V
B;085;720968;3;20260105 12:00;;19;25;EXAMPLE ST;SYDNEY;2000;;M;20020113;20020301;375000;;R;RESIDENCE;;;;;123456
C;085;720968;3;20260105 12:00;19//18756
D;085;720968;3;20260105 12:00;P
D;085;720968;3;20260105 12:00;P
D;085;720968;3;20260105 12:00;V
D;085;720968;3;20260105 12:00;V
Z;2;2;3;3
""",
        )

    ingest_zip(sql_dest, zip_path, "https://example.com/2002.zip")

    rows = sql_dest._conn.execute(
        """
        SELECT unit_number, contract_date, dealing_number, purchase_price
        FROM sale
        WHERE district_code = '085' AND property_id = '720968' AND sale_counter = '3'
        ORDER BY unit_number
        """
    ).fetchall()

    assert rows == [
        ("13", "2001-12-06", "987654", 382000),
        ("19", "2002-01-13", "123456", 375000),
    ]


def test_ingest_new_format_dedupes_repeat_snapshots_with_equal_download_datetime(
    sql_dest, tmp_path
):
    zip_path = tmp_path / "2002.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "139.DAT",
            """\
A;RTSALEDATA;139;202601051200;TESTUSER
B;139;1447639;1;20260105 12:00;;;23;EXAMPLE ST;SYDNEY;2000;;M;20011218;20020122;560000;A;R;RESIDENCE;;ES;AC;0;123456
C;139;1447639;1;20260105 12:00;B/112233
D;139;1447639;1;20260105 12:00;P
D;139;1447639;1;20260105 12:00;V
B;139;1447639;1;20260105 12:00;;;;EXAMPLE ST;SYDNEY;2000;;M;20011218;20020122;560000;A;R;RESIDENCE;;ES;;;123456
C;139;1447639;1;20260105 12:00;B//112233
D;139;1447639;1;20260105 12:00;P
D;139;1447639;1;20260105 12:00;V
Z;1;1;2;3
""",
        )

    ingest_zip(sql_dest, zip_path, "https://example.com/2002.zip")

    rows = sql_dest._conn.execute(
        """
        SELECT house_number, sale_code, legal_description
        FROM sale
        WHERE district_code = '139' AND property_id = '1447639'
        """
    ).fetchall()

    assert rows == [("23", "AC", "B/112233")]


@pytest.fixture
def two_files_with_sale_records_for_the_same_sale_event(tmp_path) -> tuple[Path, Path]:
    data = """\
A;RTSALEDATA;001;202604011200;TESTUSER
B;001;15205;16;{date}:00;;;42;ROAD RD;CESSNOCK;2325;500;M;20161219;20170127;{amount};R1;R;;;;;0;AM117853
Z;3;1;0;0
"""
    earlier_zip = tmp_path / "earlier.zip"
    with zipfile.ZipFile(earlier_zip, "w") as zf:
        zf.writestr(
            "001.DAT",
            data.format(date="20260401 12:00", amount=12345),
        )

    later_zip = tmp_path / "later.zip"
    with zipfile.ZipFile(later_zip, "w") as zf:
        zf.writestr(
            "001.DAT",
            data.format(date="20260402 12:00", amount=54321),
        )
    return earlier_zip, later_zip


def test_ingest_zip_overwrites_records_with_events_that_were_created_after_current_record(
    sql_dest, two_files_with_sale_records_for_the_same_sale_event
):
    earlier_zip, later_zip = two_files_with_sale_records_for_the_same_sale_event
    ingest_zip(sql_dest, earlier_zip, "https://example.com/earlier.zip")
    ingest_zip(sql_dest, later_zip, "https://example.com/later.zip")

    row = sql_dest._conn.execute(
        "SELECT purchase_price FROM sale WHERE dealing_number = 'AM117853'"
    ).fetchone()

    assert row == (54321,)


def test_ingest_zip_ignores_records_that_were_created_earlier_than_existing_items_in_db(
    sql_dest, two_files_with_sale_records_for_the_same_sale_event
):
    earlier_zip, later_zip = two_files_with_sale_records_for_the_same_sale_event
    ingest_zip(sql_dest, later_zip, "https://example.com/later.zip")
    ingest_zip(sql_dest, earlier_zip, "https://example.com/earlier.zip")

    row = sql_dest._conn.execute(
        "SELECT purchase_price FROM sale WHERE dealing_number = 'AM117853'"
    ).fetchone()

    assert row == (54321,)


def test_ingest_new_format_keeps_bulk_strata_units_as_separate_rows(sql_dest, tmp_path):
    zip_path = tmp_path / "bulk.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "001.DAT",
            """\
A;RTSALEDATA;001;202608291200;TESTUSER
B;001;12422;24;20260829 12:00;;1;100;EXAMPLE ST;SYDNEY;2000;75;M;20140829;20140930;780000;R4;R;;;;;0;AJ80885
B;001;12422;25;20260829 12:00;;2;100;EXAMPLE ST;SYDNEY;2000;75;M;20140829;20140930;780000;R4;R;;;;;0;AJ80885
B;001;12422;26;20260829 12:00;;3;100;EXAMPLE ST;SYDNEY;2000;75;M;20140829;20140930;780000;R4;R;;;;;0;AJ80885
Z;5;3;0;0
""",
        )

    ingest_zip(sql_dest, zip_path, "https://example.com/bulk.zip")

    units = sql_dest._conn.execute(
        "SELECT unit_number FROM sale WHERE dealing_number = 'AJ80885' "
        "ORDER BY unit_number"
    ).fetchall()

    assert units == [("1",), ("2",), ("3",)]


def test_ingest_merges_duplicate_old_records(sql_dest, tmp_path):
    zip_path = tmp_path / "1990.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "ARCHIVE_SALES_1990.DAT",
            """\
B;001;ARCHIVE;1019900000000;12520;;91;MAIN ST;CESSNOCK;2325;30/11/1990;87000;Notes 1;854;M;;;A;;;;
B;001;ARCHIVE;1019900000000;12520;;91;MAIN STREET;CESSNOCK;2325;30/11/1990;87000;Notes 2;854;M;;HC;A;;;;
Z;3;2;;
""",
        )

    ingest_zip(sql_dest, zip_path, "https://example.com/1990.zip")

    rows = sql_dest._conn.execute(
        "SELECT property_id, street_name, legal_description, component_code FROM sale"
    ).fetchall()

    assert len(rows) == 1
    assert rows[0] == (
        "12520",
        "MAIN STREET",
        "Notes 1 | Notes 2",
        "HC",
    )


@pytest.mark.parametrize(
    ["purpose", "cleaned"],
    [
        ("Commerical un", "COMMERCIAL UNIT"),
        ("HOMLE & IJNIT", "HOME AND UNIT"),
        (" APT/CARSPACE,", "APARTMENT / CARSPACE"),
    ],
)
def test_it_cleans_purpose(purpose, cleaned):
    assert clean_purpose_from_purpose(purpose) == cleaned

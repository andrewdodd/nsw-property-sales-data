import sqlite3

import pytest

from nsw_property_sales_data import db


def test_create_database_creates_expected_tables(db_path):
    conn = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert {"district", "zone", "sale", "sale_fts", "loaded_zip"} <= tables


def test_create_database_seeds_all_districts(db_path):
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM district").fetchone()[0]
    sydney = conn.execute(
        "SELECT name FROM district WHERE code = ?", ("708",)
    ).fetchone()
    conn.close()
    assert count == 130
    assert sydney == ("CITY OF SYDNEY",)


def test_connect_enables_foreign_keys(db_path):
    conn = db.connect(db_path)
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.close()
    assert fk == 1


def test_foreign_key_constraint_rejects_unknown_district(db_path):
    conn = db.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sale (district_code, property_id, sale_counter, source_format) "
            "VALUES ('999', 'P1', 'S1', 'new')"
        )
    conn.close()


def test_create_database_seeds_all_zones(db_path):
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM zone").fetchone()[0]
    legacy_residential = conn.execute(
        "SELECT name, category, legacy_code FROM zone WHERE code = ?", ("A",)
    ).fetchone()
    lep_high_density = conn.execute(
        "SELECT name, category, legacy_code FROM zone WHERE code = ?", ("R4",)
    ).fetchone()
    conn.close()
    assert count == 53
    assert legacy_residential == ("Residential", "Residential", None)
    assert lep_high_density == ("High Density Residential", "Residential", "A")


def test_zone_legacy_code_resolves_to_legacy_zone(db_path):
    conn = db.connect(db_path)
    row = conn.execute(
        """
        SELECT lep.code, legacy.name, legacy.code
        FROM zone lep
        JOIN zone legacy ON legacy.code = lep.legacy_code
        WHERE lep.code = 'IN1'
        """
    ).fetchone()
    conn.close()
    assert row == ("IN1", "Industrial", "I")

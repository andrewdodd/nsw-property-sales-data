from dataclasses import astuple, replace
from datetime import date

import pytest

from nsw_property_sales_data import db
from nsw_property_sales_data.ingest import Sale
from nsw_property_sales_data.query import (
    AddressQuery,
    District,
    SalesQueryer,
    Zone,
    _SALE_COLUMNS,
)


_INSERT_SQL = f"""
    INSERT INTO sale (
        {_SALE_COLUMNS}
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


_BASE_SALE = Sale(
    district_code="708",
    property_id="P1",
    sale_counter="S1",
    property_name=None,
    unit_number=None,
    house_number="1",
    street_name="WALLABY WAY",
    locality="SYDNEY",
    postcode="2000",
    area_sqm=100.0,
    contract_date="2024-01-15",
    settlement_date=None,
    purchase_price=1_000_000,
    zoning=None,
    nature=None,
    purpose=None,
    purpose_original=None,
    component_code=None,
    sale_code=None,
    percent_interest=100,
    dealing_number=None,
    legal_description=None,
    vendor_count=None,
    purchaser_count=None,
    source_format="new",
    download_datetime=None,
)


def _sale(**overrides) -> Sale:
    return replace(_BASE_SALE, **overrides)


@pytest.fixture
def queryer(db_path):
    conn = db.connect(db_path)
    sales = [
        _sale(property_id="P1", sale_counter="S1", contract_date="2023-06-01"),
        _sale(property_id="P1", sale_counter="S2", contract_date="2024-06-01"),
        _sale(
            property_id="P2",
            sale_counter="S3",
            contract_date="2024-08-01",
            street_name="OTHER STREET",
            locality="OTHER SUBURB",
            postcode="2001",
        ),
    ]
    conn.executemany(_INSERT_SQL, [astuple(s) for s in sales])
    conn.commit()
    try:
        yield SalesQueryer(conn)
    finally:
        conn.close()


def test_by_postcode_filters_and_orders_by_contract_date(queryer):
    sales = queryer.by_postcode("2000")
    assert [s.sale_counter for s in sales] == ["S1", "S2"]


def test_by_postcode_respects_date_window(queryer):
    sales = queryer.by_postcode("2000", since=date(2024, 1, 1))
    assert [s.sale_counter for s in sales] == ["S2"]


def test_find_address_matches_case_insensitively(queryer):
    sales = queryer.find_address(AddressQuery(street="wallaby way"))
    assert {s.sale_counter for s in sales} == {"S1", "S2"}


def test_find_address_requires_at_least_one_field(queryer):
    with pytest.raises(ValueError):
        queryer.find_address(AddressQuery())


def test_search_address_uses_fts(queryer):
    sales = queryer.search_address("wallaby")
    assert {s.sale_counter for s in sales} == {"S1", "S2"}


def test_sales_for_property_returns_all_sales_for_same_property(queryer):
    seed = queryer.by_postcode("2000")[0]
    related = queryer.sales_for_property(seed)
    assert {s.sale_counter for s in related} == {"S1", "S2"}


def test_district_and_zone_lookup(queryer):
    assert queryer.district("708") == District(code="708", name="CITY OF SYDNEY")
    assert queryer.district("999") is None
    zone = queryer.zone("R4")
    assert isinstance(zone, Zone) and zone.name == "High Density Residential"

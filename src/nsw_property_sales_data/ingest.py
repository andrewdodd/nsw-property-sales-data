import csv
import re
import logging
from collections.abc import Iterable, Iterator
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from .protocols import Destination, Sale
from dateutil import parser as _date_parser


logger = logging.getLogger(__name__)


def _configure_csv_field_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


_configure_csv_field_limit()


def ingest_zip(dest: Destination, zip_path: Path, url: str) -> None:
    is_old_format = _is_old_format_filename(zip_path.name)
    try:
        dest.insert_zip(zip_path, url)
        with zipfile.ZipFile(zip_path) as zf:
            _process_zip(dest, zf, is_old_format)
        dest.commit()
    except:
        dest.rollback()
        raise


def _is_old_format_filename(filename: str) -> bool:
    # Yearly archives 1990-2000 are in the old format; everything else is in the new format
    stem = filename.removesuffix(".zip")
    return len(stem) == 4 and stem.isdigit() and int(stem) < 2001


def _process_zip(
    dest: Destination,
    zf: zipfile.ZipFile,
    is_old_format: bool,
    inner_loop: bool = False,
) -> None:
    start = datetime.now()
    sales_before = dest.sale_count()
    if inner_loop:
        log_enabled = logger.isEnabledFor(logging.DEBUG)
        log_function = logger.debug
    else:
        log_enabled = logger.isEnabledFor(logging.INFO)
        log_function = logger.info

    if log_enabled:
        log_function(f"  processing {zf.filename}")

    for name in zf.namelist():
        if name.endswith(".DAT"):
            logger.debug("  parsing %s", name)
            with zf.open(name) as f:
                text = f.read().decode("utf-8")
            member_is_old_format = _is_old_format_dat_text(text, is_old_format)
            _insert_sales_from_dat(dest, text, member_is_old_format)
        elif name.endswith(".zip"):
            logger.debug("  recursing into %s", name)
            with zf.open(name) as f:
                with zipfile.ZipFile(f) as inner_zf:
                    _process_zip(dest, inner_zf, is_old_format, inner_loop=True)
    if log_enabled:
        records_inserted = dest.sale_count() - sales_before
        elapsed_secs = (datetime.now() - start).total_seconds()
        rate = records_inserted / elapsed_secs
        log_function(
            f"  -> imported {records_inserted} records in {elapsed_secs:.2f} seconds ({rate:.2f} records/sec)"
        )


def _is_old_format_dat_text(text: str, default_is_old_format: bool) -> bool:
    for line in text.splitlines():
        if not line:
            continue
        fields = line.split(";")
        if fields[0] != "B":
            continue
        if len(fields) <= len(OldFormatSaleBuilder.B_RECORD_FIELDS):
            return True
        return fields[2] in {"VALNET1", "ARCHIVE"}
    return default_is_old_format


def _insert_sales_from_dat(dest: Destination, text: str, is_old_format: bool) -> None:
    rows = csv.reader(text.splitlines(), delimiter=";", quoting=csv.QUOTE_NONE)
    builder = OldFormatSaleBuilder() if is_old_format else NewFormatSaleBuilder()
    sales = list(builder.process_rows(rows))
    if not sales:
        return

    districts = {(s.district_code, s.locality or s.district_code) for s in sales}
    zones = {(s.zoning, s.zoning) for s in sales if s.zoning}

    dest.upsert_districts(districts)
    if zones:
        dest.upsert_zones(zones)
    dest.insert_sales(sales)


def convert_purchase_price(price: str | None) -> int | None:
    if price is None or price.strip() == "":
        return None

    return int(round(float(price)))


_WORD_FIXES = {
    "": None,
    ".": None,
    ",": None,
    "&": "AND",
    "COMMERICAL": "COMMERCIAL",
    "UNI": "UNIT",
    "UNITS": "UNIT",
    "SHOPS": "SHOP",
    "BLD": "BUILDING",
    "BLDG": "BUILDING",
    "BUI": "BUILDING",
    "OFFICES": "OFFICE",
    "FARMLANDS": "FARMLAND",
    "ABATTOIRS": "ABATTOIR",
    "ABBATOIR": "ABATTOIR",
    "ABBATOIRS": "ABATTOIR",
    "ABBATTOIR": "ABATTOIR",
    "ACCOMODATION": "ACCOMMODATION",
    "APT": "APARTMENT",
    "APPT": "APARTMENT",
    "HOOUSE": "HOUSE",
    "HOMEUMT": "HOME UNIT",
    "HOMEUNIT": "HOME UNIT",
    "HOMEUNITHOME": "HOME UNIT",
    "HOMEUNRT": "HOME UNIT",
    "IJNIT": "UNIT",
    "HOMF": "HOME",
    "HOMLE": "HOME",
    "HONE": "HOME",
    "HONIE": "HOME",
    "HOPSITAL": "HOSPITAL",
    "HORE": "HOME",
    "HOW": "HOME",
    "HOWE": "HOME",
    "HTOEL": "HOME",
    "HU": "HOME",
    "HUM": "HOME",
    "HUME": "HOME",
    "HUSE": "HOUSE",
    "HUSCS": "HOUSE",
    "HUNIT": "HOME UNIT",
    "LAN": "LAND",
    "ICOMMERCIAL": "COMMERCIAL",
    "IDOME": "HOME",
    "IDUSTRIAL": "INDUSTRIAL",
    "IINDUSTRIAL": "INDUSTRIAL",
    "ILLDUSTRIAL": "INDUSTRIAL",
    "INDISTRIAL": "INDUSTRIAL",
    "IND": "INDUSTRIAL",
    "INDUST": "INDUSTRIAL",
}


_PURPOSE_CANONICAL = {
    "COMMERCIAL UN": "COMMERCIAL UNIT",
    "COMMERCIAL UNI": "COMMERCIAL UNIT",
    "COMMERCIAL OF": "COMMERCIAL OFFICE",
    "INDUSTRIAL UN": "INDUSTRIAL UNIT",
    "SERVICE STATI": "SERVICE STATION",
    "FARM LAND": "FARMLAND",
    "RURAL LAND": "RURAL",
}


def fix_spelling(word: str) -> str | None:
    return _WORD_FIXES.get(word, word)


def clean_purpose_from_purpose(purpose: str | None) -> str | None:
    if not purpose:
        return None

    upper = purpose.upper().strip()
    parts = re.split(r"(\W+)", upper)
    parts = [p.strip() for p in parts]
    parts = map(fix_spelling, parts)
    parts = filter(None, parts)
    cleaned = " ".join(parts)
    return _PURPOSE_CANONICAL.get(cleaned, cleaned)


class NewFormatSaleBuilder:
    B_RECORD_FIELDS = (
        "record_type",
        "district_code",
        "property_id",
        "sale_counter",
        "download_datetime",
        "property_name",
        "unit_number",
        "house_number",
        "street_name",
        "locality",
        "postcode",
        "area",
        "area_type",
        "contract_date",
        "settlement_date",
        "purchase_price",
        "zoning",
        "nature",
        "purpose",
        "strata_lot_number",
        "component_code",
        "sale_code",
        "percent_interest",
        "dealing_number",
    )

    def __init__(self) -> None:
        self._current: dict[str, str] | None = None
        self._legal_parts: list[str] = []
        self._vendors = 0
        self._purchasers = 0

    def process_rows(self, rows: Iterable[list[str]]) -> Iterator[Sale]:
        for row in rows:
            if not row:
                continue
            sale = self.consume(row)
            if sale:
                yield sale
        final_sale = self.flush()
        if final_sale:
            yield final_sale

    def consume(self, fields: list[str]) -> Sale | None:
        rt = fields[0]
        if rt == "B":
            previous = self.flush()
            self._current = dict(zip(self.B_RECORD_FIELDS, fields))
            return previous
        elif rt == "C" and self._current and len(fields) > 5 and fields[5]:
            self._legal_parts.append(fields[5])
        elif rt == "D" and self._current and len(fields) > 5:
            if fields[5] == "P":
                self._purchasers += 1
            elif fields[5] == "V":
                self._vendors += 1
        return None

    def flush(self) -> Sale | None:
        if self._current is None:
            return None
        sale = Sale(
            district_code=self._current["district_code"],
            property_id=self._current["property_id"],
            sale_counter=self._current["sale_counter"],
            property_name=self._current["property_name"] or None,
            unit_number=self._current["unit_number"] or None,
            house_number=self._current["house_number"] or None,
            street_name=self._current["street_name"] or None,
            locality=self._current["locality"] or None,
            postcode=self._current["postcode"] or None,
            area_sqm=_convert_area(self._current["area"], self._current["area_type"]),
            contract_date=_parse_date(self._current["contract_date"]),
            settlement_date=_parse_date(self._current["settlement_date"]),
            purchase_price=convert_purchase_price(self._current["purchase_price"]),
            zoning=self._current["zoning"] or None,
            nature=self._current["nature"] or None,
            purpose=clean_purpose_from_purpose(self._current["purpose"] or None),
            purpose_original=self._current["purpose"] or None,
            component_code=self._current["component_code"] or None,
            sale_code=self._current["sale_code"] or None,
            percent_interest=int(self._current.get("percent_interest") or 100),
            dealing_number=self._current["dealing_number"] or None,
            legal_description="".join(self._legal_parts) or None,
            vendor_count=self._vendors,
            purchaser_count=self._purchasers,
            source_format="new",
            download_datetime=_parse_datetime(self._current["download_datetime"]),
        )
        self._current = None
        self._legal_parts = []
        self._vendors = 0
        self._purchasers = 0
        return sale


class OldFormatSaleBuilder:
    B_RECORD_FIELDS = (
        "record_type",
        "district_code",
        "source",
        "valuation_num",
        "property_id",
        "unit_num",
        "house_num",
        "street_name",
        "suburb_name",
        "postcode",
        "contract_date",
        "purchase_price",
        "land_description",
        "area",
        "area_type",
        "dimensions",
        "comp_code",
        "zone_code",
        "vendor_name",
        "purchaser_name",
    )

    def process_rows(self, rows: Iterable[list[str]]) -> Iterator[Sale]:
        records = {}
        for row in rows:
            if not row or row[0] != "B":
                continue
            b = dict(zip(self.B_RECORD_FIELDS, row))
            property_id = b["property_id"] or b["valuation_num"]
            contract_date = _parse_date(b["contract_date"], dayfirst=True)
            purchase_price = convert_purchase_price(b["purchase_price"])
            # Some records appear to have purchase prices that are above $1 billion.
            # These all look like they are 1_000_000 times too high. Correct them here
            if purchase_price is not None and purchase_price > 1_000_000_000:
                purchase_price = int(purchase_price / 1_000_000)
            sale = Sale(
                district_code=b["district_code"],
                property_id=property_id,
                sale_counter=contract_date or property_id,
                property_name=None,
                unit_number=b["unit_num"] or None,
                house_number=b["house_num"] or None,
                street_name=b["street_name"] or None,
                locality=b["suburb_name"] or None,
                postcode=b["postcode"] or None,
                area_sqm=_convert_area(b["area"], b["area_type"]),
                contract_date=contract_date,
                settlement_date=None,
                purchase_price=purchase_price,
                zoning=b["zone_code"] or None,
                nature=None,
                purpose=None,
                purpose_original=None,
                component_code=b["comp_code"] or None,
                sale_code=None,
                percent_interest=100,
                dealing_number=None,
                legal_description=b["land_description"] or None,
                vendor_count=None,
                purchaser_count=None,
                source_format="old",
                download_datetime=None,
            )
            key = sale.key()
            records[key] = records.get(key, sale).combine_from(sale)

        for record in records.values():
            yield record


def _convert_area(value: str, unit: str) -> float | None:
    if not value:
        return None
    area = float(value)
    if unit == "H":
        area *= 10000.0
    return area


def _parse_date(value: str, *, dayfirst: bool = False) -> str | None:
    if not value:
        return None
    return _date_parser.parse(value, dayfirst=dayfirst).date().isoformat()


def _parse_datetime(value: str) -> str | None:
    if not value:
        return None
    return _date_parser.parse(value).isoformat()

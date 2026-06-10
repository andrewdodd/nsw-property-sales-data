import sqlite3
from pathlib import Path
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from .ingest import Sale
from .db import connect


_SALE_COLUMNS = (
    "district_code, property_id, sale_counter, "
    "property_name, unit_number, house_number, street_name, locality, postcode, "
    "area_sqm, contract_date, settlement_date, purchase_price, "
    "zoning, nature, purpose, purpose_original,"
    "component_code, sale_code, percent_interest, dealing_number, "
    "legal_description, vendor_count, purchaser_count, "
    "source_format, download_datetime"
)


@dataclass(frozen=True, slots=True)
class AddressQuery:
    street: str | None = None
    locality: str | None = None
    postcode: str | None = None
    house_number: str | None = None
    unit_number: str | None = None


@dataclass(frozen=True, slots=True)
class District:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class Zone:
    code: str
    name: str
    category: str | None
    legacy_code: str | None


class SalesQueryer:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def from_db_path(cls, path: Path):
        return SalesQueryer(connect(path))

    def by_property(
        self, property_id: str, *, district_code: str | None = None
    ) -> list[Sale]:
        clauses = ["property_id = ?"]
        params: list[object] = [property_id]
        if district_code is not None:
            clauses.append("district_code = ?")
            params.append(district_code)
        sql = (
            f"SELECT {_SALE_COLUMNS} FROM sale WHERE "
            + " AND ".join(clauses)
            + " ORDER BY contract_date"
        )
        return self._fetch(sql, params)

    def by_postcode(
        self,
        postcode: str,
        *,
        since: date | None = None,
        until: date | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Sale]:
        return self._by_column(
            "postcode", postcode, since=since, until=until, limit=limit, offset=offset
        )

    def by_locality(
        self,
        locality: str,
        *,
        since: date | None = None,
        until: date | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Sale]:
        return self._by_column(
            "locality", locality, since=since, until=until, limit=limit, offset=offset
        )

    def by_district(
        self,
        district_code: str,
        *,
        since: date | None = None,
        until: date | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Sale]:
        return self._by_column(
            "district_code",
            district_code,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )

    def search_address(
        self, text: str, *, limit: int = 50, offset: int | None = None
    ) -> list[Sale]:
        columns = ", ".join(f"sale.{c.strip()}" for c in _SALE_COLUMNS.split(","))
        sql = (
            f"SELECT {columns} FROM sale_fts "
            "JOIN sale ON sale.rowid = sale_fts.rowid "
            "WHERE sale_fts MATCH ? "
            "LIMIT ?"
        )
        params: list[object] = [text, limit]
        if offset is not None:
            sql += " OFFSET ?"
            params.append(offset)
        return self._fetch(sql, params)

    def find_address(
        self,
        query: AddressQuery,
        *,
        since: date | None = None,
        until: date | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Sale]:
        clauses: list[str] = []
        params: list[object] = []
        if query.street is not None:
            clauses.append("street_name = ? COLLATE NOCASE")
            params.append(query.street)
        if query.locality is not None:
            clauses.append("locality = ? COLLATE NOCASE")
            params.append(query.locality)
        if query.postcode is not None:
            clauses.append("postcode = ?")
            params.append(query.postcode)
        if query.house_number is not None:
            clauses.append("house_number = ? COLLATE NOCASE")
            params.append(query.house_number)
        if query.unit_number is not None:
            clauses.append("unit_number = ? COLLATE NOCASE")
            params.append(query.unit_number)
        if not clauses:
            raise ValueError("AddressQuery must have at least one field set")
        if since is not None:
            clauses.append("contract_date >= ?")
            params.append(since.isoformat())
        if until is not None:
            clauses.append("contract_date <= ?")
            params.append(until.isoformat())
        sql = (
            f"SELECT {_SALE_COLUMNS} FROM sale WHERE "
            + " AND ".join(clauses)
            + " ORDER BY contract_date"
        )
        sql, params = _apply_limit_offset(sql, params, limit, offset)
        return self._fetch(sql, params)

    def sales_for_property(self, sale: Sale) -> list[Sale]:
        return self.by_property(sale.property_id, district_code=sale.district_code)

    def district(self, code: str) -> District | None:
        row = self._conn.execute(
            "SELECT code, name FROM district WHERE code = ?", (code,)
        ).fetchone()
        return District(*row) if row else None

    def zone(self, code: str) -> Zone | None:
        row = self._conn.execute(
            "SELECT code, name, category, legacy_code FROM zone WHERE code = ?",
            (code,),
        ).fetchone()
        return Zone(*row) if row else None

    def _by_column(
        self,
        column: str,
        value: str,
        *,
        since: date | None,
        until: date | None,
        limit: int | None,
        offset: int | None,
    ) -> list[Sale]:
        clauses = [f"{column} = ?"]
        params: list[object] = [value]
        if since is not None:
            clauses.append("contract_date >= ?")
            params.append(since.isoformat())
        if until is not None:
            clauses.append("contract_date <= ?")
            params.append(until.isoformat())
        sql = (
            f"SELECT {_SALE_COLUMNS} FROM sale WHERE "
            + " AND ".join(clauses)
            + " ORDER BY contract_date"
        )
        sql, params = _apply_limit_offset(sql, params, limit, offset)
        return self._fetch(sql, params)

    def _fetch(self, sql: str, params: Sequence[object]) -> list[Sale]:
        return [Sale(*row) for row in self._conn.execute(sql, params)]


def _apply_limit_offset(
    sql: str, params: list[object], limit: int | None, offset: int | None
) -> tuple[str, list[object]]:
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
        if offset is not None:
            sql += " OFFSET ?"
            params.append(offset)
    elif offset is not None:
        # SQLite requires LIMIT before OFFSET; -1 means "no limit"
        sql += " LIMIT -1 OFFSET ?"
        params.append(offset)
    return sql, params

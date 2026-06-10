from dataclasses import dataclass, replace
from typing import Self, Protocol
from pathlib import Path
from typing import ContextManager


@dataclass(frozen=True)
class Sale:
    district_code: str
    property_id: str
    sale_counter: str
    property_name: str | None
    unit_number: str | None
    house_number: str | None
    street_name: str | None
    locality: str | None
    postcode: str | None
    area_sqm: float | None
    contract_date: str | None
    settlement_date: str | None
    purchase_price: float | None
    zoning: str | None
    nature: str | None
    purpose: str | None
    purpose_original: str | None
    component_code: str | None
    sale_code: str | None
    percent_interest: int
    dealing_number: str | None
    legal_description: str | None
    vendor_count: int | None
    purchaser_count: int | None
    source_format: str
    download_datetime: str | None

    def key(self) -> tuple[str, str, str]:
        return self.district_code, self.property_id, self.sale_counter

    def combine_from(self, other: Self) -> Self:
        if self is other or self == other:
            return self

        assert self.district_code == other.district_code, (
            "Combining from sale in different district"
        )
        assert self.property_id == other.property_id, (
            "Combining from sale in with different property_id"
        )
        assert self.sale_counter == other.sale_counter, (
            "Combining from sale with different sale_counter"
        )

        return replace(
            self,
            street_name=max(self.street_name or "", other.street_name or "", key=len),
            component_code=max(
                self.component_code or "", other.component_code or "", key=len
            ),
            legal_description=" | ".join(
                filter(None, (v.legal_description or None for v in [self, other]))
            ),
        )


class Destination(Protocol):
    def already_loaded_zips(self) -> set[str]: ...
    def sale_count(self) -> int: ...
    def upsert_districts(self, districts: set[tuple[str, str]]) -> None: ...
    def upsert_zones(self, zones: set[tuple[str, str]]) -> None: ...
    def insert_sales(self, sales: list[Sale]) -> None: ...
    def insert_zip(self, zip_path: Path, url: str) -> None: ...
    def commit(self):
        pass

    def rollback(self):
        pass


DestinationProvider = ContextManager[Destination]


class MultipleDestinations(Destination):
    def __init__(self, destinations: list[Destination]):
        self.destinations = destinations

    def already_loaded_zips(self) -> set[str]:
        return {z for d in self.destinations for z in d.already_loaded_zips()}

    def sale_count(self) -> int:
        counts = {d.sale_count() for d in self.destinations}
        return max(counts)

    def upsert_districts(self, districts: set[tuple[str, str]]):
        for d in self.destinations:
            d.upsert_districts(districts)

    def upsert_zones(self, zones: set[tuple[str, str]]):
        for d in self.destinations:
            d.upsert_zones(zones)

    def insert_sales(self, sales: list[Sale]):
        for d in self.destinations:
            d.insert_sales(sales)

    def insert_zip(self, zip_path: Path, url: str):
        for d in self.destinations:
            d.insert_zip(zip_path, url)

    def commit(self):
        for d in self.destinations:
            d.commit()

    def rollback(self):
        for d in self.destinations:
            d.rollback()

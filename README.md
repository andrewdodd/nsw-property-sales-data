# nsw-property-sales-data

A Python library for working with NSW Valuer General Property Sales Information (PSI) data, published as weekly and yearly bulk dumps going back to 1990.

This library fetches the source ZIPs, parses the `.DAT` files, and exposes the contents through a queryable SQLite database.

## Requirements

- Python 3.12+
- A `sqlite3` module backed by **libsqlite3 ≥ 3.24** and compiled with **FTS5** support.
- 3+ GBs of disk space - the SQLite from 1990 takes 2 GBs.

Both are standard on current macOS/Linux Pythons. If your Python is older or built without FTS5, connecting fails with a message saying so.

## Installation

Install from PyPI:

```sh
pip install nsw-property-sales-data
```

## Syncing the database

Run `sync_db <database-path>` to create the database (if it doesn't exist) and populate it with all available sales data.

For example, if installed:

```sh
sync_db ./the-data.db
```

Or if using a tool like `uv`:

```sh
uv run sync_db ./the-data.db
```

This command:

1. Lists the available information from the [NSW Valuer General](https://valuation.property.nsw.gov.au/embed/propertySalesInformation).
1. Downloads any new ZIPs not yet in the local cache directory.
1. Ingests any unprocessed ZIPs into the database provided.

Re-run `sync_db` against the same database to pull in newly released data (the NSW Valuer General publishes updates weekly).

For more information run `sync_db --help`.

## Querying the data

For ad-hoc analysis, the sqlite3 CLI is the most direct way to query the database:

```sql
sqlite3 ./the-data.db -box <<'SQL'
SELECT
    contract_date,
    coalesce(unit_number || '/', '') || house_number || ' ' || street_name AS address,
    printf('$%,d', purchase_price) AS price,
    area_sqm,
    CASE WHEN area_sqm > 0
         THEN printf('$%,d', purchase_price / area_sqm)
    END AS price_per_sqm,
    purpose
FROM sale
WHERE locality = 'BONDI'
  AND contract_date >= '2025-06-01'
  AND purchase_price IS NOT NULL
ORDER BY purchase_price DESC
LIMIT 10;
SQL
┌───────────────┬──────────────────┬─────────────┬──────────┬───────────────┬───────────┐
│ contract_date │     address      │    price    │ area_sqm │ price_per_sqm │  purpose  │
├───────────────┼──────────────────┼─────────────┼──────────┼───────────────┼───────────┤
│ 2025-09-03    │ 21 WILGA ST      │ $23,554,827 │ 676.6    │ $34,813       │ RESIDENCE │
│ 2025-09-03    │ 20 SANDRIDGE ST  │ $11,777,413 │ 712.0    │ $16,541       │ RESIDENCE │
│ 2025-07-05    │ 44 IMPERIAL AVE  │ $9,100,000  │ 539.65   │ $16,862       │ RESIDENCE │
│ 2026-02-11    │ 6 JACKAMAN ST    │ $8,725,000  │ 505.28   │ $17,267       │ RESIDENCE │
│ 2025-11-05    │ 16 BOONARA AVE   │ $8,025,000  │ 557.33   │ $14,399       │ RESIDENCE │
│ 2025-11-21    │ 52 OCEAN ST S    │ $7,000,000  │ 448.9    │ $15,593       │ RESIDENCE │
│ 2025-11-21    │ 50 OCEAN ST S    │ $7,000,000  │ 455.3    │ $15,374       │ RESIDENCE │
│ 2025-10-17    │ 1 OCEAN ST N     │ $6,900,000  │ 626.0    │ $11,022       │ RESIDENCE │
│ 2025-08-14    │ 9 DUDLEY ST      │ $6,700,000  │ 233.9    │ $28,644       │ RESIDENCE │
│ 2026-02-23    │ 1/14 PENKIVIL ST │ $6,700,000  │          │               │ RESIDENCE │
└───────────────┴──────────────────┴─────────────┴──────────┴───────────────┴───────────┘
```

The `nsw_property_sales_data.query.SalesQueryer` demonstrates some ways to achieve this from Python.

```python
> python
Python 3.14.5 ... on darwin
Type "help", "copyright", "credits" or "license" for more information.
>>> from datetime import datetime, timedelta
>>> from nsw_property_sales_data.query import SalesQueryer
>>> eight_weeks_ago = datetime.now() - timedelta(days=8*7)
>>> q = SalesQueryer.from_db_path("./the-data.db")
>>> recent_sydney_city_sales = q.by_postcode("2000", since=eight_weeks_ago)
>>> for sale in recent_sydney_city_sales:
...     property_number = f"{sale.unit_number} / {sale.house_number}" if sale.unit_number else sale.house_number
...     area = f"{int(sale.area_sqm)} sqm = {round(sale.purchase_price / sale.area_sqm)} $/sqm" if sale.area_sqm else ""
...     print(f"{sale.contract_date}: {property_number:>12} {sale.street_name:<15} - ${sale.purchase_price:>10,} {area:>25}")
...
2026-04-16:   17 C / 171 GLOUCESTER ST   - $ 2,085,000
2026-04-17:     9 D / 88 BARANGAROO AVE  - $ 5,200,000       195 sqm = 26667 $/sqm
2026-04-17:    133 / 361 KENT ST         - $   970,000
2026-04-18:   1508 / 178 THOMAS ST       - $ 1,555,000       117 sqm = 13291 $/sqm
2026-04-20:   1602 / 116 BATHURST ST     - $ 3,425,000       116 sqm = 29526 $/sqm
2026-04-21:      1 / 257 CLARENCE ST     - $ 3,312,000
2026-04-21:   1404 / 362 PITT ST         - $   965,000
2026-04-21:          119 KING ST         - $19,000,000       53 sqm = 353818 $/sqm
2026-04-22:     78 A / 2 WATERMANS QY    - $32,500,000       491 sqm = 66191 $/sqm
2026-04-22:     303 / 21 BARANGAROO AVE  - $ 3,750,000
2026-04-23:    811 / 653 GEORGE ST       - $   435,000
2026-04-23:     1006 / 2 BOND ST         - $   790,000
2026-04-23:    3157 / 65 TUMBALONG BVD   - $ 1,825,000       115 sqm = 15870 $/sqm
2026-04-24:      18 / 44 BRIDGE ST       - $ 1,350,000        63 sqm = 21429 $/sqm
2026-04-24:   2502 / 393 PITT ST         - $   775,000
2026-04-24:   3009 / 117 BATHURST ST     - $ 1,170,000
2026-04-28:   1706 / 168 KENT ST         - $ 3,750,000
2026-04-29:     38 / 414 PITT ST         - $ 1,050,000
2026-04-29:    309 / 147 KING ST         - $   305,000
2026-05-01:     29 H / 6 WATERMANS QY    - $ 2,800,000       114 sqm = 24561 $/sqm
2026-05-01:   3102 / 199 CASTLEREAGH ST  - $ 2,450,000
2026-05-05:     55 / 251 CLARENCE ST     - $   140,000
...
```

## Development

```sh
uv sync                # install deps incl. dev group
uv run pytest          # run tests
uv run pyright         # type-check
uv run ruff check      # lint
uv run ruff format     # format
uv run mdformat .      # format markdown
```

## Data sources and licensing

This project ingests data published by the NSW Valuer General. **The code in this repository and the data it processes are under separate licenses — be aware of both.**

See `NOTICES.md` for the full attribution and license details.

In short:

- **The code** in this repository is licensed under the [MIT License](./LICENSE).
- **District codes/names** and **zone codes/descriptions** seeded into this repo are derived from NSW Valuer General fact sheets — © Crown in right of New South Wales through the Valuer General NSW, 2020. Licensed under Creative Commons Attribution 4.0.
- **The bulk Property Sales Information data files** (downloaded by this library at runtime) are licensed under **Creative Commons BY-NC-ND 4.0** — Attribution, Non-Commercial, No Derivatives.

The BY-NC-ND license on the sales data means downstream users of any database built with this library are bound by those terms. In particular: no commercial use, and no redistribution of a modified version.

For the official source and terms, see <https://valuation.property.nsw.gov.au/embed/propertySalesInformation>.

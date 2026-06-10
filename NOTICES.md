# Notices

This file records third-party attributions and the licensing terms applicable to the data shipped with — and processed by — this project.

The code in this repository is licensed separately (see `LICENSE`). The terms below apply to the **data**.

## NSW Valuer General — Property Sales Information

> © Crown in right of New South Wales through the Valuer General NSW, 2020.

Source: <https://valuation.property.nsw.gov.au/embed/propertySalesInformation>

### Fact-sheet derived data

The following files in this repository were transcribed from NSW Valuer General fact sheets:

| File                                            | Source document                                                                          |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `src/nsw_propery_sales_data/data/districts.csv` | `Property_Sales_Data_File_District_Codes_and_Names.pdf` (May 2020, ISSN 2203-1642)       |
| `src/nsw_propery_sales_data/data/zones.csv`     | `Property_Sales_Data_File_Zone_Codes_and_Descriptions_V2.pdf` (May 2020, ISSN 2203-1642) |

The fact sheets state they are licensed under a Creative Commons Attribution 4.0 licence. (Note: the PDFs include a URL pointing to `creativecommons.org/licenses/by-nd/4.0/au/`, which contradicts the textual "Attribution 4.0" wording. We treat the textual statement as authoritative; users with stricter compliance needs should consult NSW Valuer General directly.)

License: <https://creativecommons.org/licenses/by/4.0/>

### Bulk Property Sales Information data files

The `.zip` and `.DAT` files downloaded at runtime from <https://www.valuergeneral.nsw.gov.au/__psi/> contain the bulk Property Sales Information dataset.

License: **Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International (CC BY-NC-ND 4.0)** — <https://creativecommons.org/licenses/by-nc-nd/4.0/>

Per the NSW portal: *"Bulk PSI is available under open access licensing as part of the NSW Government Open Data Policy and is subject to the Creative Commons BY-NC-ND 4.0 Licence."*

Implications for users of this library:

- **Attribution**: any redistribution of the data (including a built database) must credit the NSW Valuer General as the source.
- **Non-Commercial**: the data may not be used for commercial purposes.
- **No Derivatives**: redistributing a modified or transformed version of the data is not permitted under this license. Loading the data into a database for personal or research use is generally fine; publishing a derived dataset is not.

This license travels with the data. Building a database with this library does not relicense the contents.

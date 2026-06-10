CREATE TABLE district (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE zone (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT,
    legacy_code TEXT REFERENCES zone(code)
);

CREATE TABLE loaded_zip (
    filename  TEXT PRIMARY KEY,
    url       TEXT NOT NULL,
    loaded_at TEXT NOT NULL
);

CREATE TABLE sale (
    district_code     TEXT NOT NULL REFERENCES district(code),
    property_id       TEXT NOT NULL,
    sale_counter      TEXT NOT NULL,
    contract_date     TEXT,
    settlement_date   TEXT,
    purchase_price    INTEGER,
    area_sqm          REAL,
    zoning            TEXT REFERENCES zone(code),
    nature            TEXT,
    purpose_original  TEXT,
    purpose           TEXT, -- cleaned
    unit_number       TEXT,
    house_number      TEXT,
    street_name       TEXT,
    locality          TEXT,
    postcode          TEXT,
    property_name     TEXT,
    legal_description TEXT,
    vendor_count      INTEGER,
    purchaser_count   INTEGER,
    dealing_number    TEXT,
    sale_code         TEXT,
    component_code    TEXT,
    percent_interest  INTEGER NOT NULL,
    source_format     TEXT NOT NULL CHECK (source_format IN ('new', 'old')),
    download_datetime TEXT,
    transaction_key   TEXT GENERATED ALWAYS AS (
        district_code || '|' || property_id || '|' ||
        coalesce(nullif(dealing_number, ''), ifnull(contract_date, '')) || '|' ||
        ifnull(unit_number, '')
    ) STORED UNIQUE
);

CREATE INDEX idx_sale_postcode      ON sale(postcode);
CREATE INDEX idx_sale_property      ON sale(property_id);
CREATE INDEX idx_sale_contract_date ON sale(contract_date);

CREATE VIRTUAL TABLE sale_fts USING fts5(
    street_name,
    locality,
    property_name,
    content='sale',
    content_rowid='rowid'
);

CREATE TRIGGER sale_after_insert AFTER INSERT ON sale BEGIN
    INSERT INTO sale_fts(rowid, street_name, locality, property_name)
    VALUES (new.rowid, new.street_name, new.locality, new.property_name);
END;

CREATE TRIGGER sale_after_delete AFTER DELETE ON sale BEGIN
    INSERT INTO sale_fts(sale_fts, rowid, street_name, locality, property_name)
    VALUES ('delete', old.rowid, old.street_name, old.locality, old.property_name);
END;

CREATE TRIGGER sale_after_update AFTER UPDATE ON sale BEGIN
    INSERT INTO sale_fts(sale_fts, rowid, street_name, locality, property_name)
    VALUES ('delete', old.rowid, old.street_name, old.locality, old.property_name);
    INSERT INTO sale_fts(rowid, street_name, locality, property_name)
    VALUES (new.rowid, new.street_name, new.locality, new.property_name);
END;

-- 01_staging.sql
-- Typed views over the cleaned frames registered by transform.py (raw_stock, raw_receipts,
-- raw_materials). Every later script reads only these views, so the column types are fixed
-- in one place: dates without time, identifiers as text, quantities as DOUBLE.

-- One row per date, material, plant and storage location (end-of-day stock).
CREATE OR REPLACE VIEW stg_stock AS
SELECT
    CAST(date AS DATE)                AS date,
    CAST(material_id AS VARCHAR)      AS material_id,
    CAST(plant AS VARCHAR)            AS plant,
    CAST(storage_location AS VARCHAR) AS storage_location,
    CAST(stock_qty AS DOUBLE)         AS stock_qty
FROM raw_stock;

-- One row per goods receipt. The storage location of a receipt is not needed for the
-- analysis, which works per material and plant.
CREATE OR REPLACE VIEW stg_receipts AS
SELECT
    CAST(date AS DATE)           AS date,
    CAST(material_id AS VARCHAR) AS material_id,
    CAST(plant AS VARCHAR)       AS plant,
    CAST(receipt_qty AS DOUBLE)  AS receipt_qty
FROM raw_receipts;

-- Material master per material and plant.
CREATE OR REPLACE VIEW stg_materials AS
SELECT
    CAST(material_id AS VARCHAR)    AS material_id,
    CAST(plant AS VARCHAR)          AS plant,
    CAST(unit_price_eur AS DOUBLE)  AS unit_price_eur,
    CAST(lead_time_days AS INTEGER) AS lead_time_days
FROM raw_materials;

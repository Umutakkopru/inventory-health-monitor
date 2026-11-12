-- 02_calendar_spine.sql
-- A complete calendar per storage location and per material-plant, with the snapshots
-- joined on. Gap days become explicit rows with a NULL stock instead of being absent.
--
-- Rule (Methodology, "missing days"): a material-plant-date is observed only when every
-- storage location whose range covers that date has a snapshot. A sum over only some
-- locations would look like a sudden drop in stock, so such a day is missing as a whole.

-- Table sloc_daily: every date from the first to the last snapshot of each storage
-- location, with its stock or NULL. Kept for the drill-down chart per storage location.
CREATE OR REPLACE TABLE sloc_daily AS
WITH
-- First and last snapshot date of each storage location.
sloc_range AS (
    SELECT material_id, plant, storage_location, MIN(date) AS first_date, MAX(date) AS last_date
    FROM stg_stock
    GROUP BY material_id, plant, storage_location
),
-- One row per storage location and calendar day inside its range.
sloc_calendar AS (
    SELECT
        material_id,
        plant,
        storage_location,
        CAST(UNNEST(generate_series(first_date, last_date, INTERVAL 1 DAY)) AS DATE) AS date
    FROM sloc_range
)
SELECT
    c.date,
    c.material_id,
    c.plant,
    c.storage_location,
    s.stock_qty,
    s.stock_qty IS NOT NULL AS is_observed
FROM sloc_calendar AS c
LEFT JOIN stg_stock AS s USING (date, material_id, plant, storage_location);

-- Table mp_spine: one row per material-plant and calendar day from its first to its last
-- snapshot, with the summed stock on observed days and NULL on missing days.
CREATE OR REPLACE TABLE mp_spine AS
WITH
-- First and last snapshot date of each material-plant.
mp_range AS (
    SELECT material_id, plant, MIN(date) AS first_date, MAX(date) AS last_date
    FROM stg_stock
    GROUP BY material_id, plant
),
mp_calendar AS (
    SELECT
        material_id,
        plant,
        CAST(UNNEST(generate_series(first_date, last_date, INTERVAL 1 DAY)) AS DATE) AS date
    FROM mp_range
),
-- Per day: how many storage locations cover it and how many of them reported.
coverage AS (
    SELECT
        material_id,
        plant,
        date,
        COUNT(*)         AS locations_covering,
        COUNT(stock_qty) AS locations_reported,
        SUM(stock_qty)   AS stock_sum
    FROM sloc_daily
    GROUP BY material_id, plant, date
)
SELECT
    c.material_id,
    c.plant,
    c.date,
    -- A day no storage location covers (between two location ranges) is missing too.
    COALESCE(v.locations_covering > 0 AND v.locations_reported = v.locations_covering, FALSE)
        AS is_observed,
    CASE
        WHEN v.locations_reported = v.locations_covering THEN v.stock_sum
    END AS stock_qty
FROM mp_calendar AS c
LEFT JOIN coverage AS v USING (material_id, plant, date);

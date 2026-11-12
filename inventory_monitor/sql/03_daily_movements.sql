-- 03_daily_movements.sql
-- One row per material, plant and date with stock, receipts and derived consumption.
--
-- Timing assumption (Methodology): a snapshot is the end-of-day stock, and receipts posted
-- on day t are already included in the stock of day t. For an observed date d whose
-- previous observed date is p:
--
--     outflow = stock(p) + sum(receipts over dates in (p, d]) - stock(d)
--     n       = number of days from p to d          (n = 1 when there is no gap)
--     every date in (p, d] gets consumption_raw = outflow / n,  is_imputed = (n > 1)
--
-- The first observed date of a material-plant has no previous snapshot, so its
-- consumption is NULL. The figure is net outflow: it includes scrap, transfers and
-- inventory corrections, which is why the UI calls it "derived consumption".

CREATE OR REPLACE TABLE daily_movements AS
WITH
-- Receipts summed per material, plant and posting date.
receipts_per_day AS (
    SELECT material_id, plant, date, SUM(receipt_qty) AS receipt_qty
    FROM stg_receipts
    GROUP BY material_id, plant, date
),
-- The calendar with receipts (zero when none) and a running receipt total, so that the
-- receipts of any interval (p, d] are a difference of two running totals.
with_receipts AS (
    SELECT
        s.material_id,
        s.plant,
        s.date,
        s.is_observed,
        s.stock_qty,
        COALESCE(r.receipt_qty, 0) AS receipt_qty,
        SUM(COALESCE(r.receipt_qty, 0)) OVER (
            PARTITION BY s.material_id, s.plant
            ORDER BY s.date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS receipts_running
    FROM mp_spine AS s
    LEFT JOIN receipts_per_day AS r USING (material_id, plant, date)
),
-- Observed dates only, each paired with the previous observed date p. LAG over this
-- filtered set skips the gap days, which is exactly the "previous observed date".
segments AS (
    SELECT
        material_id,
        plant,
        date AS segment_end,
        DATEDIFF('day', LAG(date) OVER w, date) AS segment_days,
        -- Rounded to 6 decimals: quantities carry at most a few decimals, and summing
        -- doubles leaves noise such as -5e-14 that would look like a negative outflow.
        ROUND(
            LAG(stock_qty) OVER w
                + (receipts_running - LAG(receipts_running) OVER w)
                - stock_qty,
            6
        ) AS outflow
    FROM with_receipts
    WHERE is_observed
    WINDOW w AS (PARTITION BY material_id, plant ORDER BY date)
),
-- Every calendar day belongs to the segment that ends at the next observed date on or
-- after it. FIRST_VALUE ... IGNORE NULLS over the following rows finds that date.
assigned AS (
    SELECT
        w.*,
        FIRST_VALUE(CASE WHEN w.is_observed THEN w.date END IGNORE NULLS) OVER (
            PARTITION BY w.material_id, w.plant
            ORDER BY w.date
            ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING
        ) AS segment_end,
        -- Last observed stock carried forward: for charts and for the stock at as_of only.
        LAST_VALUE(w.stock_qty IGNORE NULLS) OVER (
            PARTITION BY w.material_id, w.plant
            ORDER BY w.date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS stock_filled
    FROM with_receipts AS w
)
SELECT
    a.material_id,
    a.plant,
    a.date,
    a.stock_qty,
    a.stock_filled,
    a.receipt_qty,
    g.outflow / g.segment_days AS consumption_raw,
    -- GREATEST ignores NULL in DuckDB (GREATEST(NULL, 0) = 0), so the first day of a
    -- material would get 0 instead of NULL without this guard.
    CASE
        WHEN g.outflow IS NOT NULL THEN GREATEST(g.outflow / g.segment_days, 0)
    END AS consumption,
    a.is_observed,
    COALESCE(g.segment_days > 1, FALSE) AS is_imputed,
    COALESCE(g.outflow < 0, FALSE) AS is_negative_outflow
FROM assigned AS a
LEFT JOIN segments AS g USING (material_id, plant, segment_end);

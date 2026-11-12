-- 04_weekly_demand.sql
-- Derived consumption summed per material, plant and ISO week (Monday to Sunday).
--
-- Weekly rather than daily figures feed the variability (sigma_weekly) because weekends
-- have no demand: a daily standard deviation would mostly measure the weekly rhythm.
-- Only complete weeks (seven days with a consumption value) may enter the statistics;
-- the first and last week of a material are usually partial.

CREATE OR REPLACE TABLE weekly_demand AS
SELECT
    material_id,
    plant,
    CAST(date_trunc('week', date) AS DATE) AS week_start,
    SUM(consumption)                       AS demand,
    COUNT(consumption)                     AS days_with_value,
    COUNT(consumption) = 7                 AS is_complete
FROM daily_movements
GROUP BY material_id, plant, date_trunc('week', date);

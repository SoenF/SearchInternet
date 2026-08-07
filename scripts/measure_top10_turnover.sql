-- Acceptance criterion #1: "Over 7 consecutive days, the top-10 backlog's
-- overlap stays under 50%." This is a production-only, multi-day metric --
-- it cannot be satisfied by a unit test on day one, only by observing real
-- daily backlog_snapshots. Direction matters: LOW overlap is the healthy,
-- desired outcome here (per the spec's "NOUVEAUTE ET DIVERSITE" section, the
-- backlog must not converge to a fixed set) -- a persistently HIGH overlap
-- (stuck near 100%) is the failure mode this query is meant to catch.
--
-- Usage: run manually against the live database once at least 8 days of
-- backlog_snapshots exist. Not run automatically, not part of the test
-- suite, not imported by the app.
--
--   psql "$DATABASE_URL" -f scripts/measure_top10_turnover.sql

WITH distinct_days AS (
    SELECT DISTINCT window_end
    FROM backlog_snapshots
    WHERE window_end >= CURRENT_DATE - INTERVAL '7 days'
),
day_sequence AS (
    SELECT
        window_end,
        LAG(window_end) OVER (ORDER BY window_end) AS previous_day
    FROM distinct_days
),
top10 AS (
    SELECT window_end, opportunity_id
    FROM backlog_snapshots
    WHERE rank <= 10
)
SELECT
    ds.window_end AS day,
    ds.previous_day,
    count(*) AS today_top10_count,
    count(*) FILTER (WHERE prev.opportunity_id IS NOT NULL) AS overlap_count,
    round(
        100.0 * count(*) FILTER (WHERE prev.opportunity_id IS NOT NULL) / NULLIF(count(*), 0),
        1
    ) AS overlap_pct
FROM day_sequence ds
JOIN top10 today ON today.window_end = ds.window_end
LEFT JOIN top10 prev
    ON prev.window_end = ds.previous_day AND prev.opportunity_id = today.opportunity_id
WHERE ds.previous_day IS NOT NULL
GROUP BY ds.window_end, ds.previous_day
ORDER BY ds.window_end;

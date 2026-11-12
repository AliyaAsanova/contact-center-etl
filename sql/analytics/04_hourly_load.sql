-- Load by hour of day: when do customers wait the longest and hang up the most?
-- Used for staffing decisions (how many agents are needed in each hour).
WITH hourly AS (
    SELECT
        extract(hour FROM started_at)::int               AS hour_of_day,
        count(*)                                         AS total_calls,
        count(DISTINCT call_date)                        AS days_observed,
        avg(wait_seconds)                                AS avg_wait_seconds,
        percentile_cont(0.9) WITHIN GROUP (ORDER BY wait_seconds) AS p90_wait_seconds,
        avg((status = 'abandoned')::int)                 AS abandon_rate
    FROM core.fact_call
    GROUP BY 1
)
SELECT
    hour_of_day,
    round(total_calls::numeric / days_observed, 1)       AS avg_calls_per_day,
    round(avg_wait_seconds)                              AS avg_wait_seconds,
    round(p90_wait_seconds::numeric)                     AS p90_wait_seconds,
    round(100.0 * abandon_rate, 1)                       AS abandon_rate_pct,
    round(100.0 * total_calls / sum(total_calls) OVER (), 1) AS share_of_all_calls_pct,
    dense_rank() OVER (ORDER BY abandon_rate DESC)       AS worst_hour_rank
FROM hourly
ORDER BY hour_of_day;

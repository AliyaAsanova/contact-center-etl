-- Daily contact-center KPIs with a 7-day moving average.
--   service level  = share of ALL calls answered within 20 seconds (industry "80/20" target)
--   abandon rate   = share of callers who hung up before an agent answered
--   AHT            = average handling (talk) time of answered calls
WITH daily AS (
    SELECT
        call_date,
        count(*)                                                        AS total_calls,
        count(*) FILTER (WHERE status = 'answered')                     AS answered_calls,
        count(*) FILTER (WHERE status = 'abandoned')                    AS abandoned_calls,
        count(*) FILTER (WHERE status = 'answered' AND wait_seconds <= 20) AS answered_in_20s,
        avg(talk_seconds) FILTER (WHERE status = 'answered')            AS aht_seconds,
        avg(wait_seconds)                                               AS avg_wait_seconds
    FROM core.fact_call
    GROUP BY call_date
)
SELECT
    call_date,
    total_calls,
    answered_calls,
    round(100.0 * abandoned_calls / total_calls, 1)  AS abandon_rate_pct,
    round(100.0 * answered_in_20s / total_calls, 1)  AS service_level_pct,
    round(aht_seconds)                               AS aht_seconds,
    round(avg_wait_seconds)                          AS avg_wait_seconds,
    -- window functions: smooth out the weekday/weekend pattern
    round(avg(total_calls) OVER w7)                                   AS total_calls_ma7,
    round(avg(100.0 * answered_in_20s / total_calls) OVER w7, 1)      AS service_level_ma7_pct
FROM daily
WINDOW w7 AS (ORDER BY call_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
ORDER BY call_date;

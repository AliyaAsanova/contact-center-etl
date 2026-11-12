-- Repeat calls: the same customer calls again about the same topic within 24 hours.
-- A repeat call means the first contact did not solve the problem, so
--   FCR (first contact resolution) = 100 - repeat rate.
-- LAG() looks at the customer's previous answered call without a self-join.
WITH answered AS (
    SELECT
        f.call_id,
        f.customer_id,
        f.topic_id,
        f.started_at,
        lag(f.started_at) OVER (PARTITION BY f.customer_id, f.topic_id ORDER BY f.started_at)
            AS previous_call_at
    FROM core.fact_call f
    WHERE f.status = 'answered'
),
flagged AS (
    SELECT
        *,
        (previous_call_at IS NOT NULL
         AND started_at - previous_call_at <= interval '24 hours') AS is_repeat
    FROM answered
)
SELECT
    t.topic_name,
    count(*)                                             AS answered_calls,
    count(*) FILTER (WHERE is_repeat)                    AS repeat_calls,
    round(100.0 * count(*) FILTER (WHERE is_repeat) / count(*), 1)        AS repeat_rate_pct,
    round(100.0 - 100.0 * count(*) FILTER (WHERE is_repeat) / count(*), 1) AS fcr_pct,
    -- every repeat call costs agent time: estimate it with the topic's average talk time
    round(count(*) FILTER (WHERE is_repeat)
          * (SELECT avg(talk_seconds) FROM core.fact_call x
             WHERE x.topic_id = t.topic_id AND x.status = 'answered') / 3600.0, 1) AS agent_hours_on_repeats
FROM flagged f
JOIN core.dim_topic t USING (topic_id)
GROUP BY t.topic_id, t.topic_name
ORDER BY repeat_rate_pct DESC;

-- Month-over-month change in call volume for every topic.
-- A topic that grows faster than the rest points to a product or network problem.
WITH monthly AS (
    SELECT
        date_trunc('month', f.started_at)::date AS month,
        t.topic_name,
        count(*)                                AS calls
    FROM core.fact_call f
    JOIN core.dim_topic t USING (topic_id)
    GROUP BY 1, 2
)
SELECT
    month,
    topic_name,
    calls,
    lag(calls) OVER by_topic                                              AS calls_prev_month,
    round(100.0 * (calls - lag(calls) OVER by_topic) / lag(calls) OVER by_topic, 1) AS change_pct,
    round(100.0 * calls / sum(calls) OVER (PARTITION BY month), 1)        AS share_of_month_pct,
    sum(calls) OVER (PARTITION BY topic_name ORDER BY month)              AS calls_running_total
FROM monthly
WINDOW by_topic AS (PARTITION BY topic_name ORDER BY month)
ORDER BY topic_name, month;

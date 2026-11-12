-- Agent performance for the whole period, ranked inside each team.
-- Shows who is faster/slower than the team average and who resolves more on the first call.
WITH agent_stats AS (
    SELECT
        a.agent_id,
        a.full_name,
        a.team,
        count(*)                                 AS calls_handled,
        avg(f.talk_seconds)                      AS aht_seconds,
        avg(f.is_resolved::int)                  AS resolution_rate,
        avg(f.csat)                              AS avg_csat,
        count(f.csat)                            AS csat_responses
    FROM core.fact_call f
    JOIN core.dim_agent a USING (agent_id)
    WHERE f.status = 'answered'
    GROUP BY a.agent_id, a.full_name, a.team
)
SELECT
    team,
    agent_id,
    full_name,
    calls_handled,
    round(aht_seconds)                                              AS aht_seconds,
    round(aht_seconds - avg(aht_seconds) OVER (PARTITION BY team))  AS aht_vs_team_avg,
    round(100.0 * resolution_rate, 1)                               AS resolution_rate_pct,
    round(avg_csat, 2)                                              AS avg_csat,
    csat_responses,
    rank() OVER (PARTITION BY team ORDER BY resolution_rate DESC)   AS rank_in_team_by_resolution,
    ntile(4) OVER (ORDER BY aht_seconds)                            AS aht_quartile  -- 1 = fastest
FROM agent_stats
ORDER BY team, rank_in_team_by_resolution;

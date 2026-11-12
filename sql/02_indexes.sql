-- Indexes for the most common access paths.
-- docs/query_optimization.md shows the measured effect of each one.

-- Reports almost always filter by a date range
CREATE INDEX IF NOT EXISTS idx_fact_call_started_at
    ON core.fact_call (started_at);

-- Agent statistics for a period
CREATE INDEX IF NOT EXISTS idx_fact_call_agent_started
    ON core.fact_call (agent_id, started_at);

-- Customer history and the repeat-call search (LAG over customer_id, started_at)
CREATE INDEX IF NOT EXISTS idx_fact_call_customer_started
    ON core.fact_call (customer_id, started_at);

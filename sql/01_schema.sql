-- Database layout
--   staging : raw data exactly as it came from the source (everything is text)
--   core    : cleaned, typed, normalized data (star schema)
--   dq      : pipeline run log and data-quality check results

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS dq;

-- ---------- staging ----------
CREATE TABLE IF NOT EXISTS staging.calls_raw (
    call_id      text,
    customer_id  text,
    started_at   text,
    topic        text,
    region       text,
    channel      text,
    status       text,
    agent_id     text,
    wait_seconds text,
    talk_seconds text,
    is_resolved  text,
    csat         text
);

CREATE TABLE IF NOT EXISTS staging.agents_raw (
    agent_id  text,
    full_name text,
    team      text,
    hire_date text,
    shift     text
);

-- ---------- core: dimensions ----------
CREATE TABLE IF NOT EXISTS core.dim_agent (
    agent_id  text PRIMARY KEY,
    full_name text NOT NULL,
    team      text NOT NULL,
    hire_date date NOT NULL,
    shift     text NOT NULL CHECK (shift IN ('day', 'evening', 'night'))
);

CREATE TABLE IF NOT EXISTS core.dim_topic (
    topic_id   smallserial PRIMARY KEY,
    topic_name text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS core.dim_region (
    region_id   smallserial PRIMARY KEY,
    region_name text NOT NULL UNIQUE
);

-- ---------- core: fact ----------
CREATE TABLE IF NOT EXISTS core.fact_call (
    call_id      bigint PRIMARY KEY,
    customer_id  text      NOT NULL,
    started_at   timestamp NOT NULL,
    call_date    date      NOT NULL,
    agent_id     text      REFERENCES core.dim_agent (agent_id),
    topic_id     smallint  NOT NULL REFERENCES core.dim_topic (topic_id),
    region_id    smallint  NOT NULL REFERENCES core.dim_region (region_id),
    channel      text      NOT NULL CHECK (channel IN ('phone', 'chat')),
    status       text      NOT NULL CHECK (status IN ('answered', 'abandoned')),
    wait_seconds integer   NOT NULL CHECK (wait_seconds >= 0),
    talk_seconds integer   NOT NULL CHECK (talk_seconds >= 0),
    is_resolved  boolean   NOT NULL,
    csat         smallint  CHECK (csat BETWEEN 1 AND 5),
    loaded_at    timestamp NOT NULL DEFAULT now(),
    -- an answered call must have an agent, an abandoned call must not
    CONSTRAINT agent_matches_status CHECK ((status = 'answered') = (agent_id IS NOT NULL))
);

-- Rows that failed validation are kept, not silently dropped
CREATE TABLE IF NOT EXISTS core.rejected_call (
    rejected_id bigserial PRIMARY KEY,
    run_id      integer   NOT NULL,
    call_id     text,
    reason      text      NOT NULL,
    raw_row     jsonb     NOT NULL,
    rejected_at timestamp NOT NULL DEFAULT now()
);

-- ---------- dq ----------
CREATE TABLE IF NOT EXISTS dq.pipeline_run (
    run_id             serial PRIMARY KEY,
    started_at         timestamp NOT NULL DEFAULT now(),
    finished_at        timestamp,
    status             text NOT NULL DEFAULT 'running',
    rows_extracted     integer,
    duplicates_removed integer,
    rows_rejected      integer,
    rows_loaded        integer,
    rows_already_in_db integer
);

CREATE TABLE IF NOT EXISTS dq.check_result (
    check_id   bigserial PRIMARY KEY,
    run_id     integer NOT NULL REFERENCES dq.pipeline_run (run_id),
    check_name text    NOT NULL,
    severity   text    NOT NULL CHECK (severity IN ('critical', 'warning')),
    passed     boolean NOT NULL,
    observed   text,
    expected   text,
    checked_at timestamp NOT NULL DEFAULT now()
);

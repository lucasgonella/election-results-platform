BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version         INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS elections (
    id                  BIGSERIAL PRIMARY KEY,
    tse_election_code   INTEGER NOT NULL,
    round_number        SMALLINT NOT NULL,
    name                TEXT,
    election_date       DATE,
    environment         VARCHAR(20) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_elections_tse
        UNIQUE (tse_election_code, environment)
);

CREATE TABLE IF NOT EXISTS scopes (
    id              BIGSERIAL PRIMARY KEY,
    scope_type      VARCHAR(20) NOT NULL,
    code            VARCHAR(20) NOT NULL,
    uf              CHAR(2),
    name            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_scopes
        UNIQUE (scope_type, code)
);

CREATE TABLE IF NOT EXISTS offices (
    id              BIGSERIAL PRIMARY KEY,
    tse_code        INTEGER NOT NULL UNIQUE,
    name            VARCHAR(100) NOT NULL,
    seats           INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS candidates (
    id                  BIGSERIAL PRIMARY KEY,

    election_id         BIGINT NOT NULL
                        REFERENCES elections(id),

    scope_id            BIGINT NOT NULL
                        REFERENCES scopes(id),

    office_id           BIGINT NOT NULL
                        REFERENCES offices(id),

    tse_candidate_seq   BIGINT NOT NULL,
    ballot_number       INTEGER,

    name                TEXT NOT NULL,
    ballot_name         TEXT,

    birth_date          DATE,

    party_number        INTEGER,
    party_acronym       VARCHAR(50),
    party_name          TEXT,

    alliance_name       TEXT,

    candidate_status    TEXT,
    result_status       TEXT,
    elected             BOOLEAN,

    running_mates       JSONB NOT NULL DEFAULT '[]'::jsonb,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_candidate
        UNIQUE (
            election_id,
            scope_id,
            office_id,
            tse_candidate_seq
        )
);

CREATE TABLE IF NOT EXISTS collector_runs (
    id                  BIGSERIAL PRIMARY KEY,

    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,

    status              VARCHAR(20) NOT NULL DEFAULT 'running',

    source_url          TEXT NOT NULL,

    election_code       INTEGER,
    scope_code          VARCHAR(20),
    office_code         INTEGER,

    http_status         INTEGER,

    tse_idg             BIGINT,

    etag                TEXT,
    last_modified       TEXT,

    payload_sha256      CHAR(64),

    candidates_processed INTEGER NOT NULL DEFAULT 0,

    error_message       TEXT,

    CONSTRAINT chk_collector_status
        CHECK (
            status IN (
                'running',
                'success',
                'not_modified',
                'error'
            )
        )
);

CREATE TABLE IF NOT EXISTS scope_snapshots (
    id                      BIGSERIAL PRIMARY KEY,

    election_id             BIGINT NOT NULL
                            REFERENCES elections(id),

    scope_id                BIGINT NOT NULL
                            REFERENCES scopes(id),

    office_id               BIGINT NOT NULL
                            REFERENCES offices(id),

    collector_run_id        BIGINT
                            REFERENCES collector_runs(id),

    tse_idg                 BIGINT NOT NULL,

    generated_at            TIMESTAMPTZ,
    totalized_at            TIMESTAMPTZ,

    sections_total          BIGINT,
    sections_totalized      BIGINT,
    sections_percentage     NUMERIC(12,9),

    electorate_total        BIGINT,
    electorate_totalized    BIGINT,

    turnout                 BIGINT,
    turnout_percentage      NUMERIC(12,9),

    abstentions             BIGINT,
    abstention_percentage   NUMERIC(12,9),

    votes_total             BIGINT,

    candidate_valid_votes   BIGINT,
    valid_votes             BIGINT,

    blank_votes             BIGINT,
    null_votes              BIGINT,

    captured_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_scope_snapshot
        UNIQUE (
            election_id,
            scope_id,
            office_id,
            tse_idg
        )
);

CREATE TABLE IF NOT EXISTS candidate_result_snapshots (
    id                  BIGSERIAL PRIMARY KEY,

    scope_snapshot_id   BIGINT NOT NULL
                        REFERENCES scope_snapshots(id)
                        ON DELETE CASCADE,

    candidate_id        BIGINT NOT NULL
                        REFERENCES candidates(id),

    votes               BIGINT NOT NULL,

    vote_percentage     NUMERIC(12,9),

    candidate_status    TEXT,
    result_status       TEXT,
    elected             BOOLEAN,

    captured_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_candidate_snapshot
        UNIQUE (
            scope_snapshot_id,
            candidate_id
        )
);

CREATE INDEX IF NOT EXISTS idx_candidates_lookup
    ON candidates (
        election_id,
        scope_id,
        office_id
    );

CREATE INDEX IF NOT EXISTS idx_scope_snapshots_latest
    ON scope_snapshots (
        election_id,
        scope_id,
        office_id,
        captured_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_candidate_snapshots_history
    ON candidate_result_snapshots (
        candidate_id,
        captured_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_collector_runs_started
    ON collector_runs (
        started_at DESC
    );

INSERT INTO schema_migrations (
    version,
    name
)
VALUES (
    1,
    'initial_schema'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;

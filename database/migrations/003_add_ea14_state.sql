BEGIN;

CREATE TABLE IF NOT EXISTS ea14_state (
    id                  BIGSERIAL PRIMARY KEY,

    environment         VARCHAR(20) NOT NULL,
    cycle               VARCHAR(20) NOT NULL,

    election_code       INTEGER NOT NULL,
    round_number        SMALLINT NOT NULL,

    tse_idg             BIGINT,

    source_url          TEXT NOT NULL,

    etag                TEXT,
    last_modified       TEXT,
    payload_sha256      CHAR(64),

    payload             JSONB NOT NULL,

    captured_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_ea14_state
        UNIQUE (
            environment,
            cycle,
            election_code,
            round_number
        )
);

CREATE INDEX IF NOT EXISTS idx_ea14_state_updated
    ON ea14_state (
        environment,
        cycle,
        captured_at DESC
    );

INSERT INTO schema_migrations (
    version,
    name
)
VALUES (
    3,
    'add_ea14_state'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;

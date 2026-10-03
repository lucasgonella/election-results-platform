BEGIN;

CREATE TABLE IF NOT EXISTS ea20_batches (
    id                      BIGSERIAL PRIMARY KEY,

    environment             VARCHAR(20) NOT NULL,
    cycle                   VARCHAR(20) NOT NULL,

    election_code           INTEGER NOT NULL,
    round_number            SMALLINT NOT NULL,

    ea14_tse_idg            BIGINT,
    ea14_payload_sha256     VARCHAR(64) NOT NULL,
    ea14_source_url         TEXT NOT NULL,

    status                  VARCHAR(20) NOT NULL
                            DEFAULT 'pending',

    total_targets           INTEGER NOT NULL
                            DEFAULT 0,

    completed_targets       INTEGER NOT NULL
                            DEFAULT 0,

    created_at              TIMESTAMPTZ NOT NULL
                            DEFAULT NOW(),

    updated_at              TIMESTAMPTZ NOT NULL
                            DEFAULT NOW(),

    completed_at            TIMESTAMPTZ,

    CONSTRAINT chk_ea20_batch_status
        CHECK (
            status IN (
                'pending',
                'ready',
                'completed',
                'superseded'
            )
        ),

    CONSTRAINT uq_ea20_batch
        UNIQUE (
            environment,
            cycle,
            election_code,
            round_number,
            ea14_payload_sha256
        )
);

CREATE TABLE IF NOT EXISTS ea20_batch_items (
    id                  BIGSERIAL PRIMARY KEY,

    batch_id            BIGINT NOT NULL
                        REFERENCES ea20_batches(id)
                        ON DELETE CASCADE,

    scope_code          VARCHAR(20) NOT NULL,
    office_code         INTEGER NOT NULL,
    office_name         TEXT NOT NULL,

    source_url          TEXT NOT NULL,

    status              VARCHAR(20) NOT NULL
                        DEFAULT 'pending',

    attempts            INTEGER NOT NULL
                        DEFAULT 0,

    collector_run_id    BIGINT
                        REFERENCES collector_runs(id),

    last_error          TEXT,

    processed_at        TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL
                        DEFAULT NOW(),

    updated_at          TIMESTAMPTZ NOT NULL
                        DEFAULT NOW(),

    CONSTRAINT chk_ea20_batch_item_status
        CHECK (
            status IN (
                'pending',
                'success',
                'not_modified',
                'error'
            )
        ),

    CONSTRAINT uq_ea20_batch_item
        UNIQUE (
            batch_id,
            source_url
        )
);

CREATE INDEX IF NOT EXISTS idx_ea20_batches_active
    ON ea20_batches (
        environment,
        cycle,
        election_code,
        round_number,
        status
    );

CREATE INDEX IF NOT EXISTS idx_ea20_batch_items_pending
    ON ea20_batch_items (
        batch_id,
        status,
        id
    );

INSERT INTO schema_migrations (
    version,
    name
)
VALUES (
    4,
    'add_ea20_batches'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;

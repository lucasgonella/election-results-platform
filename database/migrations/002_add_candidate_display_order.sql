BEGIN;

ALTER TABLE candidates
    ADD COLUMN display_order INTEGER;

INSERT INTO schema_migrations (
    version,
    name
)
VALUES (
    2,
    'add_candidate_display_order'
)
ON CONFLICT (version) DO NOTHING;

COMMIT;

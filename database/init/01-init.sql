CREATE TABLE IF NOT EXISTS visit_events (
    id BIGSERIAL PRIMARY KEY,
    request_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_visit_events_created_at
ON visit_events (created_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    message TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_created_at
ON messages (created_at DESC);

INSERT INTO messages (message, instance_id)
SELECT 'Database initialized successfully.', 'postgres-init'
WHERE NOT EXISTS (
    SELECT 1
    FROM messages
    WHERE instance_id = 'postgres-init'
);


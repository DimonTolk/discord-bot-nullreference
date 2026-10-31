ALTER TABLE game_state ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS interaction_jobs (
    id TEXT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    season_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    response JSONB,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_until TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '14 minutes',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS interaction_jobs_pending ON interaction_jobs(status,lease_until);
ALTER TABLE news_outbox ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS game_state (
    guild_id BIGINT NOT NULL,
    season_id TEXT NOT NULL,
    state JSONB NOT NULL,
    PRIMARY KEY (guild_id, season_id)
);
CREATE TABLE IF NOT EXISTS game_events (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    season_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    actor_id BIGINT NOT NULL,
    action TEXT NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (guild_id, season_id, request_id)
);
CREATE TABLE IF NOT EXISTS flavour_overrides (
    guild_id BIGINT NOT NULL,
    season_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_by BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, season_id, key)
);
CREATE TABLE IF NOT EXISTS flavour_history (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    season_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    actor_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id BIGINT PRIMARY KEY,
    news_channel_id BIGINT
);
CREATE TABLE IF NOT EXISTS news_outbox (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    season_id TEXT NOT NULL,
    text_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    sent_at TIMESTAMPTZ
);

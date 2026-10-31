CREATE TABLE IF NOT EXISTS mafia_role_bindings (
    guild_id BIGINT NOT NULL,
    season_id TEXT NOT NULL,
    family TEXT NOT NULL,
    role_id BIGINT NOT NULL,
    updated_by BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id, season_id, family),
    UNIQUE (guild_id, season_id, role_id)
);
CREATE TABLE IF NOT EXISTS mafia_role_history (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    season_id TEXT NOT NULL,
    family TEXT NOT NULL,
    role_id BIGINT,
    actor_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

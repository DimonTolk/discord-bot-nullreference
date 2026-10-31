from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    token: str
    public_key: str
    application_id: str
    guild_id: str
    database_url: str
    season_id: str = "mafia-2027"

    @classmethod
    def from_env(cls, env):
        def value(key, default=""):
            return str(getattr(env, key, default) or default)

        result = cls(
            value("DISCORD_TOKEN"),
            value("DISCORD_PUBLIC_KEY"),
            value("DISCORD_APPLICATION_ID"),
            value("DISCORD_GUILD_ID"),
            value("DATABASE_URL"),
            value("SEASON_ID", "mafia-2027"),
        )
        if not result.token or not result.database_url or len(result.public_key) != 64:
            raise ValueError("Missing Worker secrets/settings")
        bytes.fromhex(result.public_key)
        if not result.application_id.isdecimal() or not result.guild_id.isdecimal():
            raise ValueError("Invalid Discord application/guild settings")
        if not 1 <= len(result.season_id) <= 80:
            raise ValueError("Invalid season setting")
        return result

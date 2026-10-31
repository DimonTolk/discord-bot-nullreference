from string import Template

from nullreference.themes.mafia.texts import DEFAULTS


class FlavourCatalog:
    def __init__(self, sql, guild, season):
        self.sql, self.guild, self.season = sql, guild, season
        self.defaults = DEFAULTS

    def validate(self, key, value):
        if key not in self.defaults:
            raise ValueError("Неизвестный ключ текста")
        template = Template(value)
        expected = set(Template(self.defaults[key]).get_identifiers())
        if not template.is_valid() or set(template.get_identifiers()) != expected:
            raise ValueError("Сохраните переменные: " + ", ".join(sorted(expected)))
        if not 1 <= len(value) <= 1400:
            raise ValueError("Текст должен содержать 1–1400 символов")

    async def get(self, key):
        if key not in self.defaults:
            raise ValueError("Неизвестный ключ текста")
        rows = await self.sql.query(
            "SELECT value FROM flavour_overrides WHERE guild_id=$1 AND season_id=$2 AND key=$3",
            [self.guild, self.season, key],
        )
        return rows[0]["value"] if rows else self.defaults[key]

    async def render(self, key, **values):
        return Template(await self.get(key)).substitute(**values)[:2000]

    async def set(self, key, value, actor):
        if key not in self.defaults:
            raise ValueError("Неизвестный ключ текста")
        if value is not None:
            self.validate(key, value)
            mutation = (
                "INSERT INTO flavour_overrides(guild_id,season_id,key,value,updated_by) "
                "VALUES ($1,$2,$3,$4,$5) ON CONFLICT (guild_id,season_id,key) DO UPDATE "
                "SET value=EXCLUDED.value,updated_by=EXCLUDED.updated_by,updated_at=now() RETURNING key"
            )
        else:
            mutation = (
                "DELETE FROM flavour_overrides WHERE guild_id=$1 AND season_id=$2 "
                "AND key=$3 RETURNING key"
            )
        await self.sql.query(
            f"WITH mutation AS ({mutation}) "
            "INSERT INTO flavour_history(guild_id,season_id,key,value,actor_id) VALUES ($1,$2,$3,$4,$5)",
            [self.guild, self.season, key, value, actor],
        )

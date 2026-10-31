from nullreference.core.theme import RuleError
from nullreference.core.http import ServiceError

from .rules import FAMILIES


class MafiaMembership:
    def __init__(self, sql, guild, season):
        self.sql, self.guild, self.season = sql, guild, season

    @staticmethod
    def resolve(role_ids, bindings):
        roles = {str(r) for r in role_ids}
        families = {family for family, role in bindings.items() if str(role) in roles}
        if not families:
            raise RuleError("Нет роли семьи или полиции. Обратитесь к организатору: /family_role.")
        if len(families) != 1:
            raise RuleError("У вас роли нескольких сторон. Оставьте ровно одну игровую роль.")
        return families.pop()

    async def bindings(self):
        rows = await self.sql.query(
            "SELECT family,role_id FROM mafia_role_bindings WHERE guild_id=$1 AND season_id=$2",
            [self.guild, self.season],
        )
        return {r["family"]: r["role_id"] for r in rows}

    async def set(self, family, role, actor):
        if family not in FAMILIES:
            raise RuleError("Неизвестная сторона")
        mutation = (
            "INSERT INTO mafia_role_bindings(guild_id,season_id,family,role_id,updated_by) "
            "VALUES ($1,$2,$3,$4,$5) ON CONFLICT(guild_id,season_id,family) DO UPDATE "
            "SET role_id=EXCLUDED.role_id,updated_by=EXCLUDED.updated_by,updated_at=now() RETURNING family"
            if role
            else "DELETE FROM mafia_role_bindings WHERE guild_id=$1 AND season_id=$2 AND family=$3 RETURNING family"
        )
        try:
            await self.sql.query(
                f"WITH mutation AS ({mutation}) "
                "INSERT INTO mafia_role_history(guild_id,season_id,family,role_id,actor_id) VALUES ($1,$2,$3,$4,$5)",
                [self.guild, self.season, family, role, actor],
            )
        except ServiceError as exc:
            if str(exc).endswith("23505"):
                raise RuleError("Эта роль уже привязана к другой стороне") from None
            raise

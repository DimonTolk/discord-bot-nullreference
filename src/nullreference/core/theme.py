from typing import Protocol


class Theme(Protocol):
    """Implement this contract to add another year's rules without changing storage."""

    def initial_state(self) -> dict: ...

    def sync_members(self, state: dict, identities: dict[str, str | None], now: float) -> None: ...

    def apply(self, state: dict, actor: str, action: str, now: float, **args) -> dict: ...


class RuleError(Exception):
    """Expected, safe-to-display rejection; the enclosing transaction is rolled back."""

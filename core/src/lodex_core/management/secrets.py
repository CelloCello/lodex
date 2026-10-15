"""Local plaintext secrets, separate from public management records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lodex_core.management.common import ManagementError

if TYPE_CHECKING:
    from lodex_core.management.store import Registry


def validate_reference(reference: str) -> None:
    if reference.startswith("keychain:"):
        raise ManagementError(
            "invalid_reference",
            "Keychain references are unsupported; use secret:NAME and set the value again",
        )
    if (
        not reference.startswith("secret:")
        or not reference.removeprefix("secret:").strip()
        or "\x00" in reference
    ):
        raise ManagementError("invalid_reference", "Use a nonempty secret:NAME reference")


class SQLiteSecrets:
    def __init__(self, registry: Registry) -> None:
        self.db = registry.db

    def list_names(self) -> list[str]:
        return [
            str(row[0]).removeprefix("secret:")
            for row in self.db.execute("SELECT reference FROM secrets ORDER BY reference")
        ]

    def get(self, reference: str) -> str:
        validate_reference(reference)
        row = self.db.execute(
            "SELECT value FROM secrets WHERE reference=?", (reference,)
        ).fetchone()
        if row is None:
            raise ManagementError("missing_secret", "Secret is not set; use lodex secret set")
        return str(row[0])

    def set(self, reference: str, value: str) -> None:
        validate_reference(reference)
        if not value or "\x00" in value:
            raise ManagementError("invalid_secret", "Secret must be nonempty and contain no NUL")
        with self.db:
            self.db.execute(
                "INSERT INTO secrets(reference,value) VALUES(?,?) "
                "ON CONFLICT(reference) DO UPDATE SET value=excluded.value",
                (reference, value),
            )

    def remove(self, reference: str) -> None:
        validate_reference(reference)
        with self.db:
            self.db.execute("DELETE FROM secrets WHERE reference=?", (reference,))


def reference_for_name(name: str) -> str:
    if name.startswith(("secret:", "keychain:")):
        raise ManagementError("invalid_name", "Use a secret name without a reference prefix")
    reference = f"secret:{name}"
    validate_reference(reference)
    return reference

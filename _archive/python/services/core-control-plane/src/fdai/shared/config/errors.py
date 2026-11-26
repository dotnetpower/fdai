"""Structured config-load errors.

Kept separate so callers can catch :class:`ConfigError` without importing
pydantic or jsonschema.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfigIssue:
    """One problem detected while loading config.

    ``key`` uses the dotted config path (``azure.tenant_id``) or an env-var
    name (``AZURE_TENANT_ID``) - whichever the caller was working with.
    """

    key: str
    message: str


class ConfigError(ValueError):
    """Aggregate error emitted at the config-load boundary.

    Carries the full :class:`ConfigIssue` list so the operator sees every
    problem at once, not one at a time.
    """

    def __init__(self, issues: list[ConfigIssue]) -> None:
        self.issues = issues
        preview = "; ".join(f"{i.key}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"config load failed: {preview}{suffix}")


__all__ = ["ConfigError", "ConfigIssue"]

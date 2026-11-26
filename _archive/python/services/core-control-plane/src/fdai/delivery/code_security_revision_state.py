"""Durable successful-revision watermarks for registered repository scans."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fdai.shared.providers.state_store import StateStore

REVISION_STATE_PREFIX = "runtime:code-security-revision:"
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REVISION = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


def revision_state_key(repository_alias: str) -> str:
    if _ALIAS.fullmatch(repository_alias) is None:
        raise ValueError("repository_alias is invalid")
    return f"{REVISION_STATE_PREFIX}{repository_alias}"


async def read_successful_revision(store: StateStore, repository_alias: str) -> str | None:
    state = await store.read_state(revision_state_key(repository_alias))
    if state is None:
        return None
    if (
        set(state) != {"kind", "schema_version", "repository_alias", "revision", "recorded_at"}
        or state.get("kind") != "code-security-revision"
        or state.get("schema_version") != "1.0.0"
        or state.get("repository_alias") != repository_alias
        or not isinstance(state.get("revision"), str)
        or _REVISION.fullmatch(str(state["revision"])) is None
        or not isinstance(state.get("recorded_at"), str)
    ):
        raise ValueError("code-security revision state is malformed")
    try:
        datetime.fromisoformat(str(state["recorded_at"]))
    except ValueError as exc:
        raise ValueError("code-security revision timestamp is malformed") from exc
    return str(state["revision"])


async def record_successful_revision(
    store: StateStore,
    repository_alias: str,
    revision: str,
    *,
    recorded_at: datetime | None = None,
) -> None:
    if _REVISION.fullmatch(revision) is None:
        raise ValueError("revision is invalid")
    current = (recorded_at or datetime.now(UTC)).astimezone(UTC)
    await store.write_state(
        revision_state_key(repository_alias),
        {
            "kind": "code-security-revision",
            "schema_version": "1.0.0",
            "repository_alias": repository_alias,
            "revision": revision,
            "recorded_at": current.isoformat(timespec="seconds"),
        },
    )


__all__ = [
    "REVISION_STATE_PREFIX",
    "read_successful_revision",
    "record_successful_revision",
    "revision_state_key",
]

"""Environment parsing for the local read API harness."""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

from fdai.core.rbac.resolver import GroupMapping

_CORS_ORIGINS_ENV = "FDAI_READ_API_CORS_ALLOW_ORIGINS"
_DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5273",
    "http://localhost:5273",
    "http://127.0.0.1:5180",
    "http://localhost:5180",
    "http://127.0.0.1:5190",
    "http://localhost:5190",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    "http://127.0.0.1:8090",
    "http://localhost:8090",
)


def group_mapping_from_env(environ: Mapping[str, str] | None = None) -> GroupMapping:
    """Return the Entra group-to-role map for the local harness."""
    env = environ if environ is not None else os.environ
    slots = {
        "reader": "FDAI_RBAC_READERS_GROUP_ID",
        "contributor": "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
        "approver": "FDAI_RBAC_APPROVERS_GROUP_ID",
        "owner": "FDAI_RBAC_OWNERS_GROUP_ID",
        "break_glass": "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
    }
    resolved = {name: (env.get(key) or "").strip() for name, key in slots.items()}
    if all(resolved.values()):
        return GroupMapping(
            reader_group_id=resolved["reader"],
            contributor_group_id=resolved["contributor"],
            approver_group_id=resolved["approver"],
            owner_group_id=resolved["owner"],
            break_glass_group_id=resolved["break_glass"],
        )
    return GroupMapping(
        reader_group_id="00000000-0000-0000-0000-000000000001",
        contributor_group_id="00000000-0000-0000-0000-000000000002",
        approver_group_id="00000000-0000-0000-0000-000000000003",
        owner_group_id="00000000-0000-0000-0000-000000000004",
        break_glass_group_id="00000000-0000-0000-0000-000000000005",
    )


def cors_origins_from_env(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Return explicit browser origins for the local console dev harness."""
    env = environ if environ is not None else os.environ
    raw = env.get(_CORS_ORIGINS_ENV)
    if raw is None:
        return _DEFAULT_CORS_ORIGINS
    origins = tuple(value.strip().rstrip("/") for value in raw.split(",") if value.strip())
    if not origins:
        raise ValueError(f"{_CORS_ORIGINS_ENV} MUST contain at least one origin")
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            origin == "*"
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"{_CORS_ORIGINS_ENV} entries MUST be explicit HTTP(S) origins")
    return origins


__all__ = ["cors_origins_from_env", "group_mapping_from_env"]

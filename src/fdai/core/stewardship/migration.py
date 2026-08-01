"""Deterministic stewardship v1 to v2 candidate migration."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from fdai.core.stewardship.resolver import load_stewardship_from_mapping


class StewardshipMigrationError(ValueError):
    """Raised when a v1 map cannot produce a valid v2 candidate without guessing."""


def migrate_stewardship_mapping_to_v2(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return a validated v2 candidate without mutating ``raw``.

    The first accountable subject becomes primary and later accountable
    subjects become backups. Agents with only one accountable subject block
    migration because selecting a new person would require human judgment.
    """
    current = load_stewardship_from_mapping(raw, environ={})
    candidate = copy.deepcopy(dict(raw))
    if current.version == 2:
        return candidate

    root = candidate.get("stewardship")
    if not isinstance(root, dict):
        raise StewardshipMigrationError("stewardship migration requires a mutable root mapping")
    agents = root.get("agents")
    if not isinstance(agents, dict):
        raise StewardshipMigrationError("stewardship migration requires a mutable agents mapping")

    missing_backup: list[str] = []
    for name, raw_agent in agents.items():
        if not isinstance(raw_agent, dict):
            raise StewardshipMigrationError(f"agent {name!r} must be a mutable mapping")
        stewards = raw_agent.get("stewards", [])
        if not isinstance(stewards, list):
            raise StewardshipMigrationError(f"agent {name!r} stewards must be a mutable list")
        accountable = [
            entry
            for entry in stewards
            if isinstance(entry, Mapping) and entry.get("responsibility") == "accountable"
        ]
        if not accountable:
            continue
        if len(accountable) < 2:
            missing_backup.append(str(name))

    if missing_backup:
        raise StewardshipMigrationError(
            "stewardship v2 migration requires a second accountable subject for: "
            + ", ".join(sorted(missing_backup))
        )

    root["version"] = 2
    for raw_agent in agents.values():
        if not isinstance(raw_agent, dict):
            continue
        accountable_index = 0
        for entry in raw_agent.get("stewards", []):
            if not isinstance(entry, dict):
                continue
            if entry.get("responsibility") == "accountable":
                entry["duty"] = "primary" if accountable_index == 0 else "backup"
                accountable_index += 1
            else:
                entry.pop("duty", None)

    load_stewardship_from_mapping(candidate, environ={})
    return candidate


__all__ = ["StewardshipMigrationError", "migrate_stewardship_mapping_to_v2"]

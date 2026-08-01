"""Parse + fail-fast validate stewardship config into a :class:`StewardshipMap`.

Mirrors the notifications loader (`load_matrix_from_yaml` /
`load_matrix_from_mapping`): the YAML loader is a thin wrapper so unit tests can
validate an in-code mapping without touching the filesystem.

Fail-fast invariants (raise :class:`StewardshipValidationError`):

- fewer than 1 maintainer,
- the ``agents`` block missing any of the 15 pantheon names or naming an unknown
  agent,
- an agent with neither an accountable steward nor ``accept_autonomous``,
- an ``accept_autonomous`` without a non-empty ``reason``,
- a malformed subject (bad ``kind`` / non-UUID id / bad ``responsibility``),
- when deployment bindings are required, any maintainer or steward id left at the all-zero
    placeholder.

Design authority:
[`docs/roadmap/interfaces/agent-stewardship-and-handover.md § 7.1`]
(../../../../docs/roadmap/interfaces/agent-stewardship-and-handover.md#71-startup-fail-fast-stewardshipmapfrom_config).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from fdai.core.stewardship.model import (
    AgentStewardship,
    Duty,
    Maintainer,
    Responsibility,
    StewardKind,
    StewardshipMap,
    StewardshipValidationError,
    StewardSubject,
)
from fdai.core.stewardship.names import AGENT_NAME_SET, AGENT_NAMES

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_PLACEHOLDER_PREFIX = "00000000-0000-0000-0000-"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FORBIDDEN_ROLE_FIELDS = frozenset({"initiators", "judge", "executor", "approver", "auditor"})
_SUPPORTED_VERSIONS = frozenset({1, 2})


def _requires_real_bindings(env: Mapping[str, str]) -> bool:
    return env.get("FDAI_STEWARDSHIP_REQUIRE_BINDINGS", "").strip().lower() in _TRUTHY


def _is_placeholder(oid: str) -> bool:
    return oid.startswith(_PLACEHOLDER_PREFIX)


def _validate_oid(oid: str, *, where: str, require_real_bindings: bool) -> str:
    if not isinstance(oid, str) or not _UUID_RE.match(oid):
        raise StewardshipValidationError(
            f"stewardship config: {where} is not a valid Entra object id (UUID): {oid!r}"
        )
    if require_real_bindings and _is_placeholder(oid):
        raise StewardshipValidationError(
            f"stewardship config: {where} is still the all-zero placeholder; "
            "deployment configuration MUST supply a real Entra object id"
        )
    return oid


def load_stewardship_from_yaml(
    path: Path, *, environ: Mapping[str, str] | None = None
) -> StewardshipMap:
    """Read + validate ``config/agent-stewardship.yaml`` (or a fork override)."""
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise StewardshipValidationError(f"stewardship file {path} MUST be a YAML mapping")
    return load_stewardship_from_mapping(raw, environ=environ)


def load_stewardship_from_mapping(
    raw: Mapping[str, Any], *, environ: Mapping[str, str] | None = None
) -> StewardshipMap:
    """Validate an already-parsed mapping and return the typed map."""
    env = environ if environ is not None else os.environ
    require_real_bindings = _requires_real_bindings(env)

    root = raw.get("stewardship")
    if not isinstance(root, Mapping):
        raise StewardshipValidationError("stewardship config: top-level 'stewardship' key missing")

    forbidden = _FORBIDDEN_ROLE_FIELDS.intersection(root)
    if forbidden:
        raise StewardshipValidationError(
            "stewardship config: role fields are forbidden: " + ", ".join(sorted(forbidden))
        )

    version = root.get("version", 1)
    if isinstance(version, bool) or version not in _SUPPORTED_VERSIONS:
        raise StewardshipValidationError("stewardship config: 'version' MUST be 1 or 2")

    maintainers = _parse_maintainers(
        root.get("maintainers"),
        env=env,
        require_real_bindings=require_real_bindings,
    )
    channels = _parse_channels(
        root.get("channels"),
        require_real_bindings=require_real_bindings,
    )
    hop_timeout = _parse_hop_timeout(root.get("escalation"))
    over_assigned_max = _parse_over_assigned_max(root.get("thresholds"))
    agents = _parse_agents(
        root.get("agents"),
        version=version,
        env=env,
        require_real_bindings=require_real_bindings,
    )

    return StewardshipMap(
        version=version,
        maintainers=maintainers,
        agents=agents,
        channels=channels,
        hop_timeout_seconds=hop_timeout,
        over_assigned_max=over_assigned_max,
    )


def _parse_maintainers(
    raw: Any, *, env: Mapping[str, str], require_real_bindings: bool
) -> tuple[Maintainer, ...]:
    override = env.get("FDAI_MAINTAINERS")
    if override is not None:
        oids = [tok.strip() for tok in override.split(",") if tok.strip()]
    elif isinstance(raw, list):
        oids = []
        for entry in raw:
            if not isinstance(entry, Mapping) or "oid" not in entry:
                raise StewardshipValidationError(
                    "stewardship config: each 'maintainers' entry MUST be a mapping with an 'oid'"
                )
            oids.append(entry["oid"])
    else:
        raise StewardshipValidationError("stewardship config: 'maintainers' MUST be a list")

    if len(oids) < 1:
        raise StewardshipValidationError(
            "stewardship config: at least 1 maintainer is required (fail-fast); 2 recommended"
        )
    validated = tuple(
        Maintainer(
            oid=_validate_oid(
                o,
                where=f"maintainers[{i}].oid",
                require_real_bindings=require_real_bindings,
            )
        )
        for i, o in enumerate(oids)
    )
    if len(set(oids)) != len(oids) and any(not _is_placeholder(oid) for oid in oids):
        raise StewardshipValidationError(
            "stewardship config: maintainers MUST contain distinct Entra object ids"
        )
    return validated


def _parse_channels(raw: Any, *, require_real_bindings: bool) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise StewardshipValidationError("stewardship config: 'channels' MUST be a mapping")
    channels: dict[str, str] = {}
    for oid, channel_id in raw.items():
        if not isinstance(channel_id, str) or not channel_id.strip():
            raise StewardshipValidationError(
                f"stewardship config: 'channels' entry {oid!r} MUST map to a non-empty channel-id"
            )
        validated_oid = _validate_oid(
            oid,
            where=f"channels[{oid!r}]",
            require_real_bindings=require_real_bindings,
        )
        channels[validated_oid] = channel_id.strip()
    return channels


def _parse_hop_timeout(raw: Any) -> int:
    if raw is None:
        return 900
    if not isinstance(raw, Mapping):
        raise StewardshipValidationError("stewardship config: 'escalation' MUST be a mapping")
    value = raw.get("hop_timeout_seconds", 900)
    if not isinstance(value, int) or value <= 0:
        raise StewardshipValidationError(
            "stewardship config: 'escalation.hop_timeout_seconds' MUST be a positive integer"
        )
    return value


def _parse_over_assigned_max(raw: Any) -> int:
    if raw is None:
        return 5
    if not isinstance(raw, Mapping):
        raise StewardshipValidationError("stewardship config: 'thresholds' MUST be a mapping")
    value = raw.get("over_assigned_max", 5)
    if not isinstance(value, int) or value <= 0:
        raise StewardshipValidationError(
            "stewardship config: 'thresholds.over_assigned_max' MUST be a positive integer"
        )
    return value


def _parse_agents(
    raw: Any, *, version: int, env: Mapping[str, str], require_real_bindings: bool
) -> dict[str, AgentStewardship]:
    if not isinstance(raw, Mapping):
        raise StewardshipValidationError("stewardship config: 'agents' MUST be a mapping")

    present = set(raw.keys())
    missing = AGENT_NAME_SET - present
    if missing:
        raise StewardshipValidationError(
            "stewardship config: 'agents' is missing pantheon members: "
            + ", ".join(sorted(missing))
        )
    unknown = present - AGENT_NAME_SET
    if unknown:
        raise StewardshipValidationError(
            "stewardship config: 'agents' names unknown agents (not in the pantheon): "
            + ", ".join(sorted(unknown))
        )

    agents: dict[str, AgentStewardship] = {}
    for name in AGENT_NAMES:
        agents[name] = _parse_one_agent(
            name,
            raw[name],
            version=version,
            env=env,
            require_real_bindings=require_real_bindings,
        )
    return agents


def _parse_one_agent(
    name: str,
    raw: Any,
    *,
    version: int,
    env: Mapping[str, str],
    require_real_bindings: bool,
) -> AgentStewardship:
    if not isinstance(raw, Mapping):
        raise StewardshipValidationError(f"stewardship config: agent {name!r} MUST be a mapping")

    stewards = _parse_stewards(
        name,
        raw.get("stewards"),
        version=version,
        env=env,
        require_real_bindings=require_real_bindings,
    )

    accept = raw.get("accept_autonomous")
    reason: str | None = None
    if accept is not None:
        if not isinstance(accept, Mapping):
            raise StewardshipValidationError(
                f"stewardship config: agent {name!r} 'accept_autonomous' MUST be a mapping"
            )
        raw_reason = accept.get("reason")
        if not isinstance(raw_reason, str) or not raw_reason.strip():
            raise StewardshipValidationError(
                f"stewardship config: agent {name!r} 'accept_autonomous' MUST carry a "
                "non-empty 'reason'"
            )
        reason = raw_reason.strip()

    has_accountable = any(s.is_accountable for s in stewards)
    if not has_accountable and reason is None:
        raise StewardshipValidationError(
            f"stewardship config: agent {name!r} has no accountable steward and is not "
            "'accept_autonomous'; assign a steward or declare accept_autonomous with a reason"
        )

    if version == 2 and has_accountable:
        if not any(subject.duty is Duty.PRIMARY for subject in stewards):
            raise StewardshipValidationError(
                f"stewardship config: agent {name!r} version 2 requires a primary steward"
            )
        if not any(subject.duty in {Duty.BACKUP, Duty.ESCALATION} for subject in stewards):
            raise StewardshipValidationError(
                f"stewardship config: agent {name!r} version 2 requires a distinct backup "
                "or escalation steward"
            )

    return AgentStewardship(agent_name=name, stewards=stewards, accept_autonomous_reason=reason)


def _parse_stewards(
    agent: str,
    raw: Any,
    *,
    version: int,
    env: Mapping[str, str],
    require_real_bindings: bool,
) -> tuple[StewardSubject, ...]:
    override = env.get(f"FDAI_STEWARD_{agent.upper()}")
    if override is not None:
        return _parse_steward_env_tokens(
            agent,
            override,
            version=version,
            require_real_bindings=require_real_bindings,
        )

    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise StewardshipValidationError(
            f"stewardship config: agent {agent!r} 'stewards' MUST be a list"
        )
    subjects: list[StewardSubject] = []
    seen_subjects: set[tuple[StewardKind, str]] = set()
    accountable_count = 0
    for i, entry in enumerate(raw):
        if not isinstance(entry, Mapping):
            raise StewardshipValidationError(
                f"stewardship config: agent {agent!r} stewards[{i}] MUST be a mapping"
            )
        kind = _parse_kind(agent, i, entry.get("kind"))
        oid = _validate_oid(
            entry.get("id", ""),
            where=f"agent {agent!r} stewards[{i}].id",
            require_real_bindings=require_real_bindings,
        )
        resp = _parse_responsibility(agent, i, entry.get("responsibility"))
        duty = _parse_subject_duty(
            agent,
            i,
            entry.get("duty"),
            responsibility=resp,
            version=version,
            accountable_index=accountable_count,
        )
        if resp is Responsibility.ACCOUNTABLE:
            accountable_count += 1
        subject_key = (kind, oid)
        if subject_key in seen_subjects:
            raise StewardshipValidationError(
                f"stewardship config: agent {agent!r} has duplicate steward {kind.value}:{oid}"
            )
        seen_subjects.add(subject_key)
        subjects.append(StewardSubject(kind=kind, id=oid, responsibility=resp, duty=duty))
    return tuple(subjects)


def _parse_steward_env_tokens(
    agent: str, override: str, *, version: int, require_real_bindings: bool
) -> tuple[StewardSubject, ...]:
    subjects: list[StewardSubject] = []
    accountable_count = 0
    for raw_tok in override.split(","):
        tok = raw_tok.strip()
        if not tok:
            continue
        parts = tok.split(":")
        if len(parts) not in (2, 3, 4):
            raise StewardshipValidationError(
                f"FDAI_STEWARD_{agent.upper()}: token {tok!r} MUST be 'user:<oid>' or "
                "'group:<oid>' (optionally ':accountable|informed[:primary|backup|escalation]')"
            )
        kind = _parse_kind(agent, -1, parts[0])
        oid = _validate_oid(
            parts[1],
            where=f"FDAI_STEWARD_{agent.upper()} token",
            require_real_bindings=require_real_bindings,
        )
        resp = (
            _parse_responsibility(agent, -1, parts[2])
            if len(parts) >= 3
            else Responsibility.ACCOUNTABLE
        )
        duty = _parse_subject_duty(
            agent,
            -1,
            parts[3] if len(parts) == 4 else None,
            responsibility=resp,
            version=version,
            accountable_index=accountable_count,
        )
        if resp is Responsibility.ACCOUNTABLE:
            accountable_count += 1
        subjects.append(StewardSubject(kind=kind, id=oid, responsibility=resp, duty=duty))
    return tuple(subjects)


def _parse_subject_duty(
    agent: str,
    idx: int,
    value: Any,
    *,
    responsibility: Responsibility,
    version: int,
    accountable_index: int,
) -> Duty | None:
    if responsibility is Responsibility.INFORMED:
        if value is not None:
            raise StewardshipValidationError(
                f"stewardship config: agent {agent!r} steward[{idx}] informed subjects "
                "MUST NOT declare 'duty'"
            )
        return None
    if version == 1:
        if value is not None:
            raise StewardshipValidationError(
                f"stewardship config: agent {agent!r} steward[{idx}] 'duty' requires version 2"
            )
        return Duty.PRIMARY if accountable_index == 0 else Duty.BACKUP
    if value is None:
        raise StewardshipValidationError(
            f"stewardship config: agent {agent!r} steward[{idx}] accountable subjects "
            "MUST declare 'duty' in version 2"
        )
    try:
        return Duty(value)
    except ValueError as exc:
        raise StewardshipValidationError(
            f"stewardship config: agent {agent!r} steward[{idx}] 'duty' MUST be "
            f"'primary', 'backup', or 'escalation', got {value!r}"
        ) from exc


def _parse_kind(agent: str, idx: int, value: Any) -> StewardKind:
    try:
        return StewardKind(value)
    except ValueError as exc:
        raise StewardshipValidationError(
            f"stewardship config: agent {agent!r} steward[{idx}] 'kind' MUST be 'user' or 'group', "
            f"got {value!r}"
        ) from exc


def _parse_responsibility(agent: str, idx: int, value: Any) -> Responsibility:
    try:
        return Responsibility(value)
    except ValueError as exc:
        raise StewardshipValidationError(
            f"stewardship config: agent {agent!r} steward[{idx}] 'responsibility' MUST be "
            f"'accountable' or 'informed', got {value!r}"
        ) from exc


__all__ = ["load_stewardship_from_mapping", "load_stewardship_from_yaml"]

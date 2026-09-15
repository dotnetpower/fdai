"""Parse private alert composition bindings without acquiring identity or authority.

Only the three declared JSON settings opt into this composition. Native reader
credentials, transport keys and evidence producers belong to the source factory.
Missing source provenance disables alert writes; explicit malformed or partial
bindings fail startup without including private values in exceptions or repr.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import NoReturn, cast
from uuid import UUID

SCOPE_BINDINGS_ENV = "FDAI_ALERT_NOISE_SCOPE_BINDINGS_JSON"
PRINCIPAL_SCOPES_ENV = "FDAI_ALERT_NOISE_PRINCIPAL_SCOPES_JSON"
WRITER_BINDINGS_ENV = "FDAI_ALERT_NOISE_WRITER_BINDINGS_JSON"
SOURCE_REVISION_ENV = "FDAI_SOURCE_REVISION"
MAX_CONFIG_BYTES = 262_144
MAX_CONFIG_BINDINGS = 64

_REF = re.compile(r"[a-z][a-z0-9_.:-]{0,159}")
_PRINCIPAL = re.compile(r"principal:[a-f0-9]{64}")
_TRUST_ANCHOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}")
_COMMIT = re.compile(r"(?:commit:)?([a-f0-9]{40}(?:[a-f0-9]{24})?)")
_SCOPE_FIELDS = frozenset({"subscription_id", "resource_group", "tenant_ref", "scope_ref"})
_WRITER_FIELDS = frozenset(
    {
        "scope_ref",
        "executor_ref",
        "repository_ref",
        "repository_revision",
        "verification_trust_anchor_id",
        "principal_refs",
    }
)


@dataclass(frozen=True, slots=True, repr=False)
class AlertNoiseScopeConfig:
    """One exact native RG and its opaque routing identity; no reader is created."""

    subscription_id: str
    resource_group: str
    tenant_ref: str
    scope_ref: str


@dataclass(frozen=True, slots=True, repr=False)
class AlertNoiseWriterConfig:
    """Existing writer/repository identity pins, not permission or exclusion proof."""

    scope_ref: str
    executor_ref: str
    repository_ref: str
    repository_revision: str
    verification_trust_anchor_id: str
    principal_refs: Mapping[str, str]


@dataclass(frozen=True, slots=True, repr=False)
class AlertNoiseConfig:
    """Detached startup configuration with private identity maps and no authority."""

    scopes: Mapping[str, AlertNoiseScopeConfig]
    principal_scopes: Mapping[str, frozenset[str]]
    requester_subjects: Mapping[str, str]
    writers: Mapping[str, AlertNoiseWriterConfig]
    source_revision: str | None


def alert_requester_ref(subject: str, scope_ref: str) -> str:
    """Match Operator's exact subject/scope JSON hash without normalizing identity.

    This is a reference derivation only. The private map must contain the current
    canonical nonzero Entra OID; the result never establishes a role or approval.
    """
    _oid(subject)
    _reference(scope_ref)
    raw = json.dumps(["operator-alert-quality-v1", subject, scope_ref], separators=(",", ":"))
    return "principal:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_alert_noise_config(environment: Mapping[str, str]) -> AlertNoiseConfig | None:
    """Return None only when all alert composition settings are absent.

    Scopes and subject scopes must be supplied together. Writer bindings are
    optional, but each configured writer is complete and refers to a known scope.
    JSON documents are at most 256 KiB and collections at most 64 entries. Empty
    subject maps/lists explicitly grant no access. No file or provider is read.
    A source revision, when supplied, must be a nonzero exact Git commit identity;
    an absent revision is retained as None, never replaced with synthetic proof.
    """
    if not any(
        key in environment
        for key in (
            SCOPE_BINDINGS_ENV,
            PRINCIPAL_SCOPES_ENV,
            WRITER_BINDINGS_ENV,
        )
    ):
        return None
    if SCOPE_BINDINGS_ENV not in environment or PRINCIPAL_SCOPES_ENV not in environment:
        raise ValueError("alert noise composition requires both scope and principal bindings")
    scopes = _scopes(_json_setting(environment, SCOPE_BINDINGS_ENV))
    principals = _principal_scopes(_json_setting(environment, PRINCIPAL_SCOPES_ENV), scopes)
    subjects = {
        alert_requester_ref(subject, scope): subject
        for subject, allowed in principals.items()
        for scope in sorted(allowed)
    }
    writers = (
        _writers(_json_setting(environment, WRITER_BINDINGS_ENV), scopes, principals)
        if WRITER_BINDINGS_ENV in environment
        else {}
    )
    revision = (
        _commit(environment[SOURCE_REVISION_ENV]) if SOURCE_REVISION_ENV in environment else None
    )
    return AlertNoiseConfig(
        scopes=MappingProxyType(scopes),
        principal_scopes=MappingProxyType(principals),
        requester_subjects=MappingProxyType(subjects),
        writers=MappingProxyType(writers),
        source_revision=revision,
    )


def _json_setting(environment: Mapping[str, str], name: str) -> object:
    try:
        raw = environment[name]
        if type(raw) is not str or not 1 <= len(raw.encode("utf-8")) <= MAX_CONFIG_BYTES:
            raise ValueError("invalid size")
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (TypeError, ValueError, RecursionError):
        raise ValueError(f"{name} MUST contain bounded JSON with unique object fields") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate alert configuration field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite alert configuration value")


def _object(
    value: object, fields: frozenset[str] | None = None, *, maximum: int = MAX_CONFIG_BINDINGS
) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError("alert configuration MUST contain an object")
    if len(value) > maximum or (fields is not None and set(value) != fields):
        raise ValueError("alert configuration object has missing, unknown or excessive fields")
    return cast(dict[str, object], value)


def _array(value: object, *, allow_empty: bool = False) -> list[object]:
    if (
        type(value) is not list
        or not (0 if allow_empty else 1) <= len(value) <= MAX_CONFIG_BINDINGS
    ):
        raise ValueError("alert configuration MUST contain a bounded array")
    return cast(list[object], value)


def _reference(value: object, pattern: re.Pattern[str] = _REF) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError("alert configuration reference MUST be exact and bounded")
    return value


def _oid(value: object) -> str:
    try:
        if type(value) is not str or len(value) != 36:
            raise ValueError("invalid identity")
        parsed = UUID(value)
        if str(parsed) != value or parsed.int == 0:
            raise ValueError("noncanonical identity")
        return value
    except ValueError:
        raise ValueError("alert configuration requires a canonical nonzero UUID") from None


def _commit(value: object) -> str:
    matched = _COMMIT.fullmatch(value) if type(value) is str else None
    if matched is None or int(matched.group(1), 16) == 0:
        raise ValueError("alert configuration requires an explicit nonzero Git commit revision")
    return "commit:" + matched.group(1)


def _scopes(value: object) -> dict[str, AlertNoiseScopeConfig]:
    scopes: dict[str, AlertNoiseScopeConfig] = {}
    native: set[tuple[str, str]] = set()
    tenants: dict[str, str] = {}
    for item in _array(value):
        row = _object(item, _SCOPE_FIELDS)
        subscription = _oid(row["subscription_id"])
        group = _reference(row["resource_group"], re.compile(r"[A-Za-z0-9_.()-]{1,90}"))
        if group.endswith("."):
            raise ValueError("alert native resource group MUST NOT end with a dot")
        scope, tenant = _reference(row["scope_ref"]), _reference(row["tenant_ref"])
        key = (subscription, group.casefold())
        if scope in scopes or key in native or tenants.get(subscription, tenant) != tenant:
            raise ValueError("alert scopes contain duplicate or conflicting native routes")
        scopes[scope] = AlertNoiseScopeConfig(subscription, group, tenant, scope)
        native.add(key)
        tenants[subscription] = tenant
    return scopes


def _principal_scopes(
    value: object,
    scopes: Mapping[str, AlertNoiseScopeConfig],
) -> dict[str, frozenset[str]]:
    result: dict[str, frozenset[str]] = {}
    for subject, items in _object(value, maximum=1000).items():
        _oid(subject)
        allowed = tuple(_reference(item) for item in _array(items, allow_empty=True))
        if len(set(allowed)) != len(allowed) or not set(allowed).issubset(scopes):
            raise ValueError("alert principal scopes contain duplicate or unbound routes")
        result[subject] = frozenset(allowed)
    return result


def _writers(
    value: object,
    scopes: Mapping[str, AlertNoiseScopeConfig],
    principal_scopes: Mapping[str, frozenset[str]],
) -> dict[str, AlertNoiseWriterConfig]:
    writers: dict[str, AlertNoiseWriterConfig] = {}
    for item in _array(value):
        row = _object(item, _WRITER_FIELDS)
        scope = _reference(row["scope_ref"])
        if scope not in scopes or scope in writers:
            raise ValueError("alert writer scopes contain duplicate or unbound routes")
        identities = {
            _oid(subject): _reference(ref, _PRINCIPAL)
            for subject, ref in _object(row["principal_refs"]).items()
        }
        executor = _reference(row["executor_ref"], _PRINCIPAL)
        if executor not in identities.values() or len(set(identities.values())) != len(identities):
            raise ValueError(
                "alert writer identities require one exact mapped executor and unique refs"
            )
        for subject, ref in identities.items():
            if scope in principal_scopes.get(subject, ()) and ref != alert_requester_ref(
                subject, scope
            ):
                raise ValueError(
                    "alert writer requester identity does not match the scoped subject"
                )
        writers[scope] = AlertNoiseWriterConfig(
            scope_ref=scope,
            executor_ref=executor,
            repository_ref=_reference(row["repository_ref"]),
            repository_revision=_commit(row["repository_revision"]),
            verification_trust_anchor_id=_reference(
                row["verification_trust_anchor_id"], _TRUST_ANCHOR
            ),
            principal_refs=MappingProxyType(identities),
        )
    return writers


__all__ = [
    "AlertNoiseConfig",
    "AlertNoiseScopeConfig",
    "AlertNoiseWriterConfig",
    "alert_requester_ref",
    "parse_alert_noise_config",
]

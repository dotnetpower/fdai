"""Strict loader and content-based revision classifier for the case-scope grant registry."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from fdai_service_contracts.operational_evidence import OPERATIONAL_EVIDENCE_PURPOSES

from .grant_registry import (
    GRANT_OPERATIONS,
    GRANT_REGISTRY_ID,
    CaseScope,
    CaseScopeGrantRegistry,
    PrincipalGrant,
    ReuseGrant,
)
from .registry_json import (
    RegistryUnavailableError,
    RevisionClass,
    bounded_text,
    exact_fields,
    has_duplicates,
    load_pinned_json,
    positive_int,
    text_tuple,
    validity,
)

_SCOPE_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_TOP_FIELDS = frozenset(
    {"schema_version", "registry_id", "revision", "case_scopes", "principal_grants", "reuse_grants"}
)
_WINDOW_FIELDS = frozenset({"valid_from", "valid_until", "revoked"})
_SCOPE_FIELDS = frozenset(
    {"case_scope_id", "access_scope_digest", "resource_selectors", "purposes", "policy_revision"}
    | _WINDOW_FIELDS
)
_GRANT_FIELDS = frozenset(
    {"grant_id", "selector", "case_scopes", "operations", "purposes", "reviewer"} | _WINDOW_FIELDS
)
_REUSE_FIELDS = frozenset({"grant_id", "case_scopes", "target_scope_digest"} | _WINDOW_FIELDS)


def load_grant_registry(data: bytes, *, expected_pin: str) -> CaseScopeGrantRegistry:
    """Load one pinned revision; any defect makes every grant-dependent purpose unavailable."""

    raw = load_pinned_json(data, expected_pin=expected_pin, label="case-scope grant registry")
    try:
        if has_duplicates(raw):
            raise ValueError("case-scope grant registry repeats a key")
        top = exact_fields(raw, _TOP_FIELDS, label="case-scope grant registry")
        if top["schema_version"] != "1.0.0" or top["registry_id"] != GRANT_REGISTRY_ID:
            raise ValueError("case-scope grant registry schema or identity is unsupported")
        revision = positive_int(top["revision"], label="grant registry revision", maximum=10**9)
        scopes = tuple(_case_scope(item) for item in _list(top["case_scopes"], "case_scopes"))
        grants = tuple(
            _principal_grant(item) for item in _list(top["principal_grants"], "principal_grants")
        )
        reuse = tuple(
            _reuse_grant(item) for item in _list(top["reuse_grants"], "reuse_grants", minimum=0)
        )
        _unique((scope.case_scope_id for scope in scopes), "case_scope_id")
        _unique((scope.access_scope_digest for scope in scopes), "access_scope_digest")
        _unique(
            [*(item.grant_id for item in grants), *(item.grant_id for item in reuse)], "grant_id"
        )
        known = {scope.case_scope_id for scope in scopes}
        if any(not item.case_scopes <= known for item in grants) or any(
            not item.case_scopes <= known for item in reuse
        ):
            raise ValueError("grant references an unknown case scope")
    except (KeyError, TypeError, ValueError) as exc:
        raise RegistryUnavailableError("case-scope grant registry is invalid") from exc
    return CaseScopeGrantRegistry(
        pin=expected_pin,
        revision=revision,
        case_scopes={scope.case_scope_id: scope for scope in scopes},
        principal_grants=grants,
        reuse_grants=reuse,
    )


def classify_grant_revision(
    previous: CaseScopeGrantRegistry, current: CaseScopeGrantRegistry
) -> RevisionClass:
    """Classify by content: removal, narrowing, shortening, or a revoked flag revokes."""

    windows = current.entry_windows()
    for key, before in previous.entry_windows().items():
        after = windows.get(key)
        if after is None or before.narrowed_by(after):
            return RevisionClass.REVOCATION
    current_scopes = current.case_scopes
    for scope_id, scope in previous.case_scopes.items():
        now = current_scopes[scope_id]
        if (
            now.access_scope_digest != scope.access_scope_digest
            or not set(scope.resource_selectors) <= set(now.resource_selectors)
            or not scope.purposes <= now.purposes
            or now.policy_revision != scope.policy_revision
        ):
            return RevisionClass.REVOCATION
    grants = {grant.grant_id: grant for grant in current.principal_grants}
    for grant in previous.principal_grants:
        now_grant = grants[grant.grant_id]
        if (
            (now_grant.selector_kind, now_grant.selector_value)
            != (grant.selector_kind, grant.selector_value)
            or not grant.case_scopes <= now_grant.case_scopes
            or not grant.operations <= now_grant.operations
            or not grant.purposes <= now_grant.purposes
        ):
            return RevisionClass.REVOCATION
    reuse = {grant.grant_id: grant for grant in current.reuse_grants}
    for reuse_grant in previous.reuse_grants:
        now_reuse = reuse[reuse_grant.grant_id]
        if (
            not reuse_grant.case_scopes <= now_reuse.case_scopes
            or now_reuse.target_scope_digest != reuse_grant.target_scope_digest
        ):
            return RevisionClass.REVOCATION
    return RevisionClass.ROUTINE_ROTATION


def _case_scope(raw: object) -> CaseScope:
    value = exact_fields(raw, _SCOPE_FIELDS, label="case scope")
    digest = bounded_text(value["access_scope_digest"], label="access_scope_digest")
    if _SCOPE_DIGEST.fullmatch(digest) is None:
        raise ValueError("case scope digest MUST be lowercase SHA-256")
    return CaseScope(
        case_scope_id=bounded_text(value["case_scope_id"], label="case_scope_id", maximum=128),
        access_scope_digest=digest,
        resource_selectors=text_tuple(value["resource_selectors"], label="resource_selectors"),
        purposes=_purposes(value["purposes"]),
        policy_revision=bounded_text(value["policy_revision"], label="policy_revision"),
        window=validity(value, label="case scope"),
    )


def _principal_grant(raw: object) -> PrincipalGrant:
    value = exact_fields(raw, _GRANT_FIELDS, label="principal grant")
    selector = exact_fields(value["selector"], frozenset({"kind", "value"}), label="selector")
    if selector["kind"] not in {"group", "app_role"}:
        raise ValueError("grant selector MUST name a group or app role")
    operations = frozenset(text_tuple(value["operations"], label="operations", maximum=4))
    if not operations <= GRANT_OPERATIONS:
        raise ValueError("grant operation is unsupported")
    return PrincipalGrant(
        grant_id=bounded_text(value["grant_id"], label="grant_id", maximum=128),
        selector_kind=str(selector["kind"]),
        selector_value=bounded_text(selector["value"], label="selector value", maximum=256),
        case_scopes=frozenset(text_tuple(value["case_scopes"], label="grant case_scopes")),
        operations=operations,
        purposes=_purposes(value["purposes"]),
        reviewer=bounded_text(value["reviewer"], label="reviewer", maximum=256),
        window=validity(value, label="principal grant"),
    )


def _reuse_grant(raw: object) -> ReuseGrant:
    value = exact_fields(raw, _REUSE_FIELDS, label="reuse grant")
    target = bounded_text(value["target_scope_digest"], label="target_scope_digest")
    if _SCOPE_DIGEST.fullmatch(target) is None:
        raise ValueError("reuse target scope MUST be lowercase SHA-256")
    return ReuseGrant(
        grant_id=bounded_text(value["grant_id"], label="grant_id", maximum=128),
        case_scopes=frozenset(text_tuple(value["case_scopes"], label="reuse case_scopes")),
        target_scope_digest=target,
        window=validity(value, label="reuse grant"),
    )


def _purposes(value: object) -> frozenset[str]:
    purposes = frozenset(text_tuple(value, label="purposes", maximum=16))
    if not purposes <= set(OPERATIONAL_EVIDENCE_PURPOSES):
        raise ValueError("grant purpose is not registered")
    return purposes


def _list(value: object, label: str, *, minimum: int = 1) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= 256:
        raise ValueError(f"{label} MUST be a bounded array")
    return value


def _unique(values: Iterable[str], label: str) -> None:
    items = list(values)
    if len(set(items)) != len(items):
        raise ValueError(f"{label} MUST be unique")


__all__ = ["classify_grant_revision", "load_grant_registry"]

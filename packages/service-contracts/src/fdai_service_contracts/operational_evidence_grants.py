"""Shared case-scope grant registry loader and authorization model."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operational_evidence import (
    OPERATIONAL_EVIDENCE_PURPOSES,
    OperationalEvidenceRejectionClass,
)
from fdai_service_contracts.operator_authentication import OperatorAuthenticationReceipt

_MAX_REGISTRY_BYTES = 256 * 1024
GRANT_REGISTRY_ID = "fdai.operational-evidence.case-scope-grants"
GRANT_OPERATIONS = frozenset(
    {"test-context.propose", "test-context.review", "test-context.revoke", "case-history.read"}
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


class RegistryUnavailableError(ValueError):
    """A registry revision cannot be trusted as a whole."""


class RevisionClass(StrEnum):
    """Content-derived relation between two consecutive registry revisions."""

    ROUTINE_ROTATION = "routine_rotation"
    REVOCATION = "revocation"


class _TrackedDict(dict[str, Any]):
    duplicates: tuple[str, ...] = ()


def _pairs(pairs: list[tuple[str, Any]]) -> _TrackedDict:
    value = _TrackedDict()
    duplicates: list[str] = []
    for key, item in pairs:
        if key in value:
            duplicates.append(key)
        value[key] = item
    value.duplicates = tuple(sorted(set(duplicates)))
    return value


def content_pin(data: bytes) -> str:
    """Return the content address of the exact reviewed bytes."""

    return "sha256:" + hashlib.sha256(data).hexdigest()


def load_pinned_json(data: bytes, *, expected_pin: str, label: str) -> Mapping[str, Any]:
    """Parse bounded JSON bytes only when they match the reviewed pin."""

    if not isinstance(data, bytes) or len(data) > _MAX_REGISTRY_BYTES:
        raise RegistryUnavailableError(f"{label} MUST be bounded bytes")
    if content_pin(data) != expected_pin:
        raise RegistryUnavailableError(f"{label} content does not match its reviewed pin")
    try:
        parsed = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryUnavailableError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(parsed, _TrackedDict):
        raise RegistryUnavailableError(f"{label} MUST be a JSON object")
    return parsed


def has_duplicates(value: object) -> bool:
    if isinstance(value, _TrackedDict):
        return bool(value.duplicates) or any(has_duplicates(item) for item in value.values())
    if isinstance(value, list):
        return any(has_duplicates(item) for item in value)
    return False


def exact_fields(value: object, required: frozenset[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} MUST be an object")
    if isinstance(value, _TrackedDict) and value.duplicates:
        raise ValueError(f"{label} repeats a key")
    if set(value) != required:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def bounded_text(value: object, *, label: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} MUST be bounded non-empty text")
    if any(character in value for character in "\r\n\x00"):
        raise ValueError(f"{label} MUST NOT contain control characters")
    return value


def text_tuple(value: object, *, label: str, maximum: int = 64) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{label} MUST be a bounded non-empty array")
    items = tuple(bounded_text(item, label=label) for item in value)
    if len(set(items)) != len(items):
        raise ValueError(f"{label} MUST NOT repeat values")
    return tuple(sorted(items))


def aware_time(value: object, *, label: str) -> datetime:
    text = bounded_text(value, label=label, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} MUST be an ISO 8601 instant") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} MUST include a timezone")
    return parsed.astimezone(UTC)


def strict_bool(value: object, *, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} MUST be a boolean")
    return value


def positive_int(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{label} MUST be an integer in [1, {maximum}]")
    return value


@dataclass(frozen=True, slots=True)
class ValidityWindow:
    """Reviewed validity of one binding, grant, or scope."""

    valid_from: datetime
    valid_until: datetime
    revoked: bool

    def __post_init__(self) -> None:
        if self.valid_until <= self.valid_from:
            raise ValueError("registry validity MUST end after it starts")

    def active_at(self, evaluated_at: datetime) -> bool:
        return not self.revoked and self.valid_from <= evaluated_at < self.valid_until

    def narrowed_by(self, current: ValidityWindow) -> bool:
        return (
            (current.revoked and not self.revoked)
            or current.valid_from > self.valid_from
            or current.valid_until < self.valid_until
        )


def validity(raw: Mapping[str, Any], *, label: str) -> ValidityWindow:
    return ValidityWindow(
        valid_from=aware_time(raw["valid_from"], label=f"{label}.valid_from"),
        valid_until=aware_time(raw["valid_until"], label=f"{label}.valid_until"),
        revoked=strict_bool(raw["revoked"], label=f"{label}.revoked"),
    )


@dataclass(frozen=True, slots=True)
class CaseScope:
    """One opaque case scope, its resource selectors, purposes, and policy revision."""

    case_scope_id: str
    access_scope_digest: str
    resource_selectors: tuple[str, ...]
    purposes: frozenset[str]
    policy_revision: str
    window: ValidityWindow

    def contains(self, target_ref: str) -> bool:
        target = target_ref.casefold()
        for selector in self.resource_selectors:
            value = selector.casefold()
            if value.endswith("/*"):
                if target.startswith(value[:-1]) and len(target) > len(value) - 1:
                    return True
            elif target == value:
                return True
        return False


@dataclass(frozen=True, slots=True)
class PrincipalGrant:
    """One reviewed grant for a group or app-role selector."""

    grant_id: str
    selector_kind: str
    selector_value: str
    case_scopes: frozenset[str]
    operations: frozenset[str]
    purposes: frozenset[str]
    reviewer: str
    window: ValidityWindow

    def selects(self, receipt: OperatorAuthenticationReceipt) -> bool:
        values = receipt.groups if self.selector_kind == "group" else receipt.roles
        return self.selector_value in values


@dataclass(frozen=True, slots=True)
class ReuseGrant:
    """Case scopes whose immutable cases may be reused for events in one target scope."""

    grant_id: str
    case_scopes: frozenset[str]
    target_scope_digest: str
    window: ValidityWindow


@dataclass(frozen=True, slots=True)
class GrantDecision:
    """Result of one explicit authorization; allowance never grants execution."""

    allowed: bool
    rejection_class: OperationalEvidenceRejectionClass | None
    reasons: tuple[str, ...]
    case_scope: CaseScope | None = None
    matched_grants: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    @classmethod
    def deny(
        cls,
        rejection_class: OperationalEvidenceRejectionClass,
        reason: str,
        *,
        case_scope: CaseScope | None = None,
    ) -> GrantDecision:
        return cls(False, rejection_class, (reason,), case_scope=case_scope)


@dataclass(frozen=True, slots=True)
class CaseScopeGrantRegistry:
    """One pinned revision of the three grant parts."""

    pin: str
    revision: int
    case_scopes: Mapping[str, CaseScope]
    principal_grants: tuple[PrincipalGrant, ...]
    reuse_grants: tuple[ReuseGrant, ...] = field(default_factory=tuple)

    def scope_for(self, access_scope_digest: str) -> CaseScope | None:
        return next(
            (
                scope
                for scope in self.case_scopes.values()
                if scope.access_scope_digest == access_scope_digest
            ),
            None,
        )

    def authorize(
        self,
        receipt: OperatorAuthenticationReceipt,
        *,
        access_scope_digest: str,
        operation: str,
        purpose_id: str,
        at: datetime,
        target_ref: str | None = None,
        policy_revision: str | None = None,
    ) -> GrantDecision:
        scope = self.scope_for(access_scope_digest)
        if scope is None:
            return GrantDecision.deny(
                OperationalEvidenceRejectionClass.CROSS_SCOPE, "case_scope_unknown"
            )
        scope_decision = _scope_current(scope, at=at)
        if scope_decision is not None:
            return scope_decision
        if purpose_id not in scope.purposes:
            return GrantDecision.deny(
                OperationalEvidenceRejectionClass.CROSS_SCOPE, "purpose_outside_case_scope"
            )
        if target_ref is not None and not scope.contains(target_ref):
            return GrantDecision.deny(
                OperationalEvidenceRejectionClass.CROSS_SCOPE, "target_outside_case_scope"
            )
        if policy_revision is not None and policy_revision != scope.policy_revision:
            return GrantDecision(
                False,
                OperationalEvidenceRejectionClass.CONFLICTING,
                ("policy_revision_superseded",),
                case_scope=scope,
                conflicts=tuple(
                    sorted(
                        {
                            content_digest({"policy_revision": policy_revision}),
                            content_digest({"policy_revision": scope.policy_revision}),
                        }
                    )
                ),
            )
        matching = [
            grant
            for grant in self.principal_grants
            if grant.selects(receipt)
            and scope.case_scope_id in grant.case_scopes
            and operation in grant.operations
            and purpose_id in grant.purposes
        ]
        return _single_grant_decision(matching, scope=scope, at=at)

    def authorize_reuse(
        self,
        *,
        case_scope_digest: str,
        target_scope_digest: str,
        at: datetime,
    ) -> GrantDecision:
        scope = self.scope_for(case_scope_digest)
        if scope is None:
            return GrantDecision.deny(
                OperationalEvidenceRejectionClass.CROSS_SCOPE, "case_scope_unknown"
            )
        scope_decision = _scope_current(scope, at=at)
        if scope_decision is not None:
            return scope_decision
        matching = [
            grant
            for grant in self.reuse_grants
            if scope.case_scope_id in grant.case_scopes
            and grant.target_scope_digest == target_scope_digest
        ]
        return _single_grant_decision(matching, scope=scope, at=at)

    def entry_windows(self) -> dict[tuple[str, str], ValidityWindow]:
        windows: dict[tuple[str, str], ValidityWindow] = {
            ("case_scope", scope.case_scope_id): scope.window for scope in self.case_scopes.values()
        }
        windows.update(
            {("principal_grant", grant.grant_id): grant.window for grant in self.principal_grants}
        )
        windows.update(
            {("reuse_grant", grant.grant_id): grant.window for grant in self.reuse_grants}
        )
        return windows


def _scope_current(scope: CaseScope, *, at: datetime) -> GrantDecision | None:
    if scope.window.revoked:
        return GrantDecision.deny(
            OperationalEvidenceRejectionClass.REVOKED, "case_scope_revoked", case_scope=scope
        )
    if not scope.window.active_at(at):
        return GrantDecision.deny(
            OperationalEvidenceRejectionClass.STALE, "case_scope_not_current", case_scope=scope
        )
    return None


def _single_grant_decision(
    matching: Iterable[PrincipalGrant | ReuseGrant],
    *,
    scope: CaseScope,
    at: datetime,
) -> GrantDecision:
    grants = tuple(matching)
    if any(grant.window.revoked for grant in grants):
        return GrantDecision.deny(
            OperationalEvidenceRejectionClass.REVOKED, "grant_revoked", case_scope=scope
        )
    if any(grant.window.valid_until <= at for grant in grants):
        return GrantDecision.deny(
            OperationalEvidenceRejectionClass.STALE, "grant_not_current", case_scope=scope
        )
    current = tuple(grant for grant in grants if grant.window.active_at(at))
    if not current:
        return GrantDecision.deny(
            OperationalEvidenceRejectionClass.CROSS_SCOPE, "grant_missing", case_scope=scope
        )
    return GrantDecision(
        True,
        None,
        (),
        case_scope=scope,
        matched_grants=tuple(sorted(grant.grant_id for grant in current)),
    )


def load_grant_registry(data: bytes, *, expected_pin: str) -> CaseScopeGrantRegistry:
    """Load one pinned revision; any defect makes grant-dependent purposes unavailable."""

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


__all__ = [
    "GRANT_OPERATIONS",
    "GRANT_REGISTRY_ID",
    "CaseScope",
    "CaseScopeGrantRegistry",
    "GrantDecision",
    "PrincipalGrant",
    "RegistryUnavailableError",
    "ReuseGrant",
    "RevisionClass",
    "ValidityWindow",
    "classify_grant_revision",
    "content_pin",
    "load_grant_registry",
]

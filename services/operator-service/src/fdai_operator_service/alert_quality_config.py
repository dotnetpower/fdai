"""Validated private scope ceilings and explicit alert-quality dependency bindings."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType

from fdai_operator_service.alert_quality_records import (
    AlertQualitySource,
    AlertQualityStateStore,
    validate_alert_quality_principal,
    validate_alert_quality_scope,
)
from fdai_operator_service.alert_quality_settings import AlertQualityPreferenceStore
from fdai_operator_service.alert_quality_store import StateKvAlertQualityStore
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.operations.contracts import EventProposalWriter

PRINCIPAL_SCOPES_ENV = "FDAI_ALERT_NOISE_PRINCIPAL_SCOPES_JSON"
ProducerReady = Callable[[], Awaitable[bool]]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate members in configuration and request JSON."""
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON member")
        value[key] = item
    return value


def parse_alert_quality_principal_scopes(
    environ: Mapping[str, str],
) -> Mapping[str, frozenset[str]]:
    """Validate private exact-subject scope ceilings without assigning roles.

    Missing configuration closes access. Wildcards, URLs, duplicate entries and
    unbounded bindings fail startup without disclosing configuration values.
    """
    raw = environ.get(PRINCIPAL_SCOPES_ENV)
    if raw is None:
        return MappingProxyType({})
    try:
        if not raw or len(raw.encode()) > 262_144:
            raise ValueError("scope configuration exceeds bounds")
        parsed = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(parsed, dict) or len(parsed) > 1000:
            raise ValueError("scope configuration MUST be a bounded object")
        bindings: dict[str, frozenset[str]] = {}
        for principal, scopes in parsed.items():
            validate_alert_quality_principal(principal)
            if not isinstance(scopes, list) or len(scopes) > 64:
                raise ValueError("scope list exceeds bounds")
            for scope in scopes:
                validate_alert_quality_scope(scope)
            if len(set(scopes)) != len(scopes):
                raise ValueError("scope list contains duplicates")
            bindings[principal] = frozenset(scopes)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid private alert quality scope configuration") from exc
    return MappingProxyType(bindings)


@dataclass(frozen=True, slots=True)
class AlertQualityDependencies:
    """Bind HTTP dependencies without implying readiness, promotion or authority.

    Enabled is the unsaved default; a bound preference store overrides it per scope.
    Unbound preferences retain that default but leave Settings unavailable. Failure
    of a bound store vetoes requests without hiding evidence. Authentication and
    roles are current-request checks; scope configuration is only their ceiling.
    """

    authenticator: OperatorAuthenticator
    principal_scopes: Mapping[str, frozenset[str]] = field(repr=False)
    source: AlertQualitySource | None = None
    proposal_writer: EventProposalWriter | None = None
    producer_ready: ProducerReady | None = None
    enabled: bool = True
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    timeout_seconds: float = 15.0
    preference_store: AlertQualityPreferenceStore | None = None

    def __post_init__(self) -> None:
        if (
            type(self.enabled) is not bool
            or type(self.timeout_seconds) not in {int, float}
            or not 0 < self.timeout_seconds <= 30
        ):
            raise ValueError("invalid alert quality capability bounds")
        raw = json.dumps({key: sorted(value) for key, value in self.principal_scopes.items()})
        scopes = parse_alert_quality_principal_scopes({PRINCIPAL_SCOPES_ENV: raw})
        object.__setattr__(self, "principal_scopes", scopes)


def alert_quality_dependencies_from_environment(
    *,
    authenticator: OperatorAuthenticator,
    environ: Mapping[str, str],
    store: AlertQualityStateStore | None,
    proposal_writer: EventProposalWriter | None,
    producer_ready: ProducerReady | None = None,
    enabled: bool = True,
    preference_store: AlertQualityPreferenceStore | None = None,
) -> AlertQualityDependencies:
    """Bind the existing Operator store/writer without a producer-readiness fallback.

    Composition supplies the concrete drainer probe. The trusted result consumer
    resolves each principal from its durable request before materializing evidence.
    """
    return AlertQualityDependencies(
        authenticator=authenticator,
        principal_scopes=parse_alert_quality_principal_scopes(environ),
        source=StateKvAlertQualityStore(store) if store is not None else None,
        proposal_writer=proposal_writer,
        producer_ready=producer_ready,
        enabled=enabled,
        preference_store=preference_store,
    )

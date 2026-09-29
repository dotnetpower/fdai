"""Trial entitlement resolution tests.

These cover the boundary between durable Trial state and capability availability:
an active window grants, and absence, misbinding, expiry, clock regression, a stale
observation, or a storage failure each deny while leaving observation intact.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.capability_catalog import (
    Capability,
    CapabilityCatalog,
    CapabilityCategory,
    SideEffectClass,
)
from fdai.core.licensing.entitlement import LicenseStatus
from fdai.core.licensing.trial import TRIAL_DURATION, TrialRecord
from fdai.core.licensing.trial_entitlement import TrialEntitlementResolver

_NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
_INSTALLATION = "a" * 64
_DEPLOYMENT = "b" * 64


def _catalog() -> CapabilityCatalog:
    return CapabilityCatalog(
        [
            Capability(
                capability_id="cost.metering",
                name="Cost metering",
                category=CapabilityCategory.COST,
                summary="Read cost rollups.",
                side_effect_class=SideEffectClass.READ,
            ),
            Capability(
                capability_id="incident.restart",
                name="Restart",
                category=CapabilityCategory.INCIDENT,
                summary="Restart a target.",
                side_effect_class=SideEffectClass.EXECUTE,
            ),
        ]
    )


class _Store:
    def __init__(self, record: TrialRecord | None) -> None:
        self._record = record
        self.calls = 0

    def observe(self, *, now: datetime) -> TrialRecord | None:
        self.calls += 1
        return self._record


class _FailingStore:
    def observe(self, *, now: datetime) -> TrialRecord | None:
        raise RuntimeError("durable Trial state is unreachable")


def _record(
    *,
    activated_at: datetime = _NOW,
    last_observed_at: datetime | None = None,
    installation: str = _INSTALLATION,
    deployment: str = _DEPLOYMENT,
    clock_blocked: bool = False,
) -> TrialRecord:
    return TrialRecord(
        installation,
        deployment,
        activated_at,
        last_observed_at if last_observed_at is not None else activated_at,
        1,
        clock_blocked,
    )


def _resolver(store: object) -> TrialEntitlementResolver:
    return TrialEntitlementResolver(
        catalog=_catalog(),
        store=store,  # type: ignore[arg-type]
        installation_binding=_INSTALLATION,
        deployment_binding=_DEPLOYMENT,
    )


def test_an_active_trial_makes_every_catalog_capability_available() -> None:
    store = _Store(_record(last_observed_at=_NOW))

    entitlement = _resolver(store).resolve(now=_NOW)

    assert entitlement.status is LicenseStatus.ACTIVE
    assert entitlement.available_capability_ids == {"cost.metering", "incident.restart"}
    assert store.calls == 1


def test_an_unactivated_installation_receives_no_capability() -> None:
    entitlement = _resolver(_Store(None)).resolve(now=_NOW)

    assert entitlement.status is LicenseStatus.ABSENT
    assert entitlement.available_capability_ids == frozenset()


@pytest.mark.parametrize("field", ["installation", "deployment"])
def test_a_record_bound_elsewhere_is_refused(field: str) -> None:
    """A copied record must not activate a different installation."""

    other = "c" * 64
    store = _Store(_record(last_observed_at=_NOW, **{field: other}))

    entitlement = _resolver(store).resolve(now=_NOW)

    assert entitlement.available_capability_ids == frozenset()
    assert "another installation" in entitlement.reason


def test_an_expired_window_blocks_new_acting_work() -> None:
    expired = _NOW + TRIAL_DURATION
    store = _Store(_record(activated_at=_NOW, last_observed_at=expired))

    entitlement = _resolver(store).resolve(now=expired)

    assert entitlement.available_capability_ids == frozenset()
    assert "window has ended" in entitlement.reason


def test_expiry_is_reached_without_a_restart() -> None:
    """The same stored record denies once time crosses the window, with no new process."""

    resolver = _resolver(_Store(_record(last_observed_at=_NOW)))
    assert resolver.resolve(now=_NOW).status is LicenseStatus.ACTIVE

    later = _NOW + TRIAL_DURATION
    expired_store = _Store(_record(activated_at=_NOW, last_observed_at=later))
    assert _resolver(expired_store).resolve(now=later).available_capability_ids == frozenset()


def test_a_clock_regression_stays_denied() -> None:
    store = _Store(_record(last_observed_at=_NOW, clock_blocked=True))

    entitlement = _resolver(store).resolve(now=_NOW)

    assert entitlement.available_capability_ids == frozenset()
    assert "clock regression" in entitlement.reason


def test_a_stale_observation_cannot_act_for_a_later_moment() -> None:
    """A replica that read an older revision must not act past another writer's view."""

    store = _Store(_record(last_observed_at=_NOW))

    entitlement = _resolver(store).resolve(now=_NOW + timedelta(minutes=5))

    assert entitlement.available_capability_ids == frozenset()
    assert "stale" in entitlement.reason


def test_unreachable_trial_state_denies_rather_than_granting() -> None:
    seen: list[Exception] = []
    resolver = TrialEntitlementResolver(
        catalog=_catalog(),
        store=_FailingStore(),  # type: ignore[arg-type]
        installation_binding=_INSTALLATION,
        deployment_binding=_DEPLOYMENT,
        on_storage_error=seen.append,
    )

    entitlement = resolver.resolve(now=_NOW)

    assert entitlement.available_capability_ids == frozenset()
    assert "unavailable" in entitlement.reason
    assert len(seen) == 1


def test_resolution_requires_an_aware_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _resolver(_Store(_record())).resolve(now=datetime(2026, 7, 27, 12, 0))


def test_restarting_does_not_renew_the_window() -> None:
    """A fresh resolver over the same durable record inherits the original activation."""

    record = _record(last_observed_at=_NOW)
    first = _resolver(_Store(record)).resolve(now=_NOW)
    second = _resolver(_Store(record)).resolve(now=_NOW)

    assert first.status is second.status is LicenseStatus.ACTIVE
    assert record.expires_at == _NOW + TRIAL_DURATION


class _StubTrial:
    def __init__(self, entitlement: object) -> None:
        self._entitlement = entitlement
        self.calls = 0

    def resolve(self, *, now: datetime) -> object:
        self.calls += 1
        return self._entitlement


def _authority(trial: object, *, token: str | None = None) -> object:
    from fdai.core.licensing import LicenseEntitlementAuthority

    class _RejectAll:
        def verify(self, document: bytes, signature: bytes) -> bool:
            return False

    return LicenseEntitlementAuthority(
        catalog=_catalog(),
        token=token,
        verifier=_RejectAll(),  # type: ignore[arg-type]
        trial=trial,  # type: ignore[arg-type]
    )


def test_the_execution_authority_consults_the_trial_when_no_token_grants() -> None:
    """Wiring check: every execution path resolves through this one authority."""

    from fdai.core.licensing.entitlement import Entitlement

    granted = Entitlement(
        status=LicenseStatus.ACTIVE,
        available_capability_ids=frozenset({"incident.restart"}),
        reason="active Trial window",
    )
    trial = _StubTrial(granted)

    entitlement = _authority(trial).resolve(now=_NOW)  # type: ignore[attr-defined]

    assert trial.calls == 1
    assert "incident.restart" in entitlement.available_capability_ids


def test_an_untrusted_token_is_not_rescued_by_a_trial() -> None:
    """A rejected token must stay rejected; a Trial substitutes only for absence."""

    from fdai.core.licensing.entitlement import Entitlement

    trial = _StubTrial(
        Entitlement(
            status=LicenseStatus.ACTIVE,
            available_capability_ids=frozenset({"incident.restart"}),
            reason="active Trial window",
        )
    )

    entitlement = _authority(trial, token="not-a-valid-token").resolve(now=_NOW)  # type: ignore[attr-defined]

    assert trial.calls == 0
    assert "incident.restart" not in entitlement.available_capability_ids


def test_an_authority_without_a_trial_is_unchanged() -> None:
    from fdai.core.licensing import LicenseEntitlementAuthority

    class _RejectAll:
        def verify(self, document: bytes, signature: bytes) -> bool:
            return False

    authority = LicenseEntitlementAuthority(
        catalog=_catalog(),
        token=None,
        verifier=_RejectAll(),  # type: ignore[arg-type]
    )

    # Read-only capability is unconditional; only acting capability is licensed.
    available = authority.resolve(now=_NOW).available_capability_ids
    assert available == {"cost.metering"}

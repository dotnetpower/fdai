"""Observation sources, fail-closed observer, and the delivery adapters.

The adapters translate one provider reading; the observer decides what that
reading is allowed to claim. The tests below pin the seam in both
directions: a healthy reading must survive translation intact, and every
unhealthy one must degrade to a retained hold rather than to silence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.executor.effect_observation import (
    IndependentEffectDisposition,
    IndependentEffectObservationBinding,
    IndependentEffectOutcome,
    ObservationCompleteness,
    ObservationContainment,
    ObservationFinality,
)
from fdai.core.executor.effect_observation_source import (
    ObservedEffectState,
    SafeguardEffectObserver,
    classify,
    quality_from,
)
from fdai.core.executor.execution_provenance import (
    SafeguardExecutionOrigin,
    SafeguardExecutionVenue,
)
from fdai.delivery.azure.vm_power_state import AzureVmPowerStateReading
from fdai.delivery.azure.vm_power_state_effect_source import (
    AzureVmPowerStateEffectSource,
    AzureVmPowerStateEffectSourceConfig,
)
from fdai.delivery.github.effect_state_source import (
    GitHubArtifactEffectSource,
    GitHubArtifactEffectSourceConfig,
    GitHubArtifactKind,
    GitHubArtifactReadError,
    GitHubArtifactReading,
    reading_from_payload,
)

_NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
_VM_REF = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
    "rg-evidence/providers/Microsoft.Compute/virtualMachines/vm-evidence"
)


def _digest(seed: str) -> str:
    return "sha256:" + (seed * 64)[:64]


def _binding() -> IndependentEffectObservationBinding:
    return IndependentEffectObservationBinding.create(
        action_id="00000000-0000-0000-0000-000000000001",
        action_payload_digest=_digest("a"),
        target_digest=_digest("b"),
        source_revision="commit:" + "c" * 40,
        execution_path="direct_api",
        execution_origin=SafeguardExecutionOrigin.CORE,
        execution_venue=SafeguardExecutionVenue.CORE,
        safeguard_bundle_digest=_digest("d"),
        evidence_identity_digest=_digest("e"),
        evidence_record_digest=_digest("f"),
        evidence_record_revision=1,
        executor_receipt_digest=_digest("1"),
    )


class _StubSource:
    """Return a scripted reading, or raise to simulate an unreachable source."""

    def __init__(
        self,
        *,
        state: ObservedEffectState | None = None,
        error: Exception | None = None,
        source_instance_id: str = "stub.source",
    ) -> None:
        self._state = state
        self._error = error
        self._source_instance_id = source_instance_id

    @property
    def source_instance_id(self) -> str:
        return self._source_instance_id

    async def read(
        self,
        *,
        binding: IndependentEffectObservationBinding,
    ) -> ObservedEffectState:
        del binding
        if self._error is not None:
            raise self._error
        assert self._state is not None
        return self._state


def _state(**overrides: object) -> ObservedEffectState:
    values: dict[str, object] = {
        "source_instance_id": "stub.source",
        "observed_at": _NOW,
        "source_recorded_at": _NOW - timedelta(seconds=30),
        "evidence_window_start": _NOW - timedelta(minutes=5),
        "evidence_window_end": _NOW,
        "expected_state_present": True,
    }
    values.update(overrides)
    return ObservedEffectState(**values)  # type: ignore[arg-type]


def _observer(source: _StubSource) -> SafeguardEffectObserver:
    return SafeguardEffectObserver(
        source=source,
        observer_instance_id="fdai.observer",
        executor_instance_id="fdai.executor",
        clock=lambda: _NOW,
    )


# -- classification -----------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    (
        ({}, IndependentEffectOutcome.VERIFIED),
        ({"expected_state_present": False}, IndependentEffectOutcome.FAILED),
        ({"expected_state_present": None}, IndependentEffectOutcome.MISSING),
        ({"conflicts": ("a", "b")}, IndependentEffectOutcome.CONFLICTING),
        ({"censoring_refs": ("denied",)}, IndependentEffectOutcome.CENSORED),
        ({"unavailable_reason": "timeout"}, IndependentEffectOutcome.UNAVAILABLE),
    ),
)
def test_a_reading_classifies_to_its_strongest_honest_outcome(
    overrides: dict[str, object],
    expected: IndependentEffectOutcome,
) -> None:
    outcome, reason = classify(_state(**overrides))

    assert outcome is expected
    assert reason


def test_unavailability_outranks_every_other_weakness() -> None:
    outcome, _reason = classify(
        _state(
            unavailable_reason="timeout",
            censoring_refs=("denied",),
            conflicts=("a",),
            expected_state_present=True,
        )
    )

    assert outcome is IndependentEffectOutcome.UNAVAILABLE


def test_quality_translation_preserves_every_axis() -> None:
    quality = quality_from(
        _state(complete=False, final=False, contained=False, conflicts=("a",), synthetic=True),
        max_source_age=timedelta(minutes=15),
    )

    assert quality.completeness is ObservationCompleteness.PARTIAL
    assert quality.finality is ObservationFinality.PROVISIONAL
    assert quality.containment is ObservationContainment.EXCEEDS_DECLARED_TARGET
    assert quality.conflicting_source_count == 1
    assert quality.synthetic is True
    assert quality.max_source_age_seconds == 900.0


def test_unknown_containment_is_preserved_rather_than_assumed() -> None:
    quality = quality_from(_state(contained=None), max_source_age=timedelta(minutes=15))

    assert quality.containment is ObservationContainment.UNKNOWN


# -- fail-closed observer -----------------------------------------------------


@pytest.mark.asyncio
async def test_an_unreachable_source_produces_a_retained_hold() -> None:
    observer = _observer(_StubSource(error=TimeoutError("provider timeout")))

    receipt = await observer.observe(
        binding=_binding(),
        observation_id="observation-1",
        sequence=1,
        prior_receipt_digest=None,
    )

    assert receipt.outcome is IndependentEffectOutcome.UNAVAILABLE
    assert receipt.disposition is IndependentEffectDisposition.UNKNOWN_HOLD
    assert receipt.effect_verified is False
    assert "TimeoutError" in receipt.reason


@pytest.mark.asyncio
async def test_a_healthy_reading_produces_a_verified_receipt() -> None:
    observer = _observer(_StubSource(state=_state()))

    receipt = await observer.observe(
        binding=_binding(),
        observation_id="observation-1",
        sequence=1,
        prior_receipt_digest=None,
    )

    assert receipt.outcome is IndependentEffectOutcome.VERIFIED
    assert receipt.effect_verified is True
    assert receipt.binding == _binding()


@pytest.mark.asyncio
async def test_a_partial_reading_never_reaches_verified() -> None:
    observer = _observer(_StubSource(state=_state(complete=False)))

    receipt = await observer.observe(
        binding=_binding(),
        observation_id="observation-1",
        sequence=1,
        prior_receipt_digest=None,
    )

    assert receipt.disposition is IndependentEffectDisposition.UNKNOWN_HOLD


@pytest.mark.parametrize(
    ("observer_id", "executor_id", "source_id"),
    (
        ("same", "same", "source"),
        ("same", "executor", "same"),
        ("observer", "same", "same"),
    ),
)
def test_the_observer_refuses_overlapping_identities(
    observer_id: str,
    executor_id: str,
    source_id: str,
) -> None:
    with pytest.raises(ValueError, match="MUST differ"):
        SafeguardEffectObserver(
            source=_StubSource(state=_state(), source_instance_id=source_id),
            observer_instance_id=observer_id,
            executor_instance_id=executor_id,
        )


# -- Azure VM power-state adapter --------------------------------------------


def _vm_reading(state: str | None, **overrides: object) -> AzureVmPowerStateReading:
    """Build a reading that satisfies the shipped source invariants.

    ``complete`` is derived rather than passed so a fixture cannot claim a
    completeness the reading contract would reject.
    """

    conflicts = overrides.pop("conflicts", ())
    values: dict[str, object] = {
        "resource_ref": _VM_REF,
        "target_revision": 1,
        "state": state,
        "observed_at": _NOW,
        "recorded_at": _NOW,
        "fresh_until": _NOW + timedelta(minutes=5),
        "complete": state is not None or bool(conflicts),
        "conflicts": conflicts,
        "censoring_refs": (),
        "evidence_refs": (_digest("7"),),
    }
    values.update(overrides)
    return AzureVmPowerStateReading(**values)  # type: ignore[arg-type]


class _StubVmSource:
    def __init__(self, reading: AzureVmPowerStateReading) -> None:
        self._reading = reading

    async def observe(
        self,
        *,
        resource_ref: str,
        target_revision: int,
    ) -> AzureVmPowerStateReading:
        del resource_ref, target_revision
        return self._reading


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("power_state", "expected"),
    (
        ("running", True),
        ("deallocated", False),
        ("stopped", False),
        ("starting", None),
        (None, None),
    ),
)
async def test_the_vm_adapter_reports_only_what_arm_proved(
    power_state: str | None,
    expected: bool | None,
) -> None:
    source = AzureVmPowerStateEffectSource(
        source=_StubVmSource(_vm_reading(power_state)),
        config=AzureVmPowerStateEffectSourceConfig(
            resource_ref=_VM_REF,
            target_revision=1,
            source_instance_id="azure.arm",
        ),
    )

    state = await source.read(binding=_binding())

    assert state.expected_state_present is expected
    assert state.source_instance_id == "azure.arm"


@pytest.mark.asyncio
async def test_a_transitioning_vm_is_provisional_rather_than_failed() -> None:
    source = AzureVmPowerStateEffectSource(
        source=_StubVmSource(_vm_reading("starting")),
        config=AzureVmPowerStateEffectSourceConfig(
            resource_ref=_VM_REF,
            target_revision=1,
            source_instance_id="azure.arm",
        ),
    )

    state = await source.read(binding=_binding())

    assert state.final is False
    assert classify(state)[0] is IndependentEffectOutcome.MISSING


@pytest.mark.asyncio
async def test_the_vm_adapter_forwards_conflicts_and_censorship() -> None:
    source = AzureVmPowerStateEffectSource(
        source=_StubVmSource(_vm_reading("running", conflicts=("arg",), censoring_refs=("rbac",))),
        config=AzureVmPowerStateEffectSourceConfig(
            resource_ref=_VM_REF,
            target_revision=1,
            source_instance_id="azure.arm",
        ),
    )

    state = await source.read(binding=_binding())

    assert state.conflicts == ("arg",)
    assert state.censoring_refs == ("rbac",)
    assert classify(state)[0] is IndependentEffectOutcome.CENSORED


def test_the_vm_adapter_config_refuses_an_unpinned_target() -> None:
    with pytest.raises(ValueError, match="revision MUST be positive"):
        AzureVmPowerStateEffectSourceConfig(
            resource_ref=_VM_REF,
            target_revision=0,
            source_instance_id="azure.arm",
        )


# -- GitHub artifact adapter --------------------------------------------------


class _StubArtifactReader:
    def __init__(self, reading: GitHubArtifactReading) -> None:
        self._reading = reading

    async def read_artifact(
        self,
        *,
        owner: str,
        repo: str,
        kind: GitHubArtifactKind,
        number: int,
    ) -> GitHubArtifactReading:
        del owner, repo, kind, number
        return self._reading


def _artifact(**overrides: object) -> GitHubArtifactReading:
    values: dict[str, object] = {
        "exists": True,
        "state": "open",
        "head_sha": "a" * 40,
        "merged": False,
        "auto_merge_enabled": False,
        "labels": ("hil",),
        "observed_at": _NOW,
        "recorded_at": _NOW,
    }
    values.update(overrides)
    return GitHubArtifactReading(**values)  # type: ignore[arg-type]


def _artifact_source(
    reading: GitHubArtifactReading,
    **config: object,
) -> GitHubArtifactEffectSource:
    values: dict[str, object] = {
        "owner": "example",
        "repo": "evidence",
        "kind": GitHubArtifactKind.PULL_REQUEST,
        "number": 7,
        "source_instance_id": "github.rest",
    }
    values.update(config)
    return GitHubArtifactEffectSource(
        reader=_StubArtifactReader(reading),
        config=GitHubArtifactEffectSourceConfig(**values),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_an_existing_pull_request_proves_the_declared_effect() -> None:
    state = await _artifact_source(_artifact()).read(binding=_binding())

    assert state.expected_state_present is True


@pytest.mark.asyncio
async def test_an_absent_artifact_is_a_failed_effect_not_an_unknown() -> None:
    state = await _artifact_source(_artifact(exists=False, state=None)).read(binding=_binding())

    assert state.expected_state_present is False
    assert classify(state)[0] is IndependentEffectOutcome.FAILED


@pytest.mark.asyncio
async def test_a_mismatched_head_revision_fails_the_effect() -> None:
    source = _artifact_source(_artifact(), expected_head_sha="b" * 40)

    state = await source.read(binding=_binding())

    assert state.expected_state_present is False
    assert "head does not match" in state.detail


@pytest.mark.asyncio
async def test_auto_merge_on_a_manual_merge_path_fails_the_effect() -> None:
    source = _artifact_source(_artifact(auto_merge_enabled=True), require_manual_merge=True)

    state = await source.read(binding=_binding())

    assert state.expected_state_present is False
    assert "auto-merge" in state.detail


@pytest.mark.asyncio
async def test_a_missing_required_label_fails_the_effect() -> None:
    source = _artifact_source(_artifact(labels=()), required_label="hil")

    state = await source.read(binding=_binding())

    assert state.expected_state_present is False


@pytest.mark.asyncio
async def test_a_censored_artifact_read_is_incomplete() -> None:
    state = await _artifact_source(_artifact(censoring_refs=("private-repo",))).read(
        binding=_binding()
    )

    assert state.complete is False
    assert classify(state)[0] is IndependentEffectOutcome.CENSORED


@pytest.mark.asyncio
async def test_an_issue_artifact_uses_the_same_reader() -> None:
    source = _artifact_source(_artifact(head_sha=None), kind=GitHubArtifactKind.ISSUE)

    state = await source.read(binding=_binding())

    assert state.expected_state_present is True
    assert "issue" in state.detail


def test_a_missing_artifact_may_not_claim_a_state() -> None:
    with pytest.raises(ValueError, match="MUST NOT report a state"):
        _artifact(exists=False)


def test_a_rest_payload_translates_into_a_bounded_reading() -> None:
    reading = reading_from_payload(
        {
            "state": "open",
            "updated_at": "2026-09-13T11:59:00Z",
            "head": {"sha": "a" * 40},
            "merged": False,
            "auto_merge": {"merge_method": "squash"},
            "labels": [{"name": "hil"}, {"name": "remediation"}],
        },
        kind=GitHubArtifactKind.PULL_REQUEST,
        observed_at=_NOW,
    )

    assert reading.exists is True
    assert reading.auto_merge_enabled is True
    assert reading.labels == ("hil", "remediation")
    assert reading.head_sha == "a" * 40


@pytest.mark.parametrize(
    "payload",
    (
        {"updated_at": "2026-09-13T11:59:00Z"},
        {"state": "open"},
        {"state": "open", "updated_at": "not-a-time"},
        {"state": "open", "updated_at": "2026-09-13T11:59:00"},
    ),
)
def test_an_untrustworthy_rest_payload_is_refused(payload: dict[str, object]) -> None:
    with pytest.raises(GitHubArtifactReadError):
        reading_from_payload(
            payload,
            kind=GitHubArtifactKind.PULL_REQUEST,
            observed_at=_NOW,
        )


@pytest.mark.asyncio
async def test_a_raising_artifact_reader_degrades_to_a_hold() -> None:
    class _Broken:
        source_instance_id = "github.rest"

        async def read(
            self,
            *,
            binding: IndependentEffectObservationBinding,
        ) -> ObservedEffectState:
            del binding
            raise GitHubArtifactReadError("forbidden")

    observer = SafeguardEffectObserver(
        source=_Broken(),
        observer_instance_id="fdai.observer",
        executor_instance_id="fdai.executor",
        clock=lambda: _NOW,
    )

    receipt = await observer.observe(
        binding=_binding(),
        observation_id="observation-1",
        sequence=1,
        prior_receipt_digest=None,
    )

    assert receipt.disposition is IndependentEffectDisposition.UNKNOWN_HOLD

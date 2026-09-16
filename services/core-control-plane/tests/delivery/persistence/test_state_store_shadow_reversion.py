"""Tests for the durable, unbound shadow-reversion writer."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from fdai.core.standing_authority.effect_shadow_reversion import (
    EffectEvidenceDisposition,
    ShadowReversionTransition,
)
from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.shadow_reversion_command import (
    ExpectedAuthorizationState,
    ShadowReversionCommand,
    ShadowReversionIntent,
    ShadowReversionOutcome,
    ShadowReversionSafetyBindings,
    ShadowReversionWriter,
    apply_shadow_reversion,
)
from fdai.delivery.persistence.state_store_shadow_reversion import (
    PersistedShadowReversionRegistry,
    ShadowReversionApprovalVerifier,
    StateStoreShadowReversionWriter,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.standing_authority import StandingAuthorizationLifecycleStore
from fdai.shared.providers.state_store import StateStore

_NOW = datetime(2026, 9, 16, 8, 0, tzinfo=UTC)
_FENCE = LifecycleFence(
    family_id="family:one",
    revision_id="sha256:" + "a" * 64,
    fencing_generation=3,
    transition_digest="sha256:" + "b" * 64,
)


def _command(*, action_types: tuple[str, ...] = ("ops.start-vm@1.0.0",)) -> ShadowReversionCommand:
    return ShadowReversionCommand(
        source_revision_id="c" * 40,
        reverted_action_types=action_types,
        finding_id="sha256:" + "d" * 64,
        plan_id="sha256:" + "e" * 64,
        disposition=EffectEvidenceDisposition.FAILED,
        required_transition=ShadowReversionTransition.RETURN_TO_SHADOW,
        reason_code="effects_mismatched",
        expected_authorization=_FENCE,
        expected_authorization_state=ExpectedAuthorizationState.ACTIVE,
        safety=ShadowReversionSafetyBindings(
            stop_condition_ref="stop:provider_api_error_streak",
            rollback_plan_ref="rollback:ops.deallocate-vm",
            kill_switch_ref="killswitch:system/kill-switch",
            blast_radius_scope="resource",
        ),
        proposer_principal="human:proposer",
        reviewer_principal="human:reviewer",
        authentication_evidence_digest="sha256:" + "f" * 64,
        proposed_at=_NOW,
    )


class _Store:
    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.audits: list[Mapping[str, Any]] = []

    async def read_state(self, key: str) -> Mapping[str, Any] | None:
        value = self.states.get(key)
        return dict(value) if value is not None else None

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if key in self.states:
            return False
        self.states[key] = dict(value)
        self.audits.append(dict(audit_entry))
        return True

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        current = self.states.get(key)
        if current is None or current.get("revision") != expected_revision:
            return False
        self.states[key] = dict(value)
        self.audits.append(dict(audit_entry))
        return True


class _Lifecycle:
    def __init__(self, results: list[bool] | None = None) -> None:
        self.results = list(results or [True])
        self.calls = 0

    async def check_fence(self, fence: LifecycleFence) -> bool:
        assert fence == _FENCE
        index = min(self.calls, len(self.results) - 1)
        self.calls += 1
        return self.results[index]


class _Registry:
    def __init__(
        self,
        *,
        mode: Mode = Mode.ENFORCE,
        persist_error: Exception | None = None,
    ) -> None:
        self.mode = mode
        self.persist_error = persist_error
        self.refreshes = 0
        self.demotions = 0
        self.persists = 0

    def mode_of(self, action_type: str) -> Mode:
        assert action_type == "ops.start-vm"
        return self.mode

    def demote(self, action_type_name: str) -> object:
        assert action_type_name == "ops.start-vm"
        self.demotions += 1
        self.mode = Mode.SHADOW
        return object()

    async def refresh_for_update(self, action_type: str) -> None:
        assert action_type == "ops.start-vm"
        self.refreshes += 1

    async def persist(self, action_type: str) -> None:
        assert action_type == "ops.start-vm"
        self.persists += 1
        if self.persist_error is not None:
            raise self.persist_error


class _Approvals:
    def __init__(self, accepted: bool | list[bool] = True) -> None:
        self.results = list(accepted) if isinstance(accepted, list) else [accepted]
        self.commands: list[str] = []

    async def verify(self, command: ShadowReversionCommand) -> bool:
        self.commands.append(command.command_id)
        index = min(len(self.commands) - 1, len(self.results) - 1)
        return self.results[index]


def _writer(
    *,
    store: _Store | None = None,
    lifecycle: _Lifecycle | None = None,
    registry: _Registry | None = None,
    approvals: _Approvals | None = None,
) -> tuple[StateStoreShadowReversionWriter, _Store, _Lifecycle, _Registry, _Approvals]:
    store = store or _Store()
    lifecycle = lifecycle or _Lifecycle()
    registry = registry or _Registry()
    approvals = approvals or _Approvals()
    return (
        StateStoreShadowReversionWriter(
            store=cast(StateStore, store),
            lifecycle=cast(StandingAuthorizationLifecycleStore, lifecycle),
            registry=cast(PersistedShadowReversionRegistry, registry),
            approvals=cast(ShadowReversionApprovalVerifier, approvals),
        ),
        store,
        lifecycle,
        registry,
        approvals,
    )


async def test_authorized_reversion_records_two_phase_audit_and_persists_shadow() -> None:
    writer, store, lifecycle, registry, approvals = _writer()
    command = _command()

    terminal = await apply_shadow_reversion(command=command, writer=writer, recorded_at=_NOW)

    assert terminal.outcome is ShadowReversionOutcome.APPLIED
    assert registry.mode is Mode.SHADOW
    assert registry.demotions == registry.persists == 1
    assert lifecycle.calls == 3
    assert approvals.commands == [command.command_id, command.command_id]
    state = store.states[f"shadow-reversion:{command.idempotency_key}"]
    assert state["state"] == "terminal"
    assert state["registry_mode"] == Mode.SHADOW.value
    assert [entry["action_kind"] for entry in store.audits] == [
        "shadow_reversion.intent_recorded",
        "shadow_reversion.claimed",
        "shadow_reversion.applied",
        "shadow_reversion.terminal_recorded",
    ]


async def test_replay_is_duplicate_without_a_second_registry_write() -> None:
    writer, store, _, registry, _ = _writer()
    command = _command()

    first = await apply_shadow_reversion(command=command, writer=writer, recorded_at=_NOW)
    second = await apply_shadow_reversion(command=command, writer=writer, recorded_at=_NOW)

    assert first.outcome is ShadowReversionOutcome.APPLIED
    assert second.outcome is ShadowReversionOutcome.DUPLICATE
    assert registry.demotions == registry.persists == 1
    assert len(store.audits) == 4


async def test_already_shadow_registry_closes_without_rewriting_authority() -> None:
    registry = _Registry(mode=Mode.SHADOW)
    writer, _, _, _, _ = _writer(registry=registry)

    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=_NOW)

    assert terminal.outcome is ShadowReversionOutcome.APPLIED
    assert registry.demotions == registry.persists == 0


async def test_rejected_approval_records_failure_and_preserves_enforce() -> None:
    registry = _Registry()
    writer, store, _, _, _ = _writer(registry=registry, approvals=_Approvals(False))

    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=_NOW)

    assert terminal.outcome is ShadowReversionOutcome.REJECTED_WRITER_FAILURE
    assert registry.mode is Mode.ENFORCE
    assert store.states[next(iter(store.states))]["state"] == "terminal"


async def test_fence_change_between_intent_and_apply_blocks_reversion() -> None:
    registry = _Registry()
    writer, store, _, _, _ = _writer(
        lifecycle=_Lifecycle([True, False]),
        registry=registry,
    )

    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=_NOW)

    assert terminal.outcome is ShadowReversionOutcome.REJECTED_WRITER_FAILURE
    assert registry.mode is Mode.ENFORCE
    assert store.states[next(iter(store.states))]["state"] == "terminal"


async def test_approval_withdrawn_after_claim_blocks_registry_mutation() -> None:
    registry = _Registry()
    writer, store, _, _, _ = _writer(
        registry=registry,
        approvals=_Approvals([True, False]),
    )

    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=_NOW)

    assert terminal.outcome is ShadowReversionOutcome.REJECTED_WRITER_FAILURE
    assert registry.mode is Mode.ENFORCE
    assert store.states[next(iter(store.states))]["state"] == "applying"


async def test_fence_change_after_claim_blocks_registry_mutation() -> None:
    registry = _Registry()
    writer, store, _, _, _ = _writer(
        lifecycle=_Lifecycle([True, True, False]),
        registry=registry,
    )

    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=_NOW)

    assert terminal.outcome is ShadowReversionOutcome.REJECTED_WRITER_FAILURE
    assert registry.mode is Mode.ENFORCE
    assert store.states[next(iter(store.states))]["state"] == "applying"


async def test_registry_persist_failure_never_restores_local_enforce_mode() -> None:
    registry = _Registry(persist_error=RuntimeError("store unavailable"))
    writer, store, _, _, _ = _writer(registry=registry)

    terminal = await apply_shadow_reversion(command=_command(), writer=writer, recorded_at=_NOW)

    assert terminal.outcome is ShadowReversionOutcome.REJECTED_WRITER_FAILURE
    assert registry.mode is Mode.SHADOW
    assert store.states[next(iter(store.states))]["state"] == "applying"


async def test_restart_recovers_after_uncertain_registry_persistence() -> None:
    failed_registry = _Registry(persist_error=RuntimeError("store unavailable"))
    writer, store, _, _, _ = _writer(registry=failed_registry)
    command = _command()
    first = await apply_shadow_reversion(command=command, writer=writer, recorded_at=_NOW)
    assert first.outcome is ShadowReversionOutcome.REJECTED_WRITER_FAILURE

    durable_registry = _Registry(mode=Mode.ENFORCE)
    restarted, _, _, _, _ = _writer(store=store, registry=durable_registry)
    recovered = await apply_shadow_reversion(
        command=command,
        writer=restarted,
        recorded_at=_NOW,
    )

    assert recovered.outcome is ShadowReversionOutcome.APPLIED
    assert durable_registry.mode is Mode.SHADOW
    assert durable_registry.demotions == durable_registry.persists == 1
    assert store.states[f"shadow-reversion:{command.idempotency_key}"]["state"] == "terminal"


async def test_restart_recovers_an_applying_command_without_new_intent() -> None:
    command = _command()
    intent = ShadowReversionIntent(
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        expected_authorization=command.expected_authorization,
        recorded_at=_NOW,
    )
    writer, store, _, registry, _ = _writer()
    assert await writer.record_intent(intent)
    key = f"shadow-reversion:{command.idempotency_key}"
    store.states[key] = {
        **store.states[key],
        "state": "applying",
        "revision": 2,
        "command": command.audit_body(),
    }
    restarted, _, _, _, _ = _writer(store=store, registry=registry)

    terminal = await apply_shadow_reversion(
        command=command,
        writer=restarted,
        recorded_at=_NOW,
    )

    assert terminal.outcome is ShadowReversionOutcome.APPLIED
    assert registry.demotions == registry.persists == 1
    assert store.states[key]["state"] == "terminal"


async def test_multi_action_command_is_rejected_before_registry_mutation() -> None:
    writer, store, _, registry, _ = _writer()
    command = _command(action_types=("ops.restart@1.0.0", "ops.start-vm@1.0.0"))

    terminal = await apply_shadow_reversion(command=command, writer=writer, recorded_at=_NOW)

    assert terminal.outcome is ShadowReversionOutcome.REJECTED_WRITER_FAILURE
    assert registry.demotions == registry.persists == 0
    assert store.states[next(iter(store.states))]["state"] == "terminal"


def test_adapter_structurally_satisfies_the_writer_protocol() -> None:
    writer, _, _, _, _ = _writer()

    assert isinstance(writer, ShadowReversionWriter)

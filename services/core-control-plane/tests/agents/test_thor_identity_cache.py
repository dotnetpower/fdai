"""Cached publication and authority identities preserve exact JSON value types."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fdai.agents._framework.action_run_identity import action_run_identity_digest
from fdai.agents._framework.thor_preflight import PreflightSimulationResult
from fdai.agents.thor import ActionRun, ActionRunState, Thor
from fdai_service_contracts.compatibility import canonical_digest

from tests.agents.test_thor_durable import (
    _approval_for_run,
    _safe_semantics,
    _safeguards,
    _verdict,
)


def _run() -> ActionRun:
    return ActionRun(
        correlation_id="identity-cache",
        action_type="example.action",
        resource_id="resource:identity-cache",
        state=ActionRunState.HIL_PENDING,
        verdict="hil",
    )


@pytest.mark.parametrize("field", ["params", "workflow_action"])
@pytest.mark.parametrize("mutate_cached", [False, True])
@pytest.mark.parametrize(
    "prior,replacement",
    [(True, 1), (False, 0), (1, True), (1.0, 1), (1, 1.0), (0.0, -0.0)],
)
def test_cached_identity_cannot_alias_changed_json_types(
    field: str, mutate_cached: bool, prior: object, replacement: object
) -> None:
    run = _run()
    value: dict[str, Any] = {"nested": [{"value": prior}]}
    setattr(run, field, value)
    initial = run.action_run_identity()
    if mutate_cached:
        run.publication_identity_payload()[field]["nested"][0]["value"] = replacement
    else:
        value["nested"][0]["value"] = replacement
    expected = action_run_identity_digest(run.to_dict())

    assert run.action_run_identity() == expected
    assert canonical_digest(run.publication_identity_payload()[field]) == canonical_digest(
        getattr(run, field)
    )
    assert (run.action_run_identity() == initial) is mutate_cached


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_invalid_current_json_cannot_reuse_an_old_cached_identity(invalid: float) -> None:
    run = _run()
    run.params = {"value": 1.0}
    run.action_run_identity()
    run.params["value"] = invalid
    with pytest.raises(ValueError, match="canonical JSON"):
        run.action_run_identity()


async def test_changed_json_identity_is_rejected_by_actual_preflight_consumer() -> None:
    live: dict[str, ActionRun] = {}

    class Simulator:
        async def simulate(self, run: ActionRun) -> PreflightSimulationResult:
            value = live["run"].params["replica_count"]
            assert isinstance(value, int) and not isinstance(value, bool)
            live["run"].params["replica_count"] = float(value)
            return PreflightSimulationResult("passed", "type-alias-regression", "1")

    executor = AsyncMock(return_value=True)
    host = Thor(
        executor=executor,
        preflight_simulator=Simulator(),
        action_semantics_catalog=_safe_semantics(irreversible=True),
    )
    verdict = _verdict()
    verdict["producer_principal"] = "Forseti"
    verdict["idempotency_key"] = "cached-json-preflight"
    verdict["safeguards"] = _safeguards()
    run = await host.dispatch_verdict(verdict)
    live["run"] = run
    await host.on_typed_message("object.approval", _approval_for_run(run))

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "preflight_error"
    executor.assert_not_awaited()


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("original_quorum_required", 0, "quorum"),
        ("evidence_rejection_ref", "invalid", "SHA-256"),
        ("batch_role", "invalid", "batch role"),
        ("target_count", 0, "target count"),
        ("target_set", (), "target set"),
    ],
)
def test_malformed_stable_fields_cannot_enter_the_cache(
    field: str, value: object, reason: str
) -> None:
    invalid: dict[str, Any] = {field: value}
    with pytest.raises(ValueError, match=reason):
        ActionRun(
            correlation_id="invalid-cache-input",
            action_type="example.action",
            resource_id="resource:identity-cache",
            state=ActionRunState.HIL_PENDING,
            verdict="hil",
            **invalid,
        )


def test_incomplete_lineage_cannot_enter_a_rehydrated_cache() -> None:
    payload = _run().to_dict()
    payload["prospective_lineage"] = {"unbound": True}
    with pytest.raises(ValueError, match="requires a kinetic proposal"):
        ActionRun.from_dict(payload)


def test_nested_approval_profile_cannot_enter_a_publication_cache() -> None:
    run = _run()
    run.approval_profile = {"nested": [True]}
    with pytest.raises(ValueError, match="must be flat"):
        run.action_run_identity()


@pytest.mark.parametrize("prior,replacement", [(True, 1), (0.0, -0.0)])
def test_python_mapping_key_aliases_cannot_preserve_a_different_wire_identity(
    prior: object, replacement: object
) -> None:
    run = _run()
    run.params = {"mapping": {prior: "value"}}
    run.action_run_identity()
    run.params = {"mapping": {replacement: "value"}}
    assert run.action_run_identity() == action_run_identity_digest(run.to_dict())

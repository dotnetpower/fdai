"""The rebuild command requires independent admission and resumes idempotently."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from fdai.core.assurance_twin import EffectModelStatus, StateStoreEffectModelRegistry
from fdai.core.mscp_profile.response_outcome import response_outcome_audit_entry
from fdai.delivery import measurement_runner_cli as cli
from fdai.delivery.measurement.feedback_revision_source import PostgresFeedbackRevisionSource
from fdai.shared.contracts.models import ResponseOutcome
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from tests.assurance_twin.test_feedback_rebuild import _AS_OF, _admission, _corrected
from tests.assurance_twin.test_feedback_reliability import _challenger, _feedback
from tests.assurance_twin.test_model_registry import _model, _registry


class _ScopeSource(PostgresFeedbackRevisionSource):
    def __init__(self, outcomes: tuple[ResponseOutcome, ...]) -> None:
        super().__init__(dsn="unused-local-fake", clock=lambda: _AS_OF)
        self.outcomes = outcomes

    async def _rows(self, revision_digests: tuple[str, ...]) -> Sequence[Mapping[str, Any]]:
        return [{"entry": response_outcome_audit_entry(item)} for item in self.outcomes]

    async def outcomes_for_scope(
        self,
        *,
        action_type_id: str,
        metric: str,
    ) -> tuple[ResponseOutcome, ...]:
        assert action_type_id == "ops.scale-out" and metric == "latency_p99_ms"
        return self.outcomes


async def test_command_requires_review_then_rebuilds_and_resumes_without_duplication(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = InMemoryStateStore()
    seed = _model(EffectModelStatus.CHALLENGER)
    original = _registry(store)
    await original.register(seed, registered_by="Mimir")
    first = _feedback(1)
    assert (await original.update_from_outcome(first)).accepted
    corrected = _corrected(first)
    assert (
        await original.update_from_outcome(corrected)
    ).reason == "outcome_revision_requires_rebuild"
    source = _ScopeSource((first, corrected))
    registry = StateStoreEffectModelRegistry(
        store,
        clock=lambda: _AS_OF,
        feedback_source=source,
    )
    admitted = False
    manifests: list[str] = []

    class Reviewed:
        def __init__(self, *, store: InMemoryStateStore) -> None:
            pass

        async def admit(self, **subject: str) -> DecisionEvidenceAdmission | None:
            manifests.append(subject["evidence_digest"])
            return _admission(subject["source_revision"]) if admitted else None

    monkeypatch.setenv("FDAI_STATE_STORE_DSN", "unused-local-fake")
    monkeypatch.setenv("FDAI_EXECUTION_VENUE", "local")
    monkeypatch.setenv("FDAI_EFFECT_REBUILD_ACTION_TYPE", seed.action_type_id)
    monkeypatch.setenv("FDAI_EFFECT_REBUILD_METRIC", seed.metric)
    monkeypatch.setattr(cli, "PostgresStateStore", lambda **_: store)
    monkeypatch.setattr(cli, "PostgresFeedbackRevisionSource", lambda **_: source)
    monkeypatch.setattr(cli, "StateStoreEffectModelRegistry", lambda *_, **__: registry)
    monkeypatch.setattr(cli, "StateStoreDecisionEvidenceAdmissionProvider", Reviewed)
    before = tuple(store.audit_entries)
    assert await cli._run_mode(cli.MeasurementMode.DYNAMIC_REBUILD) == 3
    subject = json.loads(capsys.readouterr().out)
    assert subject == {
        "status": "review_required",
        "input_manifest_digest": manifests[0].removeprefix("sha256:"),
        "execution_authority": False,
        "promotion_authority": False,
    }
    assert tuple(store.audit_entries) == before
    admitted = True
    assert await cli._run_mode(cli.MeasurementMode.DYNAMIC_REBUILD) == 0
    model = await _challenger(registry)
    assert model is not None and model.sample_count == 1 and model.bias_correction == -10.0
    after = tuple(store.audit_entries)
    assert await cli._run_mode(cli.MeasurementMode.DYNAMIC_REBUILD) == 0
    assert tuple(store.audit_entries) == after
    assert len(set(manifests)) == 1


async def test_deployed_rebuild_cannot_fall_back_to_local_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_EXECUTION_VENUE", "deployed")
    monkeypatch.delenv("FDAI_STATE_STORE_DSN", raising=False)
    assert await cli._run_mode(cli.MeasurementMode.DYNAMIC_REBUILD) == 3


async def test_preview_binds_actual_applied_order_not_uuid_or_source_iteration() -> None:
    store = InMemoryStateStore()
    registry = _registry(store)
    seed = _model(EffectModelStatus.CHALLENGER)
    await registry.register(seed, registered_by="Mimir")
    assert (await registry.update_from_outcome(_feedback(2))).accepted
    assert (await registry.update_from_outcome(_feedback(1))).accepted
    preview = await registry.preview_rebuild(
        seed=seed,
        outcomes=(_feedback(1), _feedback(2)),
        as_of=_AS_OF,
    )
    assert preview is not None
    assert preview.replay_order == (str(_feedback(2).outcome_id), str(_feedback(1).outcome_id))

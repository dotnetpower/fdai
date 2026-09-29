"""Production startup binds shadow comparisons to its existing state store."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fdai.composition import Container, bind_context_selection_shadow, install_capability_bundle
from fdai.core.capability_catalog import (
    Capability,
    CapabilityBinding,
    CapabilityBindingKind,
    CapabilityBundle,
    CapabilityCategory,
    SideEffectClass,
)
from fdai.core.conversation.semantic_runtime import SemanticTurnResult as RuntimeSemanticTurnResult
from fdai.core.conversation.session import Principal, Turn
from fdai.core.working_context import (
    DEFAULT_CONTEXT_SELECTION_POLICY,
    ContextPolicyIdentity,
    ContextSelectionInput,
    ContextSelectionOutput,
    ContextShadowConfig,
)
from fdai.runtime import bootstrap
from fdai.runtime.bootstrap_lifecycle import build_semantic_turn_binding
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import SemanticDirectResponseIntent

CAPABILITY_ID = "context.selection.runtime-shadow-v1"
POLICY_REF = "runtime-shadow-v1@1.0.0"


class _CandidatePolicy:
    policy_id = "runtime-shadow-v1"
    policy_version = "1.0.0"

    def select(self, selection_input: ContextSelectionInput) -> ContextSelectionOutput:
        return DEFAULT_CONTEXT_SELECTION_POLICY.select(selection_input)


class _Runtime:
    def __init__(self) -> None:
        self.prior_turns: tuple[Turn, ...] = ()

    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        **_: object,
    ) -> RuntimeSemanticTurnResult:
        assert principal.id == "operator-1"
        self.prior_turns = prior_turns
        return RuntimeSemanticTurnResult(
            disposition="direct_response",
            reason="semantic_direct_response",
            planning=SimpleNamespace(
                direct_response_intent=SemanticDirectResponseIntent.GREETING,
                direct_response_answer=f"Received {utterance}",
                model_observations=(),
            ),
        )


def _bundle() -> CapabilityBundle:
    return CapabilityBundle(
        capabilities=(
            Capability(
                capability_id=CAPABILITY_ID,
                name="Runtime shadow policy",
                category=CapabilityCategory.INVESTIGATION,
                summary="Runtime shadow evaluation test policy.",
                side_effect_class=SideEffectClass.READ,
            ),
        ),
        bindings=(
            CapabilityBinding(
                capability_id=CAPABILITY_ID,
                kind=CapabilityBindingKind.CONTEXT_SELECTION_POLICY,
                target_ref=POLICY_REF,
            ),
        ),
    )


def _enable_shadow_candidate(container: Container) -> Container:
    installed = install_capability_bundle(
        container,
        _bundle(),
        context_selection_policies=(POLICY_REF,),
    )
    authority = installed.context_selection_policy_authority
    assert authority is not None
    record = authority.install(
        cast(Any, _CandidatePolicy()),
        capability_id=CAPABILITY_ID,
        expected_revision=authority.snapshot().revision,
    )
    authority.enable_shadow(
        ContextPolicyIdentity(_CandidatePolicy.policy_id, _CandidatePolicy.policy_version),
        expected_revision=record.revision,
    )
    return installed


def _request(*, idempotency_key: str) -> dict[str, object]:
    requested_at = datetime.now(UTC)
    deadline_at = requested_at + timedelta(seconds=30)
    return {
        "schema_version": "1.2.0",
        "request_id": "00000000-0000-0000-0000-000000000201",
        "correlation_id": "semantic-correlation-runtime",
        "idempotency_key": idempotency_key,
        "resource_ref": "operator-conversation:runtime",
        "request_kind": "semantic_query",
        "requested_at": requested_at.isoformat(),
        "semantic_turn": {
            "utterance": "Show current operations evidence.",
            "principal": {"subject_id": "operator-1", "roles": ["Reader"]},
            "session_id": "session-1",
            "turn_id": "turn-1",
            "turn_sequence": 3,
            "locale": "en",
            "purpose": "operations-review",
            "deadline_at": deadline_at.isoformat(),
            "prior_turns": [{"role": "user", "content": "What changed recently?"}],
            "cancelled": False,
            "execution_authority": False,
        },
    }


async def _process_turn(
    *,
    state_store: InMemoryStateStore,
    container: Any,
    runtime: _Runtime,
    idempotency_key: str,
) -> dict[str, Any]:
    binding = build_semantic_turn_binding(
        state_store=state_store,
        runtime=runtime,
        config={
            "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.request",
            "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "operator.projection",
        },
        context_selection_policy_authority=container.context_selection_policy_authority,
        context_selection_shadow_runner=container.context_selection_shadow_runner,
    )
    assert binding is not None
    payload = await binding.processor.process(_request(idempotency_key=idempotency_key))
    loaded = json.loads(payload)
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize("drain_outcome", ["complete", "fail", "timeout"])
async def test_consumer_bootstrap_binds_and_drains_context_shadow(
    container: Container,
    monkeypatch: pytest.MonkeyPatch,
    drain_outcome: str,
) -> None:
    store = InMemoryStateStore()
    observed: list[str] = []

    class _Resources:
        health_server: Any = None
        http_client: Any = None
        state_store: Any = None
        development_diagnostics: Any = None

        async def close(self) -> None:
            observed.append("close")

    async def _open_health_port() -> object:
        return object()

    async def _load_values(**_: object) -> dict[str, object]:
        return {}

    async def _build_core_runtime(**kwargs: object) -> None:
        bound = kwargs["container"]
        assert isinstance(bound, Container)
        assert kwargs["state_store"] is store
        runner = bound.context_selection_shadow_runner
        assert runner is not None
        assert bound.context_selection_policy_authority is runner._authority
        observed.append("bound")

        async def _drain() -> None:
            observed.append("drain")
            if drain_outcome == "fail":
                raise RuntimeError("drain failed")
            if drain_outcome == "timeout":
                await asyncio.Event().wait()

        monkeypatch.setattr(runner, "drain", _drain)
        raise RuntimeError("stop after production composition")

    plan = SimpleNamespace(
        start_consumer=True,
        identity_requests=SimpleNamespace(
            case_history=False, configuration_drift=False, telemetry=False
        ),
        requires_initial_identity=False,
        consumer_requires_workload_identity=False,
    )
    monkeypatch.setattr(bootstrap, "default_container_from_env", lambda: container)
    monkeypatch.setattr(bootstrap, "build_bootstrap_plan", lambda **_: plan)
    monkeypatch.setattr(bootstrap, "build_development_diagnostics", lambda *_, **__: None)
    monkeypatch.setattr(bootstrap, "open_health_port", _open_health_port)
    monkeypatch.setattr(bootstrap, "RuntimeResources", _Resources)
    monkeypatch.setattr(bootstrap, "_build_audit_store", lambda: store)
    monkeypatch.setattr(bootstrap, "_load_runtime_values", _load_values)
    monkeypatch.setattr(bootstrap, "_attach_runtime_knowledge_source", lambda bound: bound)
    monkeypatch.setattr(bootstrap, "build_runtime_license_authority", lambda **_: object())
    monkeypatch.setattr(bootstrap, "build_core_runtime", _build_core_runtime)
    if drain_outcome == "timeout":
        monkeypatch.setattr(bootstrap, "_CONTEXT_SHADOW_SHUTDOWN_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(
        RuntimeError,
        match="drain failed" if drain_outcome == "fail" else "stop after production composition",
    ):
        await bootstrap._run()

    assert observed == ["bound", "drain", "close"]


async def test_semantic_turn_binding_persists_one_bootstrapped_shadow_comparison(
    container: Container,
) -> None:
    state_store = InMemoryStateStore()
    bound = bind_context_selection_shadow(
        _enable_shadow_candidate(container),
        state_store=state_store,
        config=ContextShadowConfig(max_candidates=1),
    )
    runner = bound.context_selection_shadow_runner
    assert runner is not None
    runtime = _Runtime()

    projection = await _process_turn(
        state_store=state_store,
        container=bound,
        runtime=runtime,
        idempotency_key="semantic-turn-shadow",
    )
    await runner.drain()

    comparisons = await runner.store.list(limit=10)
    durable = await state_store.read_states("context-selection:evaluation:", limit=10)
    assert len(comparisons) == 1
    assert len(durable) == 1
    assert comparisons[0].candidate_policy_ref == POLICY_REF
    assert comparisons[0].baseline_manifest.verbatim_ids == ("turn-1:prior:0",)
    assert comparisons[0].failure_reason is None
    assert runtime.prior_turns[0].content == "What changed recently?"
    assert projection["semantic_result"]["answer"] == "Received Show current operations evidence."


@pytest.mark.parametrize("missing", ["authority", "runner"])
async def test_semantic_turn_context_shadow_is_optional_and_behavior_preserving(
    container: Container,
    missing: str,
) -> None:
    state_store = InMemoryStateStore()
    bound = bind_context_selection_shadow(
        _enable_shadow_candidate(container),
        state_store=state_store,
        config=ContextShadowConfig(max_candidates=1),
    )
    runtime = _Runtime()
    optional_container = (
        SimpleNamespace(
            context_selection_policy_authority=None,
            context_selection_shadow_runner=bound.context_selection_shadow_runner,
        )
        if missing == "authority"
        else SimpleNamespace(
            context_selection_policy_authority=bound.context_selection_policy_authority,
            context_selection_shadow_runner=None,
        )
    )

    projection = await _process_turn(
        state_store=state_store,
        container=optional_container,
        runtime=runtime,
        idempotency_key=f"semantic-turn-no-{missing}",
    )

    durable = await state_store.read_states("context-selection:evaluation:", limit=10)
    assert durable == ()
    assert runtime.prior_turns[0].content == "What changed recently?"
    assert projection["semantic_result"]["answer"] == "Received Show current operations evidence."

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import fdai.runtime.bootstrap as runtime_bootstrap
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai.composition import default_container
from fdai.composition._helpers import LlmBindingsUnavailableError
from fdai.composition.resolved_models import _load_resolved_models
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.rule_catalog.schema.model_lifecycle_review import (
    ModelLifecycleProposalReview,
    ModelLifecycleReviewStatus,
    evaluate_model_lifecycle_review,
)
from fdai.runtime.bootstrap import _attach_model_lifecycle_startup_revision
from fdai.runtime.model_lifecycle_startup import resolve_models_startup_revision
from fdai.shared.config import AppConfig
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 23, tzinfo=UTC)
_PROPOSAL_DIGEST = "a" * 64
_SOURCE_DIGEST = "b" * 64


def _proposal(**changes: object) -> ModelLifecycleProposalReview:
    values: dict[str, object] = {
        "proposal_digest": _PROPOSAL_DIGEST,
        "source_models_digest": _SOURCE_DIGEST,
        "affected_capabilities": ("t1.embedding", "t2.reasoner.primary"),
        "opened_at": _NOW,
        "expires_at": _NOW + timedelta(days=7),
        "merged_at": None,
    }
    values.update(changes)
    return ModelLifecycleProposalReview(**values)  # type: ignore[arg-type]


def test_active_proposal_does_not_hold_current_mapping() -> None:
    decision = evaluate_model_lifecycle_review(
        _proposal(),
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=_NOW + timedelta(days=6),
    )

    assert decision.status is ModelLifecycleReviewStatus.ACTIVE
    assert decision.held_capabilities == ()
    assert decision.mapping_authority is False
    assert decision.execution_authority is False


def test_expiry_boundary_holds_only_declared_capabilities() -> None:
    proposal = _proposal(affected_capabilities=("t2.reasoner.primary",))

    decision = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=proposal.expires_at,
    )

    assert decision.status is ModelLifecycleReviewStatus.HOLD
    assert decision.reason_code == "proposal_expired_unmerged"
    assert decision.held_capabilities == ("t2.reasoner.primary",)


def test_merged_proposal_does_not_hold() -> None:
    proposal = _proposal(merged_at=_NOW + timedelta(days=2))

    decision = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=_NOW + timedelta(days=8),
    )

    assert decision.status is ModelLifecycleReviewStatus.MERGED
    assert decision.held_capabilities == ()


def test_superseded_source_does_not_hold_new_mapping() -> None:
    decision = evaluate_model_lifecycle_review(
        _proposal(),
        current_models_digest="c" * 64,
        evaluated_at=_NOW + timedelta(days=8),
    )

    assert decision.status is ModelLifecycleReviewStatus.STALE_SOURCE
    assert decision.reason_code == "proposal_source_superseded"
    assert decision.held_capabilities == ()


@pytest.mark.parametrize(
    ("proposal", "evaluated_at", "status", "reason_code"),
    [
        (
            _proposal(),
            _NOW + timedelta(days=1),
            ModelLifecycleReviewStatus.ACTIVE,
            "proposal_review_active",
        ),
        (
            _proposal(),
            _NOW + timedelta(days=7),
            ModelLifecycleReviewStatus.HOLD,
            "proposal_expired_unmerged",
        ),
        (
            _proposal(merged_at=_NOW + timedelta(days=1)),
            _NOW + timedelta(days=2),
            ModelLifecycleReviewStatus.MERGED,
            "proposal_merged",
        ),
    ],
)
def test_every_current_source_decision_has_no_authority(
    proposal: ModelLifecycleProposalReview,
    evaluated_at: datetime,
    status: ModelLifecycleReviewStatus,
    reason_code: str,
) -> None:
    decision = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=evaluated_at,
    )

    assert decision.status is status
    assert decision.reason_code == reason_code
    assert decision.mapping_authority is False
    assert decision.execution_authority is False


def test_decision_digest_is_replay_stable() -> None:
    proposal = _proposal()
    first = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=proposal.expires_at,
    )
    second = evaluate_model_lifecycle_review(
        proposal,
        current_models_digest=_SOURCE_DIGEST,
        evaluated_at=proposal.expires_at,
    )

    assert first == second
    assert len(first.decision_digest) == 64


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"proposal_digest": "invalid"}, "proposal_digest"),
        ({"source_models_digest": "invalid"}, "source_models_digest"),
        ({"affected_capabilities": ()}, "at least one"),
        (
            {"affected_capabilities": ("t2.reasoner.primary", "t1.embedding")},
            "unique and sorted",
        ),
        ({"affected_capabilities": ("invalid",)}, "bounded T1/T2"),
        ({"expires_at": _NOW}, "after opened_at"),
        ({"opened_at": datetime(2026, 8, 23)}, "timezone-aware"),
        ({"merged_at": _NOW - timedelta(seconds=1)}, "MUST NOT precede"),
        ({"merged_at": _NOW + timedelta(days=8)}, "MUST NOT be after expires_at"),
    ],
)
def test_proposal_rejects_invalid_boundary(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _proposal(**changes)


def test_evaluation_rejects_future_merge_observation() -> None:
    proposal = _proposal(merged_at=_NOW + timedelta(days=2))

    with pytest.raises(ValueError, match="after evaluated_at"):
        evaluate_model_lifecycle_review(
            proposal,
            current_models_digest=_SOURCE_DIGEST,
            evaluated_at=_NOW + timedelta(days=1),
        )


@dataclass(frozen=True)
class _Artifact:
    content: str
    digest: str
    secret_version: str | None = "version1"


class _Source:
    def __init__(self, artifact: _Artifact) -> None:
        self.artifact = artifact
        self.loads = 0

    async def load(self) -> _Artifact:
        self.loads += 1
        return self.artifact


def _resolved_content() -> str:
    return ResolvedModels(
        schema_version="1.0.0",
        region="example-region",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000000",
        mixed_model_mode="hil-only",
        capabilities=(
            ResolvedCapability(
                name="t1.judge",
                status=CapabilityStatus.RESOLVED,
                publisher="OpenAI",
                family="example-family",
                sku="Standard",
                capacity_tpm=1,
                invocation="always",
            ),
        ),
    ).to_json()


def _observation(content: str, *, trusted: bool = True) -> dict[str, object]:
    source_digest = hashlib.sha256(
        json.dumps(json.loads(content), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    proposal: dict[str, object] = {
        "schema_version": "fdai.model-lifecycle-proposal.v3",
        "status": "proposal",
        "activation_authority": False,
        "source_models_digest": source_digest,
        "affected_capabilities": ["t1.judge"],
        "changes": [],
        "deprecations": [],
        "compatibility_impact": [],
        "proposal_digest": None,
    }
    proposal["proposal_digest"] = hashlib.sha256(
        json.dumps(proposal, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "trusted": trusted,
        "pull_request": 257,
        "head_sha": "1" * 40,
        "opened_at": _NOW.isoformat(),
        "expires_at": (_NOW + timedelta(days=1)).isoformat(),
        "merged_at": None,
        "proposal": proposal,
    }


@pytest.mark.asyncio
async def test_startup_owner_loads_once_persists_verified_hold_before_binding() -> None:
    content = _resolved_content()
    artifact = _Artifact(content, hashlib.sha256(content.encode()).hexdigest())
    source = _Source(artifact)
    store = InMemoryStateStore()

    revision = await resolve_models_startup_revision(
        source,
        expected_artifact_digest=artifact.digest,
        observations=(_observation(content),),
        decision_store=store,
        evaluated_at=_NOW + timedelta(days=1),
    )

    assert source.loads == 1
    assert revision.held_capabilities == ("t1.judge",)
    assert revision.bindable_capability("t1.judge") is None
    assert revision.mapping_authority is False
    assert revision.execution_authority is False
    stored = await store.find_state("model-lifecycle-review:", field="status", value="hold")
    assert stored is not None
    assert stored["decision_digest"] == revision.decisions[0].decision_digest


@pytest.mark.asyncio
async def test_startup_owner_rejects_untrusted_or_mismatched_revision() -> None:
    content = _resolved_content()
    artifact = _Artifact(content, hashlib.sha256(content.encode()).hexdigest())
    store = InMemoryStateStore()

    with pytest.raises(ValueError, match="deployment binding"):
        await resolve_models_startup_revision(
            _Source(artifact),
            expected_artifact_digest="0" * 64,
            observations=(),
            decision_store=store,
            evaluated_at=_NOW,
        )
    with pytest.raises(ValueError, match="MUST be trusted"):
        await resolve_models_startup_revision(
            _Source(artifact),
            expected_artifact_digest=artifact.digest,
            observations=(_observation(content, trusted=False),),
            decision_store=store,
            evaluated_at=_NOW,
        )


def test_core_rejects_source_revision_mismatch_before_model_binding() -> None:
    content = _resolved_content()

    assert _load_resolved_models(
        content,
        expected_digest=hashlib.sha256(content.encode()).hexdigest(),
    ).capabilities
    with pytest.raises(LlmBindingsUnavailableError, match="source revision"):
        _load_resolved_models(content, expected_digest="0" * 64)


def _startup_container(content: str, digest: str):  # type: ignore[no-untyped-def]
    return default_container(
        AppConfig.model_validate(
            {
                "schema_version": "1.0.0",
                "azure": {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "subscription_id": "00000000-0000-0000-0000-000000000000",
                    "region": "example-region",
                },
                "kafka": {
                    "bootstrap_servers": "events.example.com:9093",
                    "topic_events": "fdai.events",
                },
                "postgres": {"host": "postgres.example.com", "database": "fdai"},
                "runtime": {"env": "dev"},
                "llm": {
                    "mode": "azure",
                    "resolved_models_path": content,
                    "resolved_models_sha256": digest,
                },
            }
        )
    )


@pytest.mark.asyncio
async def test_core_production_startup_attaches_owner_revision_before_binding() -> None:
    content = _resolved_content()
    digest = hashlib.sha256(content.strip().encode()).hexdigest()
    container = _startup_container(content, digest)
    async with httpx.AsyncClient() as client:
        attached = await _attach_model_lifecycle_startup_revision(
            container,
            http_client=client,
            environment={},
            state_store=InMemoryStateStore(),
            evaluated_at=_NOW,
        )

    assert attached.resolved_models is not None
    assert attached.resolved_models_artifact_digest == digest


@pytest.mark.asyncio
async def test_core_production_startup_accepts_refreshable_github_app() -> None:
    content = _resolved_content()
    digest = hashlib.sha256(content.strip().encode()).hexdigest()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "github.example.com"
        if request.url.path == "/app/installations/123/access_tokens":
            return httpx.Response(
                201,
                json={
                    "token": "installation-token",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
        if request.url.path == "/repos/example/fdai/pulls":
            return httpx.Response(200, json=[])
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attached = await _attach_model_lifecycle_startup_revision(
            _startup_container(content, digest),
            http_client=client,
            environment={
                "RUNTIME_ENV": "prod",
                "FDAI_GITOPS_OWNER": "example",
                "FDAI_GITOPS_REPO": "fdai",
                "FDAI_GITHUB_APP_CLIENT_ID": "Iv1.example",
                "FDAI_GITHUB_APP_INSTALLATION_ID": "123",
                "FDAI_GITHUB_APP_PRIVATE_KEY": private_key,
                "FDAI_GITOPS_API_BASE": "https://github.example.com",
            },
            state_store=InMemoryStateStore(),
            evaluated_at=_NOW,
        )

    assert attached.resolved_models_artifact_digest == digest


@pytest.mark.asyncio
async def test_core_process_invokes_revision_owner_before_model_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _resolved_content().strip()
    container = _startup_container(content, hashlib.sha256(content.encode()).hexdigest())
    plan = runtime_bootstrap.build_bootstrap_plan(
        llm_mode=container.config.llm.mode,
        environment={},
    )
    order: list[str] = []

    class _ReachedModelBindingError(Exception):
        pass

    class _HealthServer:
        async def close(self) -> None:
            return None

    class _RuntimeSettings:
        async def effective_values(self) -> dict[str, object]:
            return {}

    async def open_health_port() -> _HealthServer:
        return _HealthServer()

    async def attach_owner(current, **_kwargs):  # type: ignore[no-untyped-def]
        order.append("revision-owner")
        return current

    async def finalize_bindings(current, **_kwargs):  # type: ignore[no-untyped-def]
        assert current is container
        order.append("model-binding")
        raise _ReachedModelBindingError

    monkeypatch.setattr(runtime_bootstrap, "default_container_from_env", lambda: container)
    monkeypatch.setattr(runtime_bootstrap, "build_bootstrap_plan", lambda **_kwargs: plan)
    monkeypatch.setattr(runtime_bootstrap, "open_health_port", open_health_port)
    monkeypatch.setattr(
        runtime_bootstrap,
        "runtime_settings_service_from_env",
        lambda _environment: _RuntimeSettings(),
    )
    monkeypatch.setattr(runtime_bootstrap, "_new_http_client", httpx.AsyncClient)
    monkeypatch.setattr(
        runtime_bootstrap,
        "_build_runtime_workload_identity",
        lambda _client: object(),
    )
    monkeypatch.setattr(runtime_bootstrap, "_build_audit_store", InMemoryStateStore)
    monkeypatch.setattr(
        runtime_bootstrap,
        "_attach_model_lifecycle_startup_revision",
        attach_owner,
    )
    monkeypatch.setattr(runtime_bootstrap, "_finalize_llm_bindings", finalize_bindings)

    with pytest.raises(_ReachedModelBindingError):
        await runtime_bootstrap._run()

    assert order == ["revision-owner", "model-binding"]


@pytest.mark.asyncio
async def test_core_production_startup_rejects_mismatch_before_binding() -> None:
    content = _resolved_content()
    container = _startup_container(content, "0" * 64)
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="deployment binding"):
            await _attach_model_lifecycle_startup_revision(
                container,
                http_client=client,
                environment={},
                state_store=InMemoryStateStore(),
                evaluated_at=_NOW,
            )

    assert container.resolved_models is None


@pytest.mark.asyncio
async def test_core_production_requires_trusted_observation_source() -> None:
    content = _resolved_content().strip()
    container = _startup_container(content, hashlib.sha256(content.encode()).hexdigest())
    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="lifecycle observations"):
            await _attach_model_lifecycle_startup_revision(
                container,
                http_client=client,
                environment={"RUNTIME_ENV": "prod"},
                state_store=InMemoryStateStore(),
                evaluated_at=_NOW,
            )


@pytest.mark.asyncio
async def test_core_production_consumes_trusted_pr_and_persists_hold() -> None:
    content = _resolved_content().strip()
    digest = hashlib.sha256(content.encode()).hexdigest()
    proposal = _observation(content)["proposal"]
    assert isinstance(proposal, dict)
    proposal_digest = str(proposal["proposal_digest"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls"):
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 257,
                        "draft": True,
                        "created_at": _NOW.isoformat(),
                        "user": {"login": "github-actions[bot]"},
                        "head": {
                            "ref": f"automation/model-lifecycle-{proposal_digest[:12]}",
                            "sha": "1" * 40,
                        },
                        "base": {"ref": "main"},
                    }
                ],
            )
        if request.url.path.endswith("/pulls/257/files"):
            return httpx.Response(
                200,
                json=[{"filename": (f"config/model-lifecycle-proposals/{proposal_digest}.json")}],
            )
        return httpx.Response(
            200,
            json={
                "encoding": "base64",
                "content": base64.b64encode(json.dumps(proposal).encode()).decode(),
            },
        )

    store = InMemoryStateStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attached = await _attach_model_lifecycle_startup_revision(
            _startup_container(content, digest),
            http_client=client,
            environment={
                "FDAI_GITOPS_TOKEN": "test-token",
                "FDAI_GITOPS_OWNER": "example",
                "FDAI_GITOPS_REPO": "fdai",
                "RUNTIME_ENV": "prod",
            },
            state_store=store,
            evaluated_at=_NOW + timedelta(days=7),
        )

    assert attached.held_model_capabilities == frozenset({"t1.judge"})
    stored = await store.find_state(
        "model-lifecycle-review:",
        field="status",
        value="hold",
    )
    assert stored is not None
    assert stored["proposal_digest"] == proposal_digest

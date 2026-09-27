"""One-shot frozen catalog review trigger tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fdai.agents import CatalogReviewBindings
from fdai.core.operational_learning import CatalogReviewPublicationReceipt
from fdai.runtime.operational_catalog_review_pantheon import (
    CatalogReviewPantheonDependencies,
)
from fdai.runtime.operational_catalog_review_trigger import (
    CatalogReviewTriggerConfig,
    run_operational_catalog_review_trigger,
)
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_REVISION = "a" * 40
_PACKAGE_DIGEST = "b" * 64
_CANDIDATE_DIGEST = "c" * 64
_TOKEN_SENTINEL = "private-token-must-not-escape"
_REQUIRED_LABELS = (
    "action:remediate.tag-add",
    "catalog-review",
    "draft",
    "governance",
    "rule:learned.operational.example",
    "shadow",
)


class _Compiler:
    def compile(self, _candidate: object) -> object:
        return SimpleNamespace(
            content_digest=_PACKAGE_DIGEST,
            candidate=SimpleNamespace(digest=_CANDIDATE_DIGEST),
        )


class _Publisher:
    def __init__(self) -> None:
        self.calls = 0

    async def publish(self, package: Any) -> CatalogReviewPublicationReceipt:
        assert package.content_digest == _PACKAGE_DIGEST
        self.calls += 1
        return CatalogReviewPublicationReceipt(
            package_digest=_PACKAGE_DIGEST,
            review_ref="example/catalog#42",
            already_existed=self.calls > 1,
            candidate_digest=_CANDIDATE_DIGEST,
            binding_digest="d" * 64,
            observation_digest="e" * 64,
            required_labels=_REQUIRED_LABELS,
            observed_labels=_REQUIRED_LABELS,
            head_sha="f" * 40,
            review_document_digest="1" * 64,
        )


class _Catalog:
    action_types: tuple[object, ...] = ()
    rules: tuple[object, ...] = ()


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "scenario_id": "governed-operational-learning-v2026.08",
        "fdai_revision": _REVISION,
        "scenario_set_version": "v2026.08",
        "reviewed_at": "2026-08-31T08:00:00Z",
        "action_type": "remediate.tag-add",
        "resource_type": "kubernetes.service",
        "failure_mechanism": "selector_target_mismatch",
        "expected": {
            "immutable_cases": 2,
            "rule_candidates": 1,
            "catalog_reviews": 1,
            "mode_before_review": "shadow",
            "mode_after_review": "enforce",
            "mode_after_demotion": "shadow",
        },
    }


def _environment() -> dict[str, str]:
    return {
        "FDAI_EXECUTION_VENUE": "deployed",
        "FDAI_CATALOG_REVIEW_PROTECTED_BINDING": "1",
        "FDAI_CATALOG_REVIEW_SOURCE_REVISION": _REVISION,
        "FDAI_CATALOG_REVIEW_FROZEN_MANIFEST": "frozen/review.json",
        "FDAI_CATALOG_REVIEW_TIMEOUT_SECONDS": "30",
        "UNUSED_SECRET_SENTINEL": _TOKEN_SENTINEL,
    }


def _dependencies(
    *,
    durable: bool = True,
    durable_state_store: bool = True,
) -> CatalogReviewPantheonDependencies:
    return CatalogReviewPantheonDependencies(
        bus=LocalEventBus(),
        state_store=InMemoryStateStore(),
        durable_transport=durable,
        durable_state_store=durable_state_store,
        consumer_join_seconds=0,
    )


async def test_trigger_is_draft_shadow_only_and_sanitized(tmp_path) -> None:
    manifest = tmp_path / "frozen/review.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    publisher = _Publisher()
    bindings = CatalogReviewBindings(
        compiler=_Compiler(),  # type: ignore[arg-type]
        publisher=publisher,
    )
    dependencies = _dependencies()

    async with httpx.AsyncClient() as client:
        receipt = await run_operational_catalog_review_trigger(
            environment=_environment(),
            http_client=client,
            asset_root=tmp_path,
            bindings=bindings,
            catalog=_Catalog(),  # type: ignore[arg-type]
            dependencies=dependencies,
        )

    assert receipt["state"] == "draft-review-published"
    assert receipt["required_labels"] == list(_REQUIRED_LABELS)
    assert receipt["observed_labels"] == list(_REQUIRED_LABELS)
    assert receipt["publication_head_sha"] == "f" * 40
    assert receipt["review_document_digest"] == "1" * 64
    assert receipt["draft"] is True
    assert receipt["mode"] == "shadow"
    assert receipt["catalog_activation_performed"] is False
    assert receipt["code_path_merge_authority"] is False
    assert receipt["independent_pr_observation_verified"] is True
    assert receipt["independent_observation_scope"] == "gitops-pr"
    assert receipt["durable_intent_verified"] is True
    assert receipt["durable_terminal_verified"] is True
    assert receipt["managed_resource_mutation_status"] == "unknown"
    assert receipt["managed_resource_mutation_performed"] is None
    assert receipt["grants_authority"] is False
    assert _TOKEN_SENTINEL not in json.dumps(receipt)
    assert (
        len(
            await dependencies.state_store.read_states(
                "catalog-review-publication:",
                limit=10,
            )
        )
        == 2
    )


async def test_trigger_rejects_in_memory_transport(tmp_path) -> None:
    manifest = tmp_path / "frozen/review.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    publisher = _Publisher()
    bindings = CatalogReviewBindings(
        compiler=_Compiler(),  # type: ignore[arg-type]
        publisher=publisher,
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="in-memory event bus"):
            await run_operational_catalog_review_trigger(
                environment=_environment(),
                http_client=client,
                asset_root=tmp_path,
                bindings=bindings,
                catalog=_Catalog(),  # type: ignore[arg-type]
                dependencies=_dependencies(durable=False),
            )


async def test_trigger_rejects_missing_durable_audit(tmp_path) -> None:
    manifest = tmp_path / "frozen/review.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    bindings = CatalogReviewBindings(
        compiler=_Compiler(),  # type: ignore[arg-type]
        publisher=_Publisher(),
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="durable StateStore and Saga"):
            await run_operational_catalog_review_trigger(
                environment=_environment(),
                http_client=client,
                asset_root=tmp_path,
                bindings=bindings,
                catalog=_Catalog(),  # type: ignore[arg-type]
                dependencies=_dependencies(durable_state_store=False),
            )


def test_trigger_rejects_missing_private_binding(tmp_path) -> None:
    environment = _environment()
    environment.pop("FDAI_CATALOG_REVIEW_PROTECTED_BINDING")

    with pytest.raises(RuntimeError, match="private GitOps binding"):
        CatalogReviewTriggerConfig.from_environment(environment, asset_root=tmp_path)

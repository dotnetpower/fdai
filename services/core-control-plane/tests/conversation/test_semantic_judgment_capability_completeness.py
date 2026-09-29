"""The judgment is offered every declaration identity, never a ranked slice of the catalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any

from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_judgment import (
    _MAX_JUDGMENT_CAPABILITY_BYTES,
    _semantic_judgment_capabilities,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import OntologyQueryPlanVerifier
from fdai_service_contracts.ontology_query import QueryNodeKind

from tests.conversation.semantic_reasoning_support import production_manifest
from tests.conversation.test_semantic_planning import NOW, _ManifestProvider, _Model

_KINDS = {"action", "function", "interface", "link", "object"}


def _encoded(capabilities: Sequence[Mapping[str, Any]]) -> int:
    import json

    return len(
        json.dumps(
            list(capabilities), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    )


def test_every_declaration_identity_is_presented_within_the_bound() -> None:
    manifest = production_manifest()
    declared = {
        (item["kind"], item["name"]) for item in manifest.descriptors if item.get("kind") in _KINDS
    }

    capabilities = _semantic_judgment_capabilities(manifest.descriptors, utterance="인시던트 목록")

    kind_names = {
        "action_type": "action",
        "function_type": "function",
        "interface_type": "interface",
        "link_type": "link",
        "object_type": "object",
    }
    presented = {(kind_names[item["kind"]], item["name"]) for item in capabilities}
    assert presented == declared
    assert _encoded(capabilities) <= _MAX_JUDGMENT_CAPABILITY_BYTES
    resource = next(item for item in capabilities if item["name"] == "Resource")
    assert {"Resource.id", "Resource.name"} <= set(resource["canonical_values"])


class _RecordingJudgment:
    def __init__(self) -> None:
        self.capabilities: tuple[dict[str, Any], ...] = ()

    def preflight(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(observations=(), attempted=False, failure_kind=None, proposal=None)

    def judge(self, **kwargs: Any) -> Any:
        self.capabilities = kwargs["capabilities"]
        raise RuntimeError("stop after recording the offered capabilities")


class _RankedSlice:
    """A selector that returns only its top-ranked slice of the manifest."""

    def select(self, *, utterance: str, manifest: Any, limit: int) -> Sequence[Mapping[str, Any]]:
        return tuple(item for item in manifest.descriptors if item.get("name") == "Resource")


def test_a_ranked_descriptor_slice_never_limits_the_judgment_catalog() -> None:
    manifest = production_manifest()
    judgment = _RecordingJudgment()
    service = SemanticPlanningService(
        model=_Model(frame=None, plan=None),
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        descriptor_selector=_RankedSlice(),
        now=lambda: NOW,
        semantic_judgment=judgment,
    )

    service.plan(
        utterance="Resource ObjectType은 무엇을 선언해?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose=next(iter(manifest.purposes)),
    )

    names = {item.get("name") for item in judgment.capabilities}
    assert {"query.ontology_declaration", "query.manifest", "Incident", "Resource"} <= names

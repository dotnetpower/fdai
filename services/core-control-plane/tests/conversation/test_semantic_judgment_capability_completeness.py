"""The judgment is offered every declaration identity, never a ranked slice of the catalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.conversation.semantic_judgment_bounds import bounded_capabilities
from fdai.core.conversation.semantic_judgment_capabilities import property_canonical_values
from fdai.core.conversation.semantic_judgment_grounding import validate_capability_grounding
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_judgment import (
    _MAX_JUDGMENT_CAPABILITY_BYTES,
    _semantic_judgment_capabilities,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import OntologyQueryPlanVerifier
from fdai_service_contracts.ontology_query import QueryNodeKind
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from tests.conversation.semantic_reasoning_support import production_manifest
from tests.conversation.test_semantic_judgment import _proposal
from tests.conversation.test_semantic_planning import NOW, _fixture, _ManifestProvider, _Model

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
    by_name = {item["name"]: item for item in manifest.descriptors if item["kind"] == "object"}
    for capability in capabilities:
        if capability["kind"] == "object_type":
            assert set(capability.get("property_names", ())) == set(
                by_name[capability["name"]].get("properties", {})
            )
            assert set(property_canonical_values(capability)) == {
                f"{capability['name']}.{name}"
                for name in by_name[capability["name"]].get("properties", {})
            }


def test_property_projection_above_old_detail_allowance_keeps_every_axis() -> None:
    names = [f"property_{index:02d}_" + "x" * 36 for index in range(20)]
    descriptors = tuple(
        {"kind": "object", "name": f"Example{index}", "properties": dict.fromkeys(names, {})}
        for index in range(24)
    )
    capabilities = _semantic_judgment_capabilities(descriptors)
    assert all(item.get("property_names") == names for item in capabilities)
    assert 20 * 1024 < _encoded(capabilities) <= _MAX_JUDGMENT_CAPABILITY_BYTES


def test_complete_property_projection_still_omits_acl_hidden_properties() -> None:
    manifest, _definition = _fixture()
    capabilities = _semantic_judgment_capabilities(manifest.descriptors)
    resource = next(item for item in capabilities if item["name"] == "Resource")
    assert resource["property_names"] == ["id"]
    assert property_canonical_values(resource) == ("Resource.id",)


def test_oversized_property_projection_holds_instead_of_omitting_an_axis() -> None:
    descriptor = {
        "kind": "object",
        "name": "Example",
        "properties": {f"property_{index}_" + "x" * 80: {} for index in range(512)},
    }
    with pytest.raises(ValueError, match="capability projection exceeds"):
        _semantic_judgment_capabilities((descriptor,))


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("identity", ["Resource.status", "Incident.status", "Resource.private"])
def test_factored_properties_preserve_exact_grounding_and_legacy_domains(
    legacy: bool,
    identity: str,
) -> None:
    capability = (
        {"kind": "object_type", "name": "Resource", "canonical_values": ["Resource.status"]}
        if legacy
        else {"kind": "object_type", "name": "Resource", "property_names": ["status"]}
    )
    capabilities = (capability, {"kind": "function_type", "name": "query.inspect"})
    proposal = SemanticJudgmentProposal.model_validate(
        _proposal(
            primary_intent="query.inspect",
            targets=[
                {
                    "kind": "property",
                    "value": "status",
                    "canonical_value": identity,
                    "source_start": 0,
                    "source_end": 6,
                }
            ],
        )
    )
    if identity == "Resource.status":
        validate_capability_grounding(proposal, capabilities=capabilities)
    else:
        with pytest.raises(ValueError, match="canonical identity is not supplied"):
            validate_capability_grounding(proposal, capabilities=capabilities)


@pytest.mark.parametrize(
    "update",
    [
        {"kind": "function_type"},
        {"name": ""},
        {"property_names": "status"},
        {"property_names": ["status", "status"]},
        {"property_names": [None]},
        {"property_names": [""]},
        {"property_names": [{}]},
    ],
)
def test_invalid_factored_property_metadata_fails_input_admission(
    update: dict[str, object],
) -> None:
    capability = {"kind": "object_type", "name": "Resource", "property_names": ["status"], **update}
    with pytest.raises(ValueError, match="property names require"):
        bounded_capabilities((capability,))


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


def test_oversized_catalog_stops_before_judgment_frame_or_plan(
    caplog: pytest.LogCaptureFixture,
) -> None:
    manifest = production_manifest()
    manifest = replace(
        manifest,
        descriptors=(
            *manifest.descriptors,
            *(
                {"kind": "function", "name": f"query.extra.{index}" + "x" * 90}
                for index in range(512)
            ),
        ),
    )
    judgment = _RecordingJudgment()
    model = _Model(frame={}, plan=None)
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        descriptor_selector=_RankedSlice(),
        now=lambda: NOW,
        semantic_judgment=judgment,
    )
    outcome = service.plan(
        utterance="Inspect the declarations.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose=next(iter(manifest.purposes)),
    )
    assert outcome.reason == "semantic_plan_invalid"
    assert judgment.capabilities == ()
    assert model.frame_calls == model.plan_calls == 0
    assert "semantic_judgment_capability_identities_exceed_bound" in caplog.text

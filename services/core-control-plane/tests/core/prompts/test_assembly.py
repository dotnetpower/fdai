"""Per-call conditional-pack assembly tests for exact prompt profiles."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
import yaml
from fdai.core.prompts import (
    DefaultPromptComposer,
    FileSystemPromptRegistry,
    PromptAblationProfile,
    PromptArtifactRef,
    PromptAssembler,
    PromptAssemblyMode,
    PromptBudgetExceededError,
    PromptLayer,
    PromptProfile,
    PromptProfileMode,
    PromptRegistryError,
    PromptSelection,
    compose_static_selection,
)
from fdai.core.prompts.types import PromptArtifact, PromptMode

_ROOT = Path(__file__).resolve().parents[5]
_CATALOG = _ROOT / "rule-catalog"


def _artifact(artifact_id: str, body: str, layer: PromptLayer = PromptLayer.PACK) -> PromptArtifact:
    return PromptArtifact(
        id=artifact_id,
        version=1,
        layer=layer,
        body=body,
        applies_to=("test.capability",),
        token_budget=None,
        default_mode=PromptMode.SHADOW,
        provenance_source="test",
    )


def _selection(*, budget: int = 4096) -> PromptSelection:
    refs = (
        PromptArtifactRef("core", 1, PromptLayer.PACK),
        PromptArtifactRef(
            "inventory",
            1,
            PromptLayer.PACK,
            when_any=("topic:resource_inventory",),
            covers=("intent:query.contextual_resources",),
        ),
        PromptArtifactRef(
            "ontology",
            1,
            PromptLayer.PACK,
            when_any=("topic:ontology_schema",),
            covers=("intent:query.manifest",),
        ),
    )
    profile = PromptProfile(
        id="test.dynamic",
        version=1,
        capability_id="test.capability",
        mode=PromptProfileMode.SHADOW,
        root=PromptArtifactRef("root", 1, PromptLayer.BASE),
        packs=refs,
        system_token_budget=budget,
        request_token_budget=budget * 2 + 32,
        reserved_output_tokens=16,
        promotion_evidence=(),
        provenance_source="test",
    )
    return PromptSelection(
        root=_artifact("root", "ROLE", PromptLayer.BASE),
        packs=(
            _artifact("core", "CORE"),
            _artifact("inventory", "INVENTORY"),
            _artifact("ontology", "ONTOLOGY"),
        ),
        profile=profile,
    )


def test_static_profile_assembler_matches_static_composition() -> None:
    selection = FileSystemPromptRegistry(_CATALOG).resolve("semantic.query.plan")
    assembler = PromptAssembler(selection)

    assert not assembler.dynamic
    assert assembler.complete.system_text == compose_static_selection(selection).system_text
    assert assembler.assemble(("shape:ontology_manifest",)) is assembler.complete
    assert assembler.complete.assembly is None


def test_missing_keys_use_the_complete_composition() -> None:
    assembler = PromptAssembler(_selection())

    composed = assembler.assemble(None)

    assert composed.system_text == "ROLE\n\nCORE\n\nINVENTORY\n\nONTOLOGY"
    assert composed.assembly is not None
    assert composed.assembly.mode is PromptAssemblyMode.COMPLETE
    assert composed.assembly.unselected_layers == ()
    assert composed.system_text == compose_static_selection(_selection()).system_text


def test_matching_keys_select_unconditional_and_matching_packs_only() -> None:
    composed = PromptAssembler(_selection()).assemble(("topic:resource_inventory",))

    assert composed.system_text == "ROLE\n\nCORE\n\nINVENTORY"
    assert composed.assembly is not None
    assert composed.assembly.mode is PromptAssemblyMode.SELECTED
    assert composed.assembly.keys == ("topic:resource_inventory",)
    assert [layer.id for layer in composed.assembly.unselected_layers] == ["ontology"]
    assert composed.assembly.covered_keys == ("intent:query.contextual_resources",)
    assert [layer.id for layer in composed.layer_manifest] == ["root", "core", "inventory"]
    manifest = composed.replay_manifest()
    assert manifest.assembly == composed.assembly
    projection = manifest.trace_projection()
    assert projection["assembly"] == {
        "mode": "selected",
        "keys": ["topic:resource_inventory"],
        "unselected_layers": ["ontology"],
        "digest": composed.assembly.digest,
    }


def test_unmatched_keys_fall_back_to_complete_and_retain_the_keys() -> None:
    composed = PromptAssembler(_selection()).assemble(("topic:general_knowledge",))

    assert composed.system_text.endswith("ONTOLOGY")
    assert composed.assembly is not None
    assert composed.assembly.mode is PromptAssemblyMode.COMPLETE
    assert composed.assembly.keys == ("topic:general_knowledge",)


def test_uncovered_reports_governed_result_keys_without_selected_guidance() -> None:
    assembler = PromptAssembler(_selection())
    selected = assembler.assemble(("topic:resource_inventory",))
    assert selected.assembly is not None

    assert selected.assembly.uncovered(
        ("intent:query.manifest", "intent:query.contextual_resources", "intent:explanation")
    ) == ("intent:query.manifest",)
    complete = assembler.assemble(None).assembly
    assert complete is not None
    assert complete.uncovered(("intent:query.manifest",)) == ()


def test_assembly_digest_binds_keys_and_selection() -> None:
    assembler = PromptAssembler(_selection())

    first = assembler.assemble(("topic:resource_inventory",)).assembly
    repeated = assembler.assemble(("topic:resource_inventory",)).assembly
    other = assembler.assemble(("topic:ontology_schema",)).assembly

    assert first is not None and repeated is not None and other is not None
    assert first.digest == repeated.digest
    assert first.digest != other.digest


def test_complete_composition_must_fit_the_profile_budget() -> None:
    with pytest.raises(PromptBudgetExceededError):
        PromptAssembler(_selection(budget=5))


@pytest.mark.parametrize("key", ("resource_inventory", "topic:Bad Key", "raw:vm"))
def test_assembly_rejects_non_canonical_keys(key: str) -> None:
    with pytest.raises(ValueError, match="canonical namespaced keys"):
        PromptAssembler(_selection()).assemble((key,))


def test_conditional_refs_are_validated() -> None:
    with pytest.raises(ValueError, match="covers requires when_any"):
        PromptArtifactRef("pack", 1, PromptLayer.PACK, covers=("intent:query.manifest",))
    with pytest.raises(ValueError, match="canonical namespaced keys"):
        PromptArtifactRef("pack", 1, PromptLayer.PACK, when_any=("vm",))
    with pytest.raises(ValueError, match="root MUST NOT be conditional"):
        PromptProfile(
            id="test.profile",
            version=1,
            capability_id="test.capability",
            mode=PromptProfileMode.SHADOW,
            root=PromptArtifactRef(
                "root", 1, PromptLayer.BASE, when_any=("topic:resource_inventory",)
            ),
            packs=(),
            system_token_budget=128,
            request_token_budget=4096,
            reserved_output_tokens=512,
            promotion_evidence=(),
            provenance_source="test",
        )


def test_unconditional_refs_keep_their_historical_profile_digest() -> None:
    plain = PromptArtifactRef("pack", 1, PromptLayer.PACK)
    conditional = PromptArtifactRef(
        "pack", 1, PromptLayer.PACK, when_any=("topic:resource_inventory",)
    )

    assert plain.digest_payload() == {"id": "pack", "layer": "pack", "version": 1}
    assert conditional.digest_payload()["when_any"] == ["topic:resource_inventory"]


def _write_dynamic_profile(catalog: Path, *, schema_version: str) -> None:
    path = catalog / "prompts" / "profiles" / "catalog.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["schema_version"] = schema_version
    data["profiles"].append(
        {
            "id": "shadow.test-dynamic-judgment",
            "version": 1,
            "capability_id": "semantic.judgment",
            "mode": "shadow",
            "root": {"id": "semantic-judgment-common", "version": 1, "layer": "base"},
            "packs": [
                {
                    "id": "semantic-resource-name-filter",
                    "version": 1,
                    "layer": "pack",
                    "when_any": ["topic:resource_inventory"],
                    "covers": ["intent:query.contextual_resources"],
                }
            ],
            "system_token_budget": 16384,
            "request_token_budget": 65536,
            "reserved_output_tokens": 2048,
            "promotion_evidence": [],
            "provenance": {"source": "docs/roadmap/decisioning/prompt-composition.md"},
        }
    )
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_conditional_packs_require_the_dynamic_catalog_schema(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    shutil.copytree(_CATALOG / "prompts", catalog / "prompts")
    _write_dynamic_profile(catalog, schema_version="1.0.0")

    with pytest.raises(PromptRegistryError) as excinfo:
        FileSystemPromptRegistry(catalog)

    assert any("schema_version 1.1.0" in issue.message for issue in excinfo.value.issues)


def test_dynamic_catalog_schema_loads_conditional_packs(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    shutil.copytree(_CATALOG / "prompts", catalog / "prompts")
    _write_dynamic_profile(catalog, schema_version="1.1.0")

    selection = FileSystemPromptRegistry(catalog).resolve(
        "semantic.judgment", profile_id="shadow.test-dynamic-judgment"
    )
    assembler = PromptAssembler(selection)

    assert assembler.dynamic
    assert assembler.profile.governed_keys == ("intent:query.contextual_resources",)
    assert assembler.assemble(("topic:resource_inventory",)).assembly is not None


def test_composer_assembler_honors_reviewed_pack_ablation() -> None:
    composer = DefaultPromptComposer(
        registry=FileSystemPromptRegistry(_CATALOG),
        ablation_profile=PromptAblationProfile.reviewed("packs"),
    )

    assembler = composer.assembler(capability_id="semantic.judgment")
    composed = asyncio.run(composer.compose(capability_id="semantic.judgment"))

    assert assembler.complete.system_text == composed.system_text
    assert [ref.id for ref in assembler.complete.ablated_layers] == [
        ref.id for ref in composed.ablated_layers
    ]

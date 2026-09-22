"""Missing local model settings are built only from actual scoped deployment evidence."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fdai.composition.wire_distiller import (
    OntologyCouncilBindingState,
    ontology_council_binding_state,
)
from fdai.rule_catalog.schema.llm_registry import (
    load_llm_registry_from_mapping,
    load_llm_registry_from_yaml,
)
from fdai.rule_catalog.schema.llm_resolver import ResolvedModels

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "ensure_local_models", ROOT / "scripts/deployment/local/ensure-local-models.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ACCOUNT_ID = (
    "/subscriptions/example-sub/resourceGroups/rg-example/"
    "providers/Microsoft.CognitiveServices/accounts/example"
)


def registry():
    return load_llm_registry_from_mapping(
        {
            "schema_version": "1.0.0",
            "mixed_model_mode": "hil-only",
            "models": {
                "t1.embedding": {
                    "preferences": [{"publisher": "OpenAI", "family": "embedding"}],
                    "sku": "Standard",
                    "capacity_tpm": 1000,
                },
                "t1.judge": {
                    "preferences": [{"publisher": "OpenAI", "family": "small"}],
                    "sku": "GlobalStandard",
                    "capacity_tpm": 1000,
                },
            },
        }
    )


def account():
    return {
        "id": ACCOUNT_ID,
        "name": "example",
        "kind": "AIServices",
        "location": "example-region",
        "properties": {
            "provisioningState": "Succeeded",
            "endpoint": "https://other.example.com/",
            "endpoints": {"OpenAI Language Model Instance API": "https://models.example.com/"},
        },
        "deployments": [
            {
                "id": f"{ACCOUNT_ID}/deployments/{name}",
                "name": name,
                "properties": {
                    "provisioningState": "Succeeded",
                    "model": {"format": "OpenAI", "name": family, "version": "1"},
                },
                "sku": {"name": "GlobalStandard", "capacity": 10},
            }
            for name, family in [("narrator-small", "small"), ("t1.embedding", "embedding")]
        ],
    }


def resolve(accounts):
    return MODULE.resolve_existing(
        registry(),
        accounts,
        subscription_id="example-sub",
        resource_group="rg-example",
        principal_id="example-human",
    )


def test_same_name_embedding_preserves_observed_identity():
    observed = account()
    result = resolve([observed])
    bindings = [item for item in result.endpoint_bindings if item.capability == "t1.embedding"]
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.deployment == "t1.embedding"
    assert binding.family == "embedding"
    assert binding.version == "1"
    assert binding.features.embeddings is True
    assert (
        binding.discovery.resource_ref_digest
        == hashlib.sha256(f"{ACCOUNT_ID}/deployments/t1.embedding".encode()).hexdigest()
    )
    assert ResolvedModels.from_json(result.to_json()) == result


def test_generates_from_observed_endpoints_names_and_capacities():
    original = account()
    before = copy.deepcopy(original)
    result = resolve([original])
    assert original == before
    assert result.narrator.endpoint == "https://models.example.com"
    assert result.narrator.deployment == "narrator-small"
    judge_binding = next(item for item in result.endpoint_bindings if item.capability == "t1.judge")
    assert judge_binding.deployment == "narrator-small"
    assert result.capabilities[0].capacity_tpm == 10000
    assert result.mixed_model_mode == "hil-only"
    assert ResolvedModels.from_json(result.to_json()) == result


@pytest.mark.parametrize(
    "defect",
    [
        "scope",
        "deployment_scope",
        "failed",
        "missing",
        "capacity",
        "duplicate",
        "endpoint",
        "version",
    ],
)
def test_rejects_missing_ambiguous_or_foreign_model_evidence(defect):
    value = account()
    if defect == "scope":
        value["id"] = value["id"].replace("example-sub", "foreign")
    elif defect == "deployment_scope":
        value["deployments"][0]["id"] = "foreign"
    elif defect == "failed":
        value["deployments"][0]["properties"]["provisioningState"] = "Failed"
    elif defect == "missing":
        value["deployments"].pop()
    elif defect == "capacity":
        value["deployments"][0]["sku"]["capacity"] = True
    elif defect == "duplicate":
        value["deployments"].append(value["deployments"][0])
    elif defect == "endpoint":
        value["properties"]["endpoints"]["OpenAI Language Model Instance API"] = (
            "https://models.example.com/path"
        )
    elif defect == "version":
        value["deployments"][0]["properties"]["model"].pop("version")
    with pytest.raises(ValueError):
        resolve([value])


def test_rejects_multiple_eligible_accounts():
    with pytest.raises(ValueError, match="exactly one"):
        resolve([account(), account()])


def test_full_registry_does_not_declare_unconfigured_ontology_council():
    configured = load_llm_registry_from_yaml(ROOT / "rule-catalog/llm-registry.yaml")
    observed = account()
    for deployment, capability in zip(
        observed["deployments"], ("t1.judge", "t1.embedding"), strict=True
    ):
        deployment["properties"]["model"]["name"] = (
            configured.models[capability].preferences[0].family
        )
    resolved = MODULE.resolve_existing(
        configured,
        [observed],
        subscription_id="example-sub",
        resource_group="rg-example",
        principal_id="example-human",
    )
    assert {item.name for item in resolved.capabilities} == {"t1.embedding", "t1.judge"}
    assert ontology_council_binding_state(resolved) is OntologyCouncilBindingState.ABSENT


def test_atomic_private_output_cannot_replace_existing_file(tmp_path):
    target = tmp_path / "resolved-models.json"
    payload = resolve([account()]).to_json()
    MODULE.write_artifact(target, payload)
    MODULE.validate_artifact(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        MODULE.write_artifact(target, "different")
    assert target.read_text() == payload + "\n"
    assert list(tmp_path.iterdir()) == [target]


def test_startup_ensures_models_before_runtime_cache_identity():
    source = (ROOT / "scripts/deployment/local/prepare-console-full-stack.sh").read_text()
    assert source.index("run_bounded local-model-settings") < source.index(
        "runtime_environment_inputs=("
    )
    assert "scripts/deployment/local/ensure-local-models.py" in source


def test_vision_selection_requires_runtime_eligible_routes(tmp_path):
    target = tmp_path / "vision.json"
    resolved = resolve([account()])
    target.write_text(resolved.to_json())
    assert not MODULE.eligible_vision_artifact(target)
    eligible = replace(resolved, vision_candidates=resolved.narrator_candidates)
    target.write_text(eligible.to_json())
    assert MODULE.eligible_vision_artifact(target)
    target.write_text(replace(eligible, capabilities=()).to_json())
    assert not MODULE.eligible_vision_artifact(target)


def test_invalid_vision_does_not_hide_existing_canonical_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("FDAI_LOCAL_RESOLVED_MODELS_PATH", raising=False)
    monkeypatch.setattr(sys, "argv", ["ensure-local-models", "--repo-root", str(tmp_path)])
    vision = tmp_path / ".fdai/resolved-models-vision.json"
    vision.parent.mkdir()
    vision.write_text("invalid")
    target = tmp_path / "resolved-models.json"
    payload = resolve([account()]).to_json()
    target.write_text(payload)

    def unexpected_discovery(*args, **kwargs):
        pytest.fail("existing canonical settings must not trigger discovery")

    monkeypatch.setattr(MODULE.subprocess, "run", unexpected_discovery)
    assert MODULE.main() == 0
    assert target.read_text() == payload
    assert vision.read_text() == "invalid"


def test_missing_explicit_settings_never_trigger_discovery(tmp_path, monkeypatch):
    target = tmp_path / "selected.json"
    monkeypatch.setenv("FDAI_LOCAL_RESOLVED_MODELS_PATH", str(target))
    monkeypatch.setattr(sys, "argv", ["ensure-local-models", "--repo-root", str(tmp_path)])

    def unexpected_discovery(*args, **kwargs):
        pytest.fail("explicit policy must not be replaced")

    monkeypatch.setattr(MODULE.subprocess, "run", unexpected_discovery)
    with pytest.raises(ValueError, match="explicit model artifact is missing"):
        MODULE.main()
    assert not target.exists()


def test_missing_default_settings_require_explicit_scope_before_provider_access(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("FDAI_LOCAL_RESOLVED_MODELS_PATH", raising=False)
    monkeypatch.setattr(sys, "argv", ["ensure-local-models", "--repo-root", str(tmp_path)])

    def observed_command(arguments, **kwargs):
        if arguments[0] == "git":
            return MODULE.subprocess.CompletedProcess(arguments, 0, "", "")
        pytest.fail("missing scope must not trigger provider discovery")

    monkeypatch.setattr(MODULE.subprocess, "run", observed_command)
    with pytest.raises(ValueError, match="explicitly selected resource group"):
        MODULE.main()


@pytest.mark.parametrize("discovery_fails", [False, True])
def test_missing_default_settings_use_only_scoped_reads(tmp_path, monkeypatch, discovery_fails):
    monkeypatch.delenv("FDAI_LOCAL_RESOLVED_MODELS_PATH", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ensure-local-models", "--repo-root", str(tmp_path), "--resource-group", "rg-example"],
    )
    monkeypatch.setattr(MODULE, "load_llm_registry_from_yaml", lambda path: registry())
    calls = []

    def observed_command(arguments, **kwargs):
        calls.append(arguments)
        assert 0 < kwargs["timeout"] <= 20
        result = None
        if arguments[0] == "git":
            assert arguments[3] == "check-ignore"
        elif arguments[1:3] == ["account", "show"]:
            if discovery_fails:
                return MODULE.subprocess.CompletedProcess(arguments, 1, "", "private error")
            result = {"id": "example-sub"}
        elif arguments[1:4] == ["ad", "signed-in-user", "show"]:
            result = "example-human"
        else:
            assert arguments[arguments.index("--subscription") + 1] == "example-sub"
            assert arguments[arguments.index("--resource-group") + 1] == "rg-example"
            if arguments[1:4] == ["cognitiveservices", "account", "list"]:
                result = [account()]
            else:
                assert arguments[1:5] == ["cognitiveservices", "account", "deployment", "list"]
                assert arguments[arguments.index("--name") + 1] == "example"
                result = account()["deployments"]
        return MODULE.subprocess.CompletedProcess(arguments, 0, json.dumps(result), "")

    monkeypatch.setattr(MODULE.subprocess, "run", observed_command)
    target = tmp_path / "resolved-models.json"
    if discovery_fails:
        with pytest.raises(ValueError, match="check login and selected scope"):
            MODULE.main()
        assert not target.exists()
        assert len(calls) == 2
    else:
        assert MODULE.main() == 0
        assert MODULE.validate_artifact(target).narrator.deployment == "narrator-small"
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert len(calls) == 5

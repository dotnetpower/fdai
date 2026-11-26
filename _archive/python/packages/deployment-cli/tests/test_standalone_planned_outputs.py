from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_planned_outputs, standalone_stage_targets

_PLAN = {
    "planned_values": {
        "outputs": {
            "event_bus_semantic_topics": {"value": ["a", "b"], "sensitive": False},
            "event_bus_operating_model_topic": {"value": "fdai.operating-model"},
            "console_default_hostname": {"sensitive": False},
            "document_event_topics": {"value": {"pipeline_stages": "x"}},
            "partly_known": {"value": {"a": "x", "b": None}},
        }
    },
    "output_changes": {
        "event_bus_semantic_topics": {"after_unknown": False},
        "event_bus_operating_model_topic": {"after_unknown": False},
        "console_default_hostname": {"after_unknown": True},
        "document_event_topics": {"after_unknown": {}},
        "partly_known": {"after_unknown": {"b": True}},
    },
}


def test_known_planned_outputs_exclude_unknown_values() -> None:
    known = standalone_planned_outputs.known_planned_outputs(_PLAN)

    assert known == {
        "event_bus_semantic_topics": ["a", "b"],
        "event_bus_operating_model_topic": "fdai.operating-model",
        "document_event_topics": {"pipeline_stages": "x"},
    }


def _fake_terraform(tmp_path: Path, calls: list[tuple[str, ...]]):
    def run(command, **kwargs):
        calls.append(tuple(command))
        if command[:2] == ("terraform", "output"):
            if command[-1] == "key_vault_uri":
                return SimpleNamespace(returncode=0, stdout="https://vault\n", stderr="")
            return SimpleNamespace(
                returncode=1, stdout="", stderr=f'Error: Output "{command[-1]}" not found'
            )
        if command[:2] == ("terraform", "plan"):
            assert "-refresh=false" in command and "-lock=false" in command
            assert not any(part.startswith("-target") for part in command)
            assert kwargs["env"]["TF_DATA_DIR"] == str(tmp_path / "data")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[:2] == ("terraform", "show"):
            return SimpleNamespace(returncode=0, stdout=json.dumps(_PLAN), stderr="")
        raise AssertionError(command)

    return run


def test_missing_state_output_uses_a_known_planned_value_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    infra = tmp_path / "infra"
    infra.mkdir()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(standalone_planned_outputs, "_CACHE", {})
    monkeypatch.setattr(standalone_planned_outputs, "_SOURCES", {})
    monkeypatch.setattr(
        standalone_planned_outputs.subprocess, "run", _fake_terraform(tmp_path, calls)
    )
    standalone_planned_outputs.bind(
        infra, variables=tmp_path / "vars.json", data_dir=tmp_path / "data"
    )

    read = standalone_planned_outputs.read_output
    assert read(infra, "key_vault_uri", raw=True, reason="r") == "https://vault"
    assert read(infra, "event_bus_operating_model_topic", raw=True, reason="r") == (
        "fdai.operating-model"
    )
    assert read(infra, "event_bus_semantic_topics", raw=False, reason="r") == ["a", "b"]
    with pytest.raises(ValueError, match="unknown until its resource is applied"):
        read(infra, "console_default_hostname", raw=True, reason="r")

    assert sum(1 for call in calls if call[:2] == ("terraform", "plan")) == 1
    assert not list(tmp_path.glob("planned-outputs-*"))


def test_unbound_root_or_other_errors_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(standalone_planned_outputs, "_CACHE", {})
    monkeypatch.setattr(standalone_planned_outputs, "_SOURCES", {})
    monkeypatch.setattr(
        standalone_planned_outputs.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr="backend error"),
    )

    with pytest.raises(ValueError, match="^r$"):
        standalone_planned_outputs.read_output(tmp_path, "x", raw=True, reason="r")


def test_aks_substrate_applies_resources_the_application_reads() -> None:
    targets = standalone_stage_targets.substrate_targets(
        {"runtime_profile": {"runtime_platform": "aks", "database_placement": "postgres-flex"}}
    )

    for address in (
        "module.console",
        "module.operational_history_storage",
        "random_id.cost_pseudonym_key",
        "azurerm_key_vault_secret.cost_pseudonym_key",
        "azurerm_role_assignment.operator_cost_pseudonym_secret_reader",
    ):
        assert address in targets

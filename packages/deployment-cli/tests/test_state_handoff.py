from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from fdai_deployment_cli.cli import main
from fdai_deployment_cli.state_handoff import compare_foundation_state


def inputs() -> tuple[dict, dict, dict]:
    local = {
        "version": 4,
        "terraform_version": "1.9.8",
        "lineage": "00000000-0000-0000-0000-000000000000",
        "serial": 7,
        "outputs": {},
        "resources": [
            {
                "mode": "managed",
                "type": "terraform_data",
                "name": "ownership",
                "module": "module.foundation",
                "instances": [
                    {
                        "index_key": "app",
                        "attributes": {"id": "opaque-resource-id", "input": "opaque-private-value"},
                    }
                ],
            }
        ],
    }
    attributes = deepcopy(local["resources"][0]["instances"][0]["attributes"])
    address = 'module.foundation.terraform_data.ownership["app"]'
    plan = {
        "format_version": "1.2",
        "terraform_version": "1.9.8",
        "complete": True,
        "errored": False,
        "applyable": False,
        "prior_state": {
            "values": {
                "root_module": {
                    "child_modules": [
                        {
                            "address": "module.foundation",
                            "resources": [
                                {
                                    "address": address,
                                    "mode": "managed",
                                    "values": deepcopy(attributes),
                                }
                            ],
                        }
                    ]
                }
            }
        },
        "resource_changes": [
            {
                "address": address,
                "change": {
                    "actions": ["no-op"],
                    "before": attributes,
                    "after": deepcopy(attributes),
                },
            }
        ],
        "output_changes": {},
        "checks": [{"status": "pass"}],
    }
    return local, deepcopy(local), plan


def test_state_comparison_never_grants_backend_or_deletion_authority() -> None:
    local, remote, plan = inputs()
    result = compare_foundation_state(local, remote, plan)
    assert result["comparison_verified"] is True
    assert result["managed_resource_count"] == 1
    assert result["state"] == "review"
    for name in (
        "remote_backend_authority_verified",
        "local_state_deletion_authorized",
        "mutation_performed",
        "subscription_ready",
    ):
        assert result[name] is False
    output = json.dumps(result)
    assert "opaque-private-value" not in output
    assert "opaque-resource-id" not in output
    assert local == remote


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 3),
        ("version", 4.0),
        ("serial", True),
        ("serial", -1),
        ("lineage", None),
        ("resources", []),
        ("resources", {}),
        ("resources", [None]),
    ],
)
def test_invalid_state_is_rejected(field: str, value: object) -> None:
    local, remote, plan = inputs()
    local[field] = value
    with pytest.raises(ValueError):
        compare_foundation_state(local, remote, plan)


@pytest.mark.parametrize(
    "change",
    [
        "serial",
        "lineage",
        "id",
        "name",
        "index",
        "attributes",
        "missing",
        "duplicate",
        "tainted",
        "deposed",
        "bad-index",
        "bad-mode",
    ],
)
def test_changed_or_unsafe_remote_state_is_rejected(change: str) -> None:
    local, remote, plan = inputs()
    resource = remote["resources"][0]
    instance = resource["instances"][0]
    if change == "serial":
        remote["serial"] += 1
    elif change == "lineage":
        remote["lineage"] = "other"
    elif change == "id":
        instance["attributes"]["id"] = "other"
    elif change == "name":
        resource["name"] = "other"
    elif change == "index":
        instance["index_key"] = 0
    elif change == "attributes":
        instance["attributes"]["input"] = "other"
    elif change == "missing":
        resource["instances"] = []
    elif change == "duplicate":
        resource["instances"].append(deepcopy(instance))
    elif change == "tainted":
        instance["status"] = "tainted"
    elif change == "deposed":
        instance["deposed"] = "abcdef01"
    elif change == "bad-index":
        instance["index_key"] = True
    else:
        resource["mode"] = "unknown"
    with pytest.raises(ValueError):
        compare_foundation_state(local, remote, plan)


@pytest.mark.parametrize(
    "field,value",
    [
        ("format_version", []),
        ("format_version", "2.0"),
        ("complete", False),
        ("complete", None),
        ("errored", True),
        ("applyable", True),
        ("resource_drift", [{}]),
        ("deferred_changes", [{}]),
        ("checks", [{"status": "unknown"}]),
        ("prior_state", {}),
        ("resource_changes", {}),
        ("output_changes", {"result": {"actions": ["create"], "before": None, "after": "new"}}),
    ],
)
def test_incomplete_or_changed_plan_is_rejected(field: str, value: object) -> None:
    local, remote, plan = inputs()
    plan[field] = value
    with pytest.raises(ValueError):
        compare_foundation_state(local, remote, plan)


@pytest.mark.parametrize(
    "change",
    [
        "update",
        "import",
        "move",
        "unknown-before",
        "different-after",
        "prior-id",
        "prior-empty",
        "prior-duplicate",
        "deep",
    ],
)
def test_plan_must_be_unchanged_and_bound_to_remote_identities(change: str) -> None:
    local, remote, plan = inputs()
    delta = plan["resource_changes"][0]
    child = plan["prior_state"]["values"]["root_module"]["child_modules"][0]
    if change == "update":
        delta["change"]["actions"] = ["update"]
    elif change == "import":
        delta["change"]["importing"] = {"id": "other"}
    elif change == "move":
        delta["previous_address"] = "other"
    elif change == "unknown-before":
        del delta["change"]["before"]
    elif change == "different-after":
        delta["change"]["after"] = None
    elif change == "prior-id":
        child["resources"][0]["values"]["id"] = "other"
    elif change == "prior-empty":
        child["resources"] = []
    elif change == "prior-duplicate":
        child["resources"].append(deepcopy(child["resources"][0]))
    else:
        for _ in range(34):
            child["child_modules"] = [{}]
            child = child["child_modules"][0]
    with pytest.raises(ValueError):
        compare_foundation_state(local, remote, plan)


@pytest.mark.parametrize("invalid", [False, True])
def test_file_only_command_writes_private_sanitized_comparison(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    invalid: bool,
) -> None:
    tmp_path.chmod(0o700)
    local, remote, plan = inputs()
    if invalid:
        remote["serial"] += 1
    paths = [tmp_path / name for name in ("local.json", "remote.json", "plan.json")]
    for path, value in zip(paths, (local, remote, plan), strict=True):
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)
    output = tmp_path / "comparison.json"
    code = main(
        [
            "provision",
            "verify-state-handoff",
            "--local-state",
            str(paths[0]),
            "--remote-state",
            str(paths[1]),
            "--plan-json",
            str(paths[2]),
            "--output-receipt",
            str(output),
            "--output",
            "json",
        ]
    )
    captured = capsys.readouterr()
    if invalid:
        assert code == 3
        assert not output.exists() and not captured.out
    else:
        assert code == 0
        assert json.loads(captured.out) == json.loads(output.read_bytes())
        assert output.stat().st_mode & 0o777 == 0o600
    assert "opaque-private-value" not in captured.out + captured.err
    assert all(path.exists() for path in paths)

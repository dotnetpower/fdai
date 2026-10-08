"""Landing parsed Azure Policy Rules in the collected tree with stable identity."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.pipeline.collect.azure_policy_landing import (
    AzurePolicyLandingError,
    land_azure_policy_rules,
)
from fdai.rule_catalog.pipeline.collect_cli import main as cli_main
from fdai.rule_catalog.pipeline.parse import build_parser

REVISION = "a" * 40
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _policy(name: str, display: str, *, category: str = "Storage") -> dict[str, object]:
    return {
        "name": name,
        "properties": {
            "displayName": display,
            "policyType": "BuiltIn",
            "metadata": {"category": category, "version": "1.0.0"},
            "parameters": {"effect": {"type": "string", "defaultValue": "Audit"}},
            "policyRule": {
                "if": {"field": "type", "equals": "Microsoft.Storage/storageAccounts"},
                "then": {"effect": "[parameters('effect')]"},
            },
        },
    }


def _tree(root: Path, policies: dict[str, dict[str, object]]) -> Path:
    for relative, body in policies.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")
    return root


def _land(tree: Path, output: Path):
    rules = build_parser("azure-policy-json").parse(tree).rules
    return land_azure_policy_rules(
        rules, resolved_ref=REVISION, retrieved_at=NOW, output_root=output
    )


def _documents(output: Path) -> dict[str, dict[str, object]]:
    return {
        path.relative_to(output).as_posix(): yaml.safe_load(path.read_text())
        for path in sorted(output.rglob("*.yaml"))
    }


def test_landing_stamps_pinned_provenance_and_is_idempotent(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path / "tree",
        {"Storage Account/secure.json": _policy("guid-1", "Secure transfer required")},
    )
    output = tmp_path / "collected"

    first = _land(tree, output)
    second = _land(tree, output)

    assert (first.written, first.unchanged) == (1, 0)
    assert (second.written, second.unchanged, second.withdrawn) == (0, 1, ())
    [(path, document)] = _documents(output).items()
    assert path.startswith("storage-account/azure-builtin_")
    provenance = document["provenance"]
    assert provenance["resolved_ref"] == REVISION
    assert provenance["retrieved_at"] == "2026-10-08T12:00:00Z"
    assert str(provenance["content_hash"]).startswith("sha256:")
    assert provenance["content_hash"] != "sha256:" + "0" * 64


def test_existing_policy_keeps_its_rule_id_and_path(tmp_path: Path) -> None:
    tree = _tree(tmp_path / "tree", {"Storage/one.json": _policy("guid-1", "Secure transfer")})
    output = tmp_path / "collected"
    _land(tree, output)
    [(path, document)] = _documents(output).items()
    curated = dict(document, id="azure-builtin.curated-id")
    (output / path).write_text(yaml.safe_dump(curated, sort_keys=False))

    _tree(tree, {"Storage/one.json": _policy("guid-1", "Secure transfer renamed")})
    _land(tree, output)

    [(after_path, after)] = _documents(output).items()
    assert after_path == path
    assert after["id"] == "azure-builtin.curated-id"
    assert after["parameters"]["azure_policy_display_name"] == "Secure transfer renamed"


def test_colliding_new_policies_are_reported_not_landed(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path / "tree",
        {
            "Storage/a.json": _policy("guid-1", "Same display"),
            "Storage/b.json": _policy("guid-2", "Same display"),
            "Storage/c.json": _policy("guid-3", "Distinct display"),
        },
    )
    output = tmp_path / "collected"

    report = _land(tree, output)

    assert report.skipped_collisions == ("guid-1", "guid-2")
    assert [doc["parameters"]["azure_policy_name"] for doc in _documents(output).values()] == [
        "guid-3"
    ]


def test_withdrawn_policy_is_kept_and_reported(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path / "tree",
        {
            "Storage/a.json": _policy("guid-1", "First policy"),
            "Network/b.json": _policy("guid-2", "Second policy", category="Network"),
        },
    )
    output = tmp_path / "collected"
    _land(tree, output)
    (output / "README.md").write_text("kept")
    (tree / "Network/b.json").unlink()

    report = _land(tree, output)

    assert report.withdrawn == ("guid-2",)
    assert len(_documents(output)) == 2
    assert (output / "README.md").read_text() == "kept"


def test_new_policy_cannot_take_a_withdrawn_rules_identity(tmp_path: Path) -> None:
    tree = _tree(tmp_path / "tree", {"Storage/a.json": _policy("guid-old", "Same display")})
    output = tmp_path / "collected"
    _land(tree, output)
    (tree / "Storage/a.json").unlink()
    _tree(tree, {"Storage/b.json": _policy("guid-new", "Same display")})

    report = _land(tree, output)

    assert report.withdrawn == ("guid-old",)
    assert report.skipped_collisions == ("guid-new",)
    assert [doc["parameters"]["azure_policy_name"] for doc in _documents(output).values()] == [
        "guid-old"
    ]


def test_one_invalid_rule_fails_the_run_before_any_write(tmp_path: Path) -> None:
    tree = _tree(
        tmp_path / "tree",
        {
            "Storage/a.json": _policy("guid-1", "Valid policy"),
            "Storage/b.json": _policy("guid-2", "Invalid policy"),
        },
    )
    rules = list(build_parser("azure-policy-json").parse(tree).rules)
    broken = dict(rules[1].raw, severity="catastrophic")
    rules[1] = type(rules[1])(origin=rules[1].origin, raw=broken)
    output = tmp_path / "collected"

    with pytest.raises(AzurePolicyLandingError, match="schema"):
        land_azure_policy_rules(rules, resolved_ref=REVISION, retrieved_at=NOW, output_root=output)
    assert not output.exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resolved_ref": "0" * 40},
        {"resolved_ref": "main"},
        {"retrieved_at": datetime(2026, 10, 8)},  # noqa: DTZ001 - naive input is the defect
    ],
)
def test_landing_rejects_unpinned_inputs(tmp_path: Path, kwargs: dict[str, object]) -> None:
    tree = _tree(tmp_path / "tree", {"Storage/a.json": _policy("guid-1", "Policy")})
    rules = build_parser("azure-policy-json").parse(tree).rules
    arguments: dict[str, object] = {"resolved_ref": REVISION, "retrieved_at": NOW} | kwargs

    with pytest.raises(AzurePolicyLandingError):
        land_azure_policy_rules(rules, output_root=tmp_path / "out", **arguments)  # type: ignore[arg-type]
    with pytest.raises(AzurePolicyLandingError):
        land_azure_policy_rules(
            (), resolved_ref=REVISION, retrieved_at=NOW, output_root=tmp_path / "out"
        )


def test_cli_refuses_to_land_an_unpinned_local_snapshot(tmp_path: Path) -> None:
    _tree(tmp_path / "src", {"Storage/a.json": _policy("guid-1", "Policy")})
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "id": "azure-policy-local",
                "name": "Local Azure Policy",
                "license": "MIT",
                "redistribution": "embeddable",
                "fetch": {"kind": "local", "path": str(tmp_path / "src")},
                "parser": "azure-policy-json",
            }
        )
    )
    output = tmp_path / "collected"

    exit_code = cli_main(
        [
            "--manifest",
            str(manifest),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "snapshots"),
            "--land-collected",
            str(output),
        ]
    )

    assert exit_code == 2
    assert not output.exists()

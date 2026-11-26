"""Drift-detection contract for the rule <-> Rego semantic synchronizer."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/catalog/sync-rule-semantics.py"
SOURCE_PATH = os.pathsep.join(
    (
        str(REPO_ROOT / "services/core-control-plane/src"),
        str(REPO_ROOT / "packages/service-contracts/src"),
    )
)
requires_opa = pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary unavailable")

POLICY = """# METADATA
# title: Require zone-redundant synthetic cache
# description: |
#   A synthetic cache MUST span at least two availability zones so a zone
#   outage does not evict the whole cache.
# custom:
#   rule_id: synthetic.zone-redundant
#   severity: high
#   category: reliability
package fdai.synthetic.zone_redundant

import rego.v1

default deny := false

deny if {
\tinput.resource.type == "cache"
\tcount(input.resource.props.zones) < 2
}
"""

RULE: dict[str, Any] = {
    "schema_version": "2.0.0",
    "id": "synthetic.zone-redundant",
    "severity": "high",
    "category": "reliability",
    "resource_type": "cache",
    "triggered_by": [],
    "evaluates": [],
    "submission_criteria": [{"kind": "resource_type_registered", "value": "cache"}],
    "check_logic": {"kind": "rego", "reference": "policies/synthetic/zone_redundant.rego"},
}


def _rule_path(repo: Path) -> Path:
    return repo / "rule-catalog/catalog/synthetic.zone-redundant.yaml"


def _write_rule(repo: Path, payload: dict[str, Any]) -> None:
    _rule_path(repo).write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _read_rule(repo: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(_rule_path(repo).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _run(repo: Path, *arguments: str, path: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = SOURCE_PATH
    if path is not None:
        environment["PATH"] = path
    return subprocess.run(  # noqa: S603 - fixed synchronizer with a test-owned repository root.
        [sys.executable, str(SCRIPT), "--repo-root", str(repo), *arguments],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


@pytest.fixture
def catalog_repo(tmp_path: Path) -> Path:
    """Return a minimal repository whose single rule already matches its policy."""

    policy_path = tmp_path / "policies/synthetic/zone_redundant.rego"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text(POLICY, encoding="utf-8")
    _rule_path(tmp_path).parent.mkdir(parents=True)
    _write_rule(tmp_path, RULE)
    if shutil.which("opa") is not None:
        assert _run(tmp_path).returncode == 0
    return tmp_path


@requires_opa
def test_synchronizer_derives_semantics_from_the_policy(catalog_repo: Path) -> None:
    rule = _read_rule(catalog_repo)

    assert rule["triggered_by"] == ["resource.configuration.observed"]
    assert rule["evaluates"] == ["property.cache.zones"]
    assert {"kind": "property_exists", "value": "property.cache.zones"} in rule[
        "submission_criteria"
    ]


@requires_opa
def test_check_passes_on_a_synchronized_catalog(catalog_repo: Path) -> None:
    result = _run(catalog_repo, "--check")

    assert result.returncode == 0, result.stderr
    assert "rule semantic drift" not in result.stderr


@requires_opa
def test_check_fails_on_drifted_evaluates(catalog_repo: Path) -> None:
    rule = _read_rule(catalog_repo)
    rule["evaluates"] = ["property.cache.sku"]
    _write_rule(catalog_repo, rule)

    result = _run(catalog_repo, "--check")

    assert result.returncode == 1
    assert "rule semantic drift" in result.stderr
    assert "synthetic.zone-redundant.yaml" in result.stderr


@requires_opa
def test_check_fails_on_drifted_triggered_by(catalog_repo: Path) -> None:
    rule = _read_rule(catalog_repo)
    rule["triggered_by"] = ["resource.metric.observed"]
    _write_rule(catalog_repo, rule)

    result = _run(catalog_repo, "--check")

    assert result.returncode == 1
    assert "rule semantic drift" in result.stderr


@requires_opa
def test_check_fails_when_the_policy_declares_another_rule_id(catalog_repo: Path) -> None:
    rule = _read_rule(catalog_repo)
    rule["id"] = "synthetic.other-rule"
    _write_rule(catalog_repo, rule)

    result = _run(catalog_repo, "--check")

    assert result.returncode == 1
    assert "rule semantic check failed" in result.stderr
    assert "rule_id mismatch" in result.stderr


@requires_opa
@pytest.mark.parametrize(("field", "value"), [("severity", "low"), ("category", "cost")])
def test_check_fails_on_classification_drift(catalog_repo: Path, field: str, value: str) -> None:
    rule = _read_rule(catalog_repo)
    rule[field] = value
    _write_rule(catalog_repo, rule)

    result = _run(catalog_repo, "--check")

    assert result.returncode == 1
    assert "classification mismatch" in result.stderr


@requires_opa
def test_sync_mode_repairs_drift_that_the_check_rejects(catalog_repo: Path) -> None:
    rule = _read_rule(catalog_repo)
    rule["evaluates"] = ["property.cache.sku"]
    _write_rule(catalog_repo, rule)
    assert _run(catalog_repo, "--check").returncode == 1

    assert _run(catalog_repo).returncode == 0

    assert _read_rule(catalog_repo)["evaluates"] == ["property.cache.zones"]
    assert _run(catalog_repo, "--check").returncode == 0


def test_check_fails_loudly_when_opa_cannot_run(catalog_repo: Path) -> None:
    """An environment without OPA MUST fail the check instead of skipping it."""

    result = _run(catalog_repo, "--check", path="")

    assert result.returncode == 1
    assert "rule semantic check failed" in result.stderr
    assert "OPA parse unavailable" in result.stderr


def test_check_is_wired_into_ci_and_local_gates() -> None:
    command = "scripts/catalog/sync-rule-semantics.py --check"
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    verify = (REPO_ROOT / "scripts/verify.sh").read_text(encoding="utf-8")

    assert f"uv run python {command}" in workflow
    assert f"uv run python {command}" in verify
    assert 'run_gate_scoped "rule-semantics"' in verify

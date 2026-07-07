"""kube-bench parser + imported rule schema validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from fdai.rule_catalog.pipeline.parse.kube_bench import KubeBenchParser
from fdai.rule_catalog.pipeline.parse.parser import (
    ParseError,
    ParserName,
    build_parser,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
COLLECTED_ROOT = REPO_ROOT / "rule-catalog" / "collected" / "kube-bench"


# ---------------------------------------------------------------------------
# Dispatcher wiring
# ---------------------------------------------------------------------------


def test_build_parser_returns_kube_bench_impl() -> None:
    p = build_parser("kube-bench")
    assert isinstance(p, KubeBenchParser)
    assert p.name is ParserName.KUBE_BENCH


# ---------------------------------------------------------------------------
# Parser behavior on synthetic input
# ---------------------------------------------------------------------------


def test_parses_a_minimal_ruleset(tmp_path: Path) -> None:
    version_dir = tmp_path / "cis-1.10"
    version_dir.mkdir()
    (version_dir / "master.yaml").write_text(
        """
controls:
  version: cis-1.10
  id: 1
  text: Control Plane
  type: master
  groups:
    - id: 1.1
      text: Control Plane Node Configuration Files
      checks:
        - id: 1.1.1
          text: Ensure that the API server pod spec file permissions are 600
          audit: stat -c permissions=%a /etc/kubernetes/manifests/kube-apiserver.yaml
          scored: true
          remediation: chmod 600 /etc/kubernetes/manifests/kube-apiserver.yaml
        - id: 1.1.2
          text: Ensure that the API server pod spec file ownership is root:root
          audit: stat -c %U:%G /etc/kubernetes/manifests/kube-apiserver.yaml
          scored: false
""",
        encoding="utf-8",
    )
    report = KubeBenchParser().parse(tmp_path)
    assert report.rule_count == 2
    ids = [r.raw["id"] for r in report.rules]
    assert any("1-1-1" in i for i in ids)
    # Scored -> medium severity; unscored -> low.
    severities = {r.raw["parameters"]["kube_bench_id"]: r.raw["severity"] for r in report.rules}
    assert severities["1.1.1"] == "medium"
    assert severities["1.1.2"] == "low"


def test_skips_config_yaml_and_non_control_yaml(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("some: config", encoding="utf-8")
    (tmp_path / "cis-1.10").mkdir()
    (tmp_path / "cis-1.10" / "config.yaml").write_text("nested: config", encoding="utf-8")
    report = KubeBenchParser().parse(tmp_path)
    assert report.rule_count == 0


def test_raises_on_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text("::: not: yaml [", encoding="utf-8")
    with pytest.raises(ParseError, match="not valid YAML"):
        KubeBenchParser().parse(tmp_path)


def test_raises_on_missing_snapshot(tmp_path: Path) -> None:
    with pytest.raises(ParseError, match="not a directory"):
        KubeBenchParser().parse(tmp_path / "nope")


# ---------------------------------------------------------------------------
# End-to-end: the actually landed collected/kube-bench/ tree validates.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rule_schema_validator() -> Draft202012Validator:
    return Draft202012Validator(dict(PackageResourceSchemaRegistry().get("rule")))


@pytest.mark.skipif(
    not COLLECTED_ROOT.is_dir(),
    reason="rule-catalog/collected/kube-bench/ has not been generated",
)
def test_random_sample_of_collected_kube_bench_rules_validates(
    rule_schema_validator: Draft202012Validator,
) -> None:
    files = sorted(COLLECTED_ROOT.rglob("*.yaml"))
    assert len(files) > 100
    sample = files[:: max(1, len(files) // 20)][:20]
    for f in sample:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        errors = list(rule_schema_validator.iter_errors(data))
        assert not errors, f"{f.name} schema violation: {errors[0].message}"


@pytest.mark.skipif(
    not COLLECTED_ROOT.is_dir(),
    reason="rule-catalog/collected/kube-bench/ has not been generated",
)
def test_collected_tree_uses_kube_bench_source_id() -> None:
    files = sorted(COLLECTED_ROOT.rglob("*.yaml"))[:50]
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert data["source"] == "kube_bench"
        assert data["remediates"] == "remediate.azure-policy-managed"  # placeholder

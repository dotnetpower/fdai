"""CLI resolver - end-to-end offline invocation."""

from __future__ import annotations

import json
from pathlib import Path

from fdai.rule_catalog.schema.llm_resolver import CapabilityStatus
from fdai.rule_catalog.schema.llm_resolver_cli import main

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = REPO_ROOT / "rule-catalog" / "llm-registry.yaml"
FIXTURES = REPO_ROOT / "tests" / "scenarios" / "llm"


def _base_argv(tmp_path: Path, permission: str) -> list[str]:
    return [
        "--registry",
        str(REGISTRY),
        "--region",
        "koreacentral",
        "--subscription-id",
        "00000000-0000-0000-0000-000000000000",
        "--deployer-object-id",
        "00000000-0000-0000-0000-000000000001",
        "--catalog-fixture",
        str(FIXTURES / "catalog.example.json"),
        "--permission-fixture",
        str(FIXTURES / permission),
        "--quota-fixture",
        str(FIXTURES / "quota.full.json"),
        "--out",
        str(tmp_path / "resolved-models.json"),
    ]


def test_cli_writes_resolved_models_for_granted_permission(tmp_path: Path) -> None:
    exit_code = main(_base_argv(tmp_path, "permission.granted.json"))
    assert exit_code == 0

    out_path = tmp_path / "resolved-models.json"
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["region"] == "koreacentral"
    assert payload["mixed_model_mode"] == "azure-foundry"
    caps = {c["name"]: c for c in payload["capabilities"]}
    assert caps["t1.embedding"]["status"] == CapabilityStatus.RESOLVED.value
    assert caps["t2.reasoner.primary"]["status"] == CapabilityStatus.RESOLVED.value
    assert caps["t2.reasoner.secondary"]["status"] == CapabilityStatus.RESOLVED.value


def test_cli_marks_hil_only_when_permission_denied(tmp_path: Path) -> None:
    exit_code = main(_base_argv(tmp_path, "permission.denied.json"))
    assert exit_code == 0
    payload = json.loads((tmp_path / "resolved-models.json").read_text(encoding="utf-8"))
    for cap in payload["capabilities"]:
        assert cap["status"] == CapabilityStatus.HIL_ONLY.value


def test_cli_output_is_stable_across_reruns(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    argv1 = _base_argv(tmp_path, "permission.granted.json")
    argv1[-1] = str(first)
    argv2 = _base_argv(tmp_path, "permission.granted.json")
    argv2[-1] = str(second)
    assert main(argv1) == 0
    assert main(argv2) == 0
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_cli_rejects_bad_catalog_fixture_shape(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")  # array where object expected
    argv = _base_argv(tmp_path, "permission.granted.json")
    argv[argv.index("--catalog-fixture") + 1] = str(bad)
    assert main(argv) == 2


def test_cli_rejects_missing_registry(tmp_path: Path) -> None:
    argv = _base_argv(tmp_path, "permission.granted.json")
    argv[argv.index("--registry") + 1] = str(tmp_path / "nope.yaml")
    assert main(argv) == 2


def test_cli_populates_narrator_when_endpoint_given(tmp_path: Path) -> None:
    """--narrator-endpoint activates single narrator + multi-candidate router feed."""
    endpoint = "https://example-openai.openai.azure.com/"
    argv = [
        *_base_argv(tmp_path, "permission.granted.json"),
        "--narrator-endpoint",
        endpoint,
        "--narrator-api-version",
        "2024-08-01-preview",
    ]
    assert main(argv) == 0
    payload = json.loads((tmp_path / "resolved-models.json").read_text(encoding="utf-8"))

    # Single narrator - fastest available family, URL-safe deployment name.
    assert payload["narrator"]["endpoint"] == endpoint
    assert payload["narrator"]["deployment"] == "narrator-gpt-5-4-mini"
    assert payload["narrator"]["api_version"] == "2024-08-01-preview"

    # Full candidate list - every mini family the fixture catalog + quota
    # allow, in preference order (see rule-catalog/llm-registry.yaml).
    candidates = [c["deployment"] for c in payload["narrator_candidates"]]
    assert candidates == [
        "narrator-gpt-5-4-mini",
        "narrator-gpt-5-mini",
        "narrator-gpt-4-1-mini",
        "narrator-gpt-4o-mini",
    ]
    for c in payload["narrator_candidates"]:
        assert c["endpoint"] == endpoint
        assert c["api_version"] == "2024-08-01-preview"

    # Terraform-side companion: one capability per candidate deployment
    # so ``azurerm_cognitive_deployment`` gets created for each family.
    cap_names = {c["name"] for c in payload["capabilities"]}
    for cand in candidates:
        assert cand in cap_names, f"missing terraform capability for {cand}"

    # The original t1.judge capability is preserved (composition.py depends
    # on it for judge binding); narrator capabilities are additive.
    assert "t1.judge" in cap_names


# ---------------------------------------------------------------------------
# Provisioning completeness gate (--assess-fail-on)
# ---------------------------------------------------------------------------


def test_cli_assess_fail_on_none_reports_only(tmp_path: Path) -> None:
    # Denied permission -> every capability hil-only -> critical severity,
    # but the default fail-on=none is report-only, so exit stays 0.
    assert main(_base_argv(tmp_path, "permission.denied.json")) == 0


def test_cli_assess_fail_on_critical_blocks_denied(tmp_path: Path) -> None:
    argv = [*_base_argv(tmp_path, "permission.denied.json"), "--assess-fail-on", "critical"]
    assert main(argv) == 3
    # The JSON is still written so the pipeline stage can inspect the report.
    assert (tmp_path / "resolved-models.json").exists()


def test_cli_assess_fail_on_critical_allows_granted(tmp_path: Path) -> None:
    # Granted permission resolves the core tier + T2 quorum, so severity is
    # never critical -> a critical gate passes.
    argv = [*_base_argv(tmp_path, "permission.granted.json"), "--assess-fail-on", "critical"]
    assert main(argv) == 0


def test_cli_omits_narrator_fields_by_default(tmp_path: Path) -> None:
    """Legacy invocations without --narrator-endpoint keep the golden shape."""
    assert main(_base_argv(tmp_path, "permission.granted.json")) == 0
    text = (tmp_path / "resolved-models.json").read_text(encoding="utf-8")
    assert "narrator" not in text
    assert "narrator_candidates" not in text


def test_cli_rejects_use_azure_cli_with_fixtures(tmp_path: Path) -> None:
    """--use-azure-cli and fixture flags are mutually exclusive."""
    argv = [
        *_base_argv(tmp_path, "permission.granted.json"),
        "--use-azure-cli",
    ]
    assert main(argv) == 2  # ArgValidationError -> exit 2


def test_cli_rejects_missing_fixture_when_not_using_azure_cli(tmp_path: Path) -> None:
    """Fixture mode requires all three fixture files."""
    argv = [
        "--registry",
        str(REGISTRY),
        "--region",
        "koreacentral",
        "--subscription-id",
        "00000000-0000-0000-0000-000000000000",
        "--deployer-object-id",
        "00000000-0000-0000-0000-000000000001",
        # Only one fixture supplied - the other two are missing.
        "--catalog-fixture",
        str(FIXTURES / "catalog.example.json"),
        "--out",
        str(tmp_path / "resolved-models.json"),
    ]
    assert main(argv) == 2

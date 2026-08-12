"""OpaRegoEvaluator - subprocess-backed policy evaluation against shipped Rego.

The tests are skipped when the ``opa`` binary is not on ``PATH`` (typical
on a fresh developer machine); CI installs OPA via ``.github/workflows/ci.yml``
so the same tests are exercised in the merge gate. A dedicated
:func:`test_missing_binary_raises_at_construction` case runs regardless - it
covers the fail-fast contract by pointing at a binary that does not exist.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.core.tiers.t0_deterministic import (
    MissingOpaBinaryError,
    OpaEvaluatorError,
    OpaRegoEvaluator,
    PolicyResult,
    RuleIndex,
    T0Engine,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import (
    load_resource_type_registry_from_mapping,
)
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[6]
POLICIES_ROOT = REPO_ROOT / "policies"
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
RULES_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"

_OPA_PRESENT = shutil.which("opa") is not None
requires_opa = pytest.mark.skipif(
    not _OPA_PRESENT, reason="opa binary not found on PATH; skip subprocess tests"
)


def _load_shipped_rules() -> tuple[Rule, ...]:
    registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=registry)
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    return load_rule_catalog(
        RULES_ROOT,
        schema_registry=registry,
        action_types=action_types,
        resource_types=resource_types,
        policies_root=POLICIES_ROOT,
    )


def _rules_by_id(rules: tuple[Rule, ...]) -> Mapping[str, Rule]:
    return {r.id: r for r in rules}


def _make_expression_rule() -> Rule:
    return Rule(
        schema_version="1.0.0",
        id="expression.rule",
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type="compute.vm",
        check_logic=CheckLogic(kind=CheckLogicKind.EXPRESSION, reference="stub"),
        remediation=Remediation(template_ref="stub"),
        remediates="remediate.tag-add",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution="embeddable",  # type: ignore[arg-type]
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _make_non_policies_prefix_rule() -> Rule:
    return Rule(
        schema_version="1.0.0",
        id="non.policies.rule",
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type="compute.vm",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="external://foo/bar"),
        remediation=Remediation(template_ref="stub"),
        remediates="remediate.tag-add",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution="embeddable",  # type: ignore[arg-type]
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


# ---------------------------------------------------------------------------
# Fail-fast construction path (runs even without opa on PATH)
# ---------------------------------------------------------------------------


def test_missing_binary_raises_at_construction() -> None:
    with pytest.raises(MissingOpaBinaryError):
        OpaRegoEvaluator(
            policies_root=POLICIES_ROOT,
            opa_binary="definitely-not-an-installed-binary-xyz",
        )


def test_non_directory_policies_root_is_rejected(tmp_path: Path) -> None:
    if not _OPA_PRESENT:
        pytest.skip("opa binary not on PATH; construction requires it before policies_root check")
    bad = tmp_path / "does-not-exist"
    with pytest.raises(ValueError, match="MUST be an existing directory"):
        OpaRegoEvaluator(policies_root=bad)


def test_non_positive_timeout_is_rejected() -> None:
    if not _OPA_PRESENT:
        pytest.skip("opa binary not on PATH")
    with pytest.raises(ValueError, match="timeout_seconds MUST be > 0"):
        OpaRegoEvaluator(policies_root=POLICIES_ROOT, timeout_seconds=0)


# ---------------------------------------------------------------------------
# Package derivation is purely static; runs without opa.
# ---------------------------------------------------------------------------


def test_derive_package_from_relative_path() -> None:
    derived = OpaRegoEvaluator._derive_package(Path("object_storage/public_access.rego"))
    assert derived == "fdai.object_storage.public_access"
    derived_two = OpaRegoEvaluator._derive_package(Path("compute/vmss_over_provisioned.rego"))
    assert derived_two == "fdai.compute.vmss_over_provisioned"


# ---------------------------------------------------------------------------
# OPA subprocess round-trip (skipped when opa is missing)
# ---------------------------------------------------------------------------


@requires_opa
def test_public_access_denied_on_enabled_flag() -> None:
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    rule = _rules_by_id(_load_shipped_rules())["object-storage.public-access.deny"]
    result = evaluator.evaluate(rule, {"public_access": "enabled"})
    assert isinstance(result, PolicyResult)
    assert result.denied is True
    assert result.context.get("deny_reason") == "public_access_enabled"
    assert result.evaluation_receipt is not None
    assert result.evaluation_receipt.decision_path == "data.fdai.object_storage.public_access.deny"
    assert result.evaluation_receipt.denied is True
    assert result.evaluation_receipt.opa_version
    assert result.evaluation_receipt.policy_source_digest.startswith("sha256:")
    assert result.evaluation_receipt.normalized_semantic_digest.startswith("sha256:")


@requires_opa
def test_evaluation_receipt_changes_with_input() -> None:
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    rule = _rules_by_id(_load_shipped_rules())["object-storage.public-access.deny"]

    denied = evaluator.evaluate(rule, {"public_access": "enabled"})
    allowed = evaluator.evaluate(rule, {"public_access": "disabled"})

    assert denied is not None and denied.evaluation_receipt is not None
    assert allowed is not None and allowed.evaluation_receipt is not None
    assert (
        denied.evaluation_receipt.input_evidence_digest
        != allowed.evaluation_receipt.input_evidence_digest
    )
    assert denied.evaluation_receipt.result_digest != allowed.evaluation_receipt.result_digest


@requires_opa
def test_public_access_allowed_on_disabled_flag() -> None:
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    rule = _rules_by_id(_load_shipped_rules())["object-storage.public-access.deny"]
    result = evaluator.evaluate(rule, {"public_access": "disabled"})
    assert isinstance(result, PolicyResult)
    assert result.denied is False
    assert "deny_reason" not in result.context
    assert result.evaluation_receipt is not None
    assert result.evaluation_receipt.denied is False


@requires_opa
def test_owner_tag_missing_denied() -> None:
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    rule = _rules_by_id(_load_shipped_rules())["object-storage.owner-tag.required"]
    result = evaluator.evaluate(rule, {"tags": {"cost-center": "eng"}})
    assert isinstance(result, PolicyResult)
    assert result.denied is True
    assert result.context.get("deny_reason") == "missing_required_tag:owner"


@requires_opa
def test_owner_tag_present_not_denied() -> None:
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    rule = _rules_by_id(_load_shipped_rules())["object-storage.owner-tag.required"]
    result = evaluator.evaluate(rule, {"tags": {"owner": "team-a"}})
    assert isinstance(result, PolicyResult)
    assert result.denied is False


@requires_opa
def test_vmss_over_provisioned_uses_authored_parameter_defaults() -> None:
    """A rule with `parameters` shipped in YAML must override rego defaults.

    The shipped rule sets `max_cpu_p95_percent: 30` and
    `min_headroom_replicas: 1` - a 15% CPU / 5 replicas scenario denies.
    """
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    rule = _rules_by_id(_load_shipped_rules())["compute.vm-scale-set.over-provisioned"]
    result = evaluator.evaluate(rule, {"cpu_p95_percent": 15, "instance_count": 5})
    assert isinstance(result, PolicyResult)
    assert result.denied is True
    assert result.context.get("deny_reason") == "cpu_utilisation_below_threshold_with_headroom"


@requires_opa
def test_secret_rotation_uses_max_age_parameter() -> None:
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    rule = _rules_by_id(_load_shipped_rules())["secret-store.rotation-overdue"]
    denied = evaluator.evaluate(rule, {"age_days": 100})
    assert denied is not None
    assert denied.denied is True
    kept = evaluator.evaluate(rule, {"age_days": 30})
    assert kept is not None
    assert kept.denied is False


@requires_opa
def test_tde_required_denies_on_false() -> None:
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    rule = _rules_by_id(_load_shipped_rules())["sql-database.tde-required"]
    result = evaluator.evaluate(rule, {"tde_enabled": False})
    assert result is not None
    assert result.denied is True
    assert result.context.get("deny_reason") == "tde_disabled"


@requires_opa
def test_expression_kind_returns_none_abstain() -> None:
    """Expression-kind rules are not this evaluator's responsibility."""
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    assert evaluator.evaluate(_make_expression_rule(), {}) is None


@requires_opa
def test_non_policies_prefix_returns_none() -> None:
    """Rego references outside `policies/` are opaque to this evaluator."""
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    assert evaluator.evaluate(_make_non_policies_prefix_rule(), {}) is None


@requires_opa
def test_missing_policy_file_raises_opa_evaluator_error(tmp_path: Path) -> None:
    """Point at a policies_root without the referenced file.

    The evaluator MUST raise `OpaEvaluatorError` so the engine's
    fail-close path records the failure per rule instead of continuing
    with an outdated verdict.
    """
    (tmp_path / "object_storage").mkdir()
    evaluator = OpaRegoEvaluator(policies_root=tmp_path)
    rule = _rules_by_id(_load_shipped_rules())["object-storage.public-access.deny"]
    with pytest.raises(OpaEvaluatorError, match="policy file not found"):
        evaluator.evaluate(rule, {"public_access": "enabled"})


@requires_opa
def test_bad_rego_file_raises_opa_evaluator_error(tmp_path: Path) -> None:
    """A corrupt policy file bubbles up as OpaEvaluatorError."""
    (tmp_path / "object_storage").mkdir()
    (tmp_path / "object_storage" / "public_access.rego").write_text(
        "this is not valid rego syntax\n", encoding="utf-8"
    )
    evaluator = OpaRegoEvaluator(policies_root=tmp_path)
    rule = _rules_by_id(_load_shipped_rules())["object-storage.public-access.deny"]
    with pytest.raises(OpaEvaluatorError, match="opa eval failed"):
        evaluator.evaluate(rule, {"public_access": "enabled"})


@requires_opa
def test_absolute_reference_raises_opa_evaluator_error() -> None:
    """Defense-in-depth: even if a bad rule slips past the loader gate,
    the evaluator refuses an absolute policy path."""
    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)
    bad_rule = Rule(
        schema_version="1.0.0",
        id="bad.abs.path",
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type="compute.vm",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies//etc/passwd"),
        remediation=Remediation(template_ref="stub"),
        remediates="remediate.tag-add",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution="embeddable",  # type: ignore[arg-type]
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )
    with pytest.raises(OpaEvaluatorError, match="repo-relative"):
        evaluator.evaluate(bad_rule, {})


@requires_opa
def test_t0_engine_end_to_end_with_opa_evaluator() -> None:
    """Full round-trip: catalog → index → engine → OpaRegoEvaluator → verdict."""
    from fdai.core.tiers.t0_deterministic import PipelineStage
    from fdai.shared.contracts.models import Mode

    rules = _load_shipped_rules()
    engine = T0Engine(
        index=RuleIndex.build(rules),
        evaluator=OpaRegoEvaluator(policies_root=POLICIES_ROOT),
    )
    verdict = engine.evaluate(
        event_id="evt-1",
        signal_id="sig-1",
        resource_id="rid-1",
        resource_type="object-storage",
        resource_props={"public_access": "enabled", "tags": {}},
    )
    # Both original object-storage rules still fire on this minimal snapshot;
    # newer rules may fire too when their properties are missing, so we assert
    # a subset relationship rather than exact equality.
    fired = {f.rule_id for f in verdict.findings}
    assert {
        "object-storage.public-access.deny",
        "object-storage.owner-tag.required",
    }.issubset(fired)
    assert verdict.audit_hint is not None
    assert verdict.audit_hint.pipeline_stage is PipelineStage.L1_EVALUATE
    assert verdict.audit_hint.mode is Mode.SHADOW
    public_access = next(
        finding
        for finding in verdict.findings
        if finding.rule_id == "object-storage.public-access.deny"
    )
    assert public_access.evaluation_receipt is not None
    assert verdict.audit_hint.evaluation_receipts


@requires_opa
def test_t0_engine_fail_closes_on_broken_policy(tmp_path: Path) -> None:
    """A corrupt policy for one rule MUST NOT kill the T0 evaluation loop.

    Property: `shadow_never_mutates` + `one_bad_rule_does_not_hide_others`.
    """
    from fdai.core.tiers.t0_deterministic import PipelineStage

    # Break just the public-access rego; leave owner-tag intact so
    # the engine's fail-close per-rule path is exercised.
    (tmp_path / "object_storage").mkdir()
    (tmp_path / "object_storage" / "public_access.rego").write_text(
        "not rego at all\n", encoding="utf-8"
    )
    good = POLICIES_ROOT / "object_storage" / "owner_tag_required.rego"
    (tmp_path / "object_storage" / "owner_tag_required.rego").write_text(
        good.read_text(encoding="utf-8"), encoding="utf-8"
    )

    rules = _load_shipped_rules()
    engine = T0Engine(
        index=RuleIndex.build(rules),
        evaluator=OpaRegoEvaluator(policies_root=tmp_path),
    )
    verdict = engine.evaluate(
        event_id="evt-2",
        signal_id="sig-2",
        resource_id="rid-2",
        resource_type="object-storage",
        resource_props={"public_access": "enabled", "tags": {}},
    )
    # public-access.deny abstained (bad rego); owner-tag.required still fired.
    assert {f.rule_id for f in verdict.findings} == {"object-storage.owner-tag.required"}
    assert verdict.audit_hint is not None
    assert verdict.audit_hint.pipeline_stage is PipelineStage.L1_EVALUATE


# ---------------------------------------------------------------------------
# Undefined-result interpretation (no opa needed - parses raw JSON)
# ---------------------------------------------------------------------------


def test_interpret_result_empty_result_list() -> None:
    from fdai.core.tiers.t0_deterministic.opa_evaluator import _interpret_result

    assert _interpret_result({"result": []}) is None
    assert _interpret_result({}) is None


def test_interpret_result_non_object_value() -> None:
    from fdai.core.tiers.t0_deterministic.opa_evaluator import _interpret_result

    # OPA returns a bare value when querying `data.<pkg>.deny` directly;
    # our evaluator queries `data.<pkg>` and expects an object, so a bare
    # bool means "cannot interpret" -> abstain.
    payload: dict[str, Any] = {"result": [{"expressions": [{"value": False}]}]}
    assert _interpret_result(payload) is None


def test_interpret_result_denies_and_carries_reason() -> None:
    from fdai.core.tiers.t0_deterministic.opa_evaluator import _interpret_result

    payload: dict[str, Any] = {
        "result": [{"expressions": [{"value": {"deny": True, "deny_reason": "example"}}]}]
    }
    got = _interpret_result(payload)
    assert got is not None
    assert got.denied is True
    assert got.context == {"deny_reason": "example"}


def test_interpret_result_ignores_non_string_reason() -> None:
    from fdai.core.tiers.t0_deterministic.opa_evaluator import _interpret_result

    payload: dict[str, Any] = {
        "result": [{"expressions": [{"value": {"deny": True, "deny_reason": 42}}]}]
    }
    got = _interpret_result(payload)
    assert got is not None
    assert got.denied is True
    assert got.context == {}


def test_interpret_result_missing_expressions() -> None:
    from fdai.core.tiers.t0_deterministic.opa_evaluator import _interpret_result

    # Some OPA versions may return an empty expressions list on undefined.
    assert _interpret_result({"result": [{}]}) is None
    assert _interpret_result({"result": [{"expressions": []}]}) is None


@requires_opa
def test_timeout_raises_opa_evaluator_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive path: subprocess timeout propagates as OpaEvaluatorError."""
    import subprocess

    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT, timeout_seconds=0.5)

    def _fake_run(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd="opa", timeout=0.001)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    rule = _rules_by_id(_load_shipped_rules())["object-storage.public-access.deny"]
    with pytest.raises(OpaEvaluatorError, match="timed out"):
        evaluator.evaluate(rule, {"public_access": "enabled"})


@requires_opa
def test_non_json_stdout_raises_opa_evaluator_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive path: `opa eval` should always produce JSON on returncode 0;
    if a future version breaks that, we fail closed with a clear error."""
    import subprocess
    from types import SimpleNamespace

    evaluator = OpaRegoEvaluator(policies_root=POLICIES_ROOT)

    def _fake_run(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(returncode=0, stdout="not-json-output", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    rule = _rules_by_id(_load_shipped_rules())["object-storage.public-access.deny"]
    with pytest.raises(OpaEvaluatorError, match="non-JSON"):
        evaluator.evaluate(rule, {"public_access": "enabled"})

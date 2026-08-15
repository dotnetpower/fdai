"""Startup binding of the governed rule-catalog profile."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fdai.core.rule_catalog_profiles import (
    Profile,
    ProfileRegistry,
    ProfileResolutionError,
    ProfileRule,
)
from fdai.core.rule_catalog_profiles.models import ProfileMode, SeverityOverride
from fdai.core.tiers.t0_deterministic import RuleIndex
from fdai.runtime.rule_profile import (
    PROFILE_ID_ENV,
    bind_rule_profile,
    build_profile_registry,
    resolve_rule_profile,
)
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

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG_ROOT = REPO_ROOT / "rule-catalog"


def _rule(
    *,
    rule_id: str,
    severity: Severity = Severity.LOW,
    parameters: dict[str, object] | None = None,
) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=severity,
        category=Category.SECURITY,
        resource_type="azure.storage.account",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates="remediate.tag-add",
        parameters=parameters or {},
        applies_to=["azure.storage.account"],
        triggered_by=["*"],
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution="embeddable",  # type: ignore[arg-type]
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _registry(*profiles: Profile) -> ProfileRegistry:
    return ProfileRegistry(profiles=list(profiles))


# ---------------------------------------------------------------------------
# Selection, grading, and the shared immutable result
# ---------------------------------------------------------------------------


def test_binding_activates_only_the_profile_subset() -> None:
    rules = [_rule(rule_id="rule-a"), _rule(rule_id="rule-b"), _rule(rule_id="rule-c")]
    profile = Profile(
        id="subset",
        title="Subset",
        rules=(ProfileRule(id="rule-a"), ProfileRule(id="rule-c")),
    )

    binding = resolve_rule_profile(rules, profile_id="subset", registry=_registry(profile))

    assert [rule.id for rule in binding.rules] == ["rule-a", "rule-c"]
    assert binding.excluded_rule_ids == ("rule-b",)


def test_t0_index_and_safety_check_read_the_same_immutable_rule() -> None:
    rules = [_rule(rule_id="rule-a", severity=Severity.LOW), _rule(rule_id="rule-b")]
    profile = Profile(
        id="graded",
        title="Graded",
        rules=(ProfileRule(id="rule-a", severity_override=SeverityOverride.CRITICAL),),
    )

    binding = resolve_rule_profile(rules, profile_id="graded", registry=_registry(profile))
    index = RuleIndex.build(binding.rules)

    # The deterministic tier resolves candidates from this index and the safety
    # check evaluates the same indexed object, so they cannot observe different
    # severities or parameters.
    candidate = index.rules_for_type("azure.storage.account")[0]
    assert index.rule("rule-a") is candidate
    assert candidate is binding.rules[0]
    assert candidate.severity is Severity.CRITICAL


def test_binding_does_not_mutate_the_loaded_catalog_rule() -> None:
    source = _rule(rule_id="rule-a", severity=Severity.LOW, parameters={"keep": 1})
    profile = Profile(
        id="graded",
        title="Graded",
        rules=(
            ProfileRule(
                id="rule-a",
                severity_override=SeverityOverride.HIGH,
                parameters={"added": 2},
            ),
        ),
    )

    binding = resolve_rule_profile([source], profile_id="graded", registry=_registry(profile))

    assert source.severity is Severity.LOW
    assert source.parameters == {"keep": 1}
    assert binding.rules[0].severity is Severity.HIGH
    assert binding.rules[0].parameters == {"keep": 1, "added": 2}
    assert binding.escalated_rule_ids == ("rule-a",)


def test_enforce_mode_is_reported_but_grants_no_promotion() -> None:
    profile = Profile(
        id="enforced",
        title="Enforced",
        rules=(ProfileRule(id="rule-a", mode=ProfileMode.ENFORCE),),
    )

    binding = resolve_rule_profile(
        [_rule(rule_id="rule-a")], profile_id="enforced", registry=_registry(profile)
    )

    assert binding.enforce_requested_rule_ids == ("rule-a",)
    # The bound rule carries no execution authority field; promotion stays with
    # the authoritative registry.
    assert not hasattr(binding.rules[0], "mode")


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


def test_unknown_rule_reference_fails_closed() -> None:
    profile = Profile(id="p", title="P", rules=(ProfileRule(id="rule-missing"),))
    with pytest.raises(ProfileResolutionError):
        resolve_rule_profile([_rule(rule_id="rule-a")], profile_id="p", registry=_registry(profile))


def test_severity_downgrade_fails_closed() -> None:
    profile = Profile(
        id="p",
        title="P",
        rules=(ProfileRule(id="rule-a", severity_override=SeverityOverride.LOW),),
    )
    with pytest.raises(ProfileResolutionError):
        resolve_rule_profile(
            [_rule(rule_id="rule-a", severity=Severity.CRITICAL)],
            profile_id="p",
            registry=_registry(profile),
        )


def test_profile_activating_no_catalog_rule_fails_closed() -> None:
    profile = Profile(id="p", title="P", rules=(ProfileRule(id="rule-a", disabled=True),))
    with pytest.raises(ProfileResolutionError, match="activates no catalog rule"):
        resolve_rule_profile([_rule(rule_id="rule-a")], profile_id="p", registry=_registry(profile))


def test_unknown_profile_id_fails_closed() -> None:
    with pytest.raises(ProfileResolutionError):
        bind_rule_profile(
            [_rule(rule_id="rule-a")],
            catalog_root=CATALOG_ROOT,
            environ={PROFILE_ID_ENV: "no-such-profile"},
        )


# ---------------------------------------------------------------------------
# Environment knob and startup diagnostics
# ---------------------------------------------------------------------------


def test_absent_knob_keeps_the_whole_catalog() -> None:
    rules = [_rule(rule_id="rule-a")]
    assert bind_rule_profile(rules, catalog_root=CATALOG_ROOT, environ={}) is None
    assert (
        bind_rule_profile(rules, catalog_root=CATALOG_ROOT, environ={PROFILE_ID_ENV: "  "}) is None
    )


def test_digest_is_stable_and_changes_with_the_resolved_grade() -> None:
    rules = [_rule(rule_id="rule-a")]
    plain = Profile(id="p", title="P", rules=(ProfileRule(id="rule-a"),))
    graded = Profile(
        id="p",
        title="P",
        rules=(ProfileRule(id="rule-a", severity_override=SeverityOverride.HIGH),),
    )

    first = resolve_rule_profile(rules, profile_id="p", registry=_registry(plain))
    second = resolve_rule_profile(rules, profile_id="p", registry=_registry(plain))
    escalated = resolve_rule_profile(rules, profile_id="p", registry=_registry(graded))

    assert first.digest == second.digest
    assert first.digest != escalated.digest


def test_startup_diagnostics_expose_profile_and_digest_only(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_value = "00000000-0000-0000-0000-000000000000"
    rules = [_rule(rule_id="rule-a", parameters={"subscription_id": tenant_value})]
    profile = Profile(id="p", title="P", rules=(ProfileRule(id="rule-a"),))
    monkeypatch.setattr(
        "fdai.runtime.rule_profile.build_profile_registry",
        lambda catalog_root: _registry(profile),
    )

    with caplog.at_level(logging.INFO, logger="fdai.startup"):
        binding = bind_rule_profile(rules, catalog_root=CATALOG_ROOT, environ={PROFILE_ID_ENV: "p"})

    assert binding is not None
    record = next(r for r in caplog.records if r.message == "rule_profile_bound")
    assert record.profile_id == "p"  # type: ignore[attr-defined]
    assert record.profile_digest == binding.digest  # type: ignore[attr-defined]
    assert tenant_value not in caplog.text
    assert set(binding.diagnostics()) == {
        "profile_id",
        "profile_digest",
        "activated_rules",
        "excluded_rules",
        "escalated_rules",
        "enforce_requested_rules",
    }


def test_shipped_profiles_load_from_the_repository_layout() -> None:
    registry = build_profile_registry(CATALOG_ROOT)
    assert registry.get("baseline") is not None
    assert registry.get("recommended") is not None
    assert registry.get("strict") is not None

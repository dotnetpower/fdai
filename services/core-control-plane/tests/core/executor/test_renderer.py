"""Tests for the remediation-template renderer (P1 W-3 Step 3e)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.core.executor.renderer import (
    RenderError,
    RenderRequest,
    TemplateRenderer,
)
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"


def _rule(
    *,
    rule_id: str,
    resource_type: str,
    remediates: str,
    template_ref: str,
    parameters: dict | None = None,
    check_logic_kind: CheckLogicKind = CheckLogicKind.REGO,
) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.HIGH,
        category=Category.SECURITY,
        resource_type=resource_type,
        check_logic=CheckLogic(kind=check_logic_kind, reference="policies/x.rego"),
        remediation=Remediation(template_ref=template_ref),
        remediates=remediates,
        parameters=parameters or {},
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def test_renderer_rejects_non_directory_root(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    with pytest.raises(ValueError, match="MUST be an existing directory"):
        TemplateRenderer(remediation_root=missing)


def test_disable_public_access_template_renders_with_resource_id() -> None:
    r = _rule(
        rule_id="object-storage.public-access.deny",
        resource_type="object-storage",
        remediates="remediate.disable-public-access",
        template_ref="remediation/object_storage/disable_public_access.tftpl",
    )
    text = TemplateRenderer(remediation_root=REMEDIATION_ROOT).render(
        RenderRequest(rule=r, resource_id="stg1", params={})
    )
    assert 'resource "azurerm_storage_account" "stg1"' in text
    assert "public_network_access_enabled" in text


def test_tag_owner_template_uses_action_params_over_rule_defaults() -> None:
    r = _rule(
        rule_id="object-storage.owner-tag.required",
        resource_type="object-storage",
        remediates="remediate.tag-add",
        template_ref="remediation/object_storage/tag_owner.tftpl",
        parameters={"tag_name": "owner", "tag_value": "unknown"},
    )
    text = TemplateRenderer(remediation_root=REMEDIATION_ROOT).render(
        RenderRequest(
            rule=r,
            resource_id="stg1",
            params={"tag_value": "team-a"},  # overrides rule default
        )
    )
    assert '"owner" = "team-a"' in text


def test_missing_placeholder_raises_render_error() -> None:
    """`vmss_right_size.tftpl` requires `target_capacity` - omit it."""
    r = _rule(
        rule_id="compute.vm-scale-set.over-provisioned",
        resource_type="compute.vm-scale-set",
        remediates="remediate.right-size",
        template_ref="remediation/compute/vmss_right_size.tftpl",
    )
    with pytest.raises(RenderError, match="target_capacity"):
        TemplateRenderer(remediation_root=REMEDIATION_ROOT).render(
            RenderRequest(rule=r, resource_id="vmss1", params={})
        )


def test_nested_placeholder_value_is_rejected() -> None:
    r = _rule(
        rule_id="x.y",
        resource_type="object-storage",
        remediates="remediate.tag-add",
        template_ref="remediation/object_storage/tag_owner.tftpl",
    )
    with pytest.raises(RenderError, match="MUST be a scalar"):
        TemplateRenderer(remediation_root=REMEDIATION_ROOT).render(
            RenderRequest(
                rule=r,
                resource_id="stg1",
                params={"tag_name": {"nested": True}, "tag_value": "y"},
            )
        )


def test_bool_placeholder_serializes_to_terraform_literal() -> None:
    r = _rule(
        rule_id="x.y",
        resource_type="object-storage",
        remediates="remediate.tag-add",
        template_ref="remediation/object_storage/tag_owner.tftpl",
    )
    text = TemplateRenderer(remediation_root=REMEDIATION_ROOT).render(
        RenderRequest(
            rule=r,
            resource_id="stg1",
            params={"tag_name": "owner", "tag_value": True},
        )
    )
    assert '"owner" = "true"' in text


def test_int_and_float_placeholders_are_stringified() -> None:
    r = _rule(
        rule_id="compute.vm-scale-set.over-provisioned",
        resource_type="compute.vm-scale-set",
        remediates="remediate.right-size",
        template_ref="remediation/compute/vmss_right_size.tftpl",
    )
    text = TemplateRenderer(remediation_root=REMEDIATION_ROOT).render(
        RenderRequest(
            rule=r,
            resource_id="vmss1",
            params={"target_capacity": 3, "previous_capacity": 10.0},
        )
    )
    assert "instances = 3" in text


def test_absolute_template_ref_is_rejected() -> None:
    r = _rule(
        rule_id="x.y",
        resource_type="object-storage",
        remediates="remediate.tag-add",
        template_ref="remediation//etc/passwd",
    )
    with pytest.raises(RenderError, match="repo-relative"):
        TemplateRenderer(remediation_root=REMEDIATION_ROOT).render(
            RenderRequest(rule=r, resource_id="stg1", params={})
        )


def test_parent_traversal_template_ref_is_rejected() -> None:
    r = _rule(
        rule_id="x.y",
        resource_type="object-storage",
        remediates="remediate.tag-add",
        template_ref="remediation/../etc/passwd",
    )
    with pytest.raises(RenderError, match="repo-relative"):
        TemplateRenderer(remediation_root=REMEDIATION_ROOT).render(
            RenderRequest(rule=r, resource_id="stg1", params={})
        )


def test_non_remediation_prefix_is_rejected() -> None:
    r = _rule(
        rule_id="x.y",
        resource_type="object-storage",
        remediates="remediate.tag-add",
        template_ref="artifact://foo/bar",
    )
    with pytest.raises(RenderError, match="MUST start with 'remediation/'"):
        TemplateRenderer(remediation_root=REMEDIATION_ROOT).render(
            RenderRequest(rule=r, resource_id="stg1", params={})
        )


def test_missing_template_file_raises_render_error(tmp_path: Path) -> None:
    (tmp_path / "compute").mkdir()
    r = _rule(
        rule_id="x.y",
        resource_type="compute.vm-scale-set",
        remediates="remediate.right-size",
        template_ref="remediation/compute/absent.tftpl",
    )
    with pytest.raises(RenderError, match="not found"):
        TemplateRenderer(remediation_root=tmp_path).render(
            RenderRequest(rule=r, resource_id="vmss1", params={"target_capacity": 3})
        )


def test_oversize_template_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "compute").mkdir()
    huge = tmp_path / "compute" / "huge.tftpl"
    huge.write_text("x" * (65 * 1024), encoding="utf-8")
    r = _rule(
        rule_id="x.y",
        resource_type="compute.vm-scale-set",
        remediates="remediate.right-size",
        template_ref="remediation/compute/huge.tftpl",
    )
    with pytest.raises(RenderError, match="exceeds"):
        TemplateRenderer(remediation_root=tmp_path).render(
            RenderRequest(rule=r, resource_id="vmss1", params={"target_capacity": 3})
        )


def test_action_params_override_rule_parameters_on_conflict() -> None:
    r = _rule(
        rule_id="compute.vm-scale-set.over-provisioned",
        resource_type="compute.vm-scale-set",
        remediates="remediate.right-size",
        template_ref="remediation/compute/vmss_right_size.tftpl",
        parameters={"target_capacity": 100, "previous_capacity": 200},
    )
    text = TemplateRenderer(remediation_root=REMEDIATION_ROOT).render(
        RenderRequest(
            rule=r,
            resource_id="vmss1",
            params={"target_capacity": 5},  # wins
        )
    )
    assert "instances = 5" in text

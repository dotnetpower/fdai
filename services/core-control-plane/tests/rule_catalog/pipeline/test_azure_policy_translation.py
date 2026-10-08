"""Azure Policy translation produces inert candidates only for the reviewed grammar."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.core.tiers.t0_deterministic import OpaRegoEvaluator
from fdai.rule_catalog.pipeline.translate.azure_policy import (
    AzurePolicyTranslationError,
    load_alias_map,
    translate_policy,
    translate_snapshot,
)
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[5]
ALIASES = load_alias_map(ROOT / "rule-catalog/translation/azure-policy/aliases.yaml")
REVISION = "a" * 40
STORAGE = "Microsoft.Storage/storageAccounts"
VAULT = "Microsoft.KeyVault/vaults"
HTTPS = f"{STORAGE}/supportsHttpsTrafficOnly"
TLS = f"{STORAGE}/minimumTlsVersion"

requires_opa = pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary not found")


def _definition(
    condition: Any,
    *,
    resource_type: str = STORAGE,
    effect: str = "Audit",
    mode: str = "Indexed",
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": "0a1b2c3d-synthetic-definition",
        "properties": {
            "displayName": "Synthetic policy",
            "policyType": "BuiltIn",
            "mode": mode,
            "version": "1.0.0",
            "parameters": {
                "effect": {"type": "String", "defaultValue": effect},
                **(parameters or {}),
            },
            "policyRule": {
                "if": {"allOf": [{"field": "type", "equals": resource_type}, condition]},
                "then": {"effect": "[parameters('effect')]"},
            },
        },
    }


def _translate(definition: dict[str, Any]):
    return translate_policy(
        definition,
        alias_map=ALIASES,
        content_hash="sha256:" + "0" * 63 + "1",
        origin="Storage/synthetic.json",
        resolved_ref=REVISION,
        retrieved_at="2026-10-08T00:00:00Z",
    )


def _evaluate(tmp_path: Path, result: Any, props: dict[str, Any]) -> bool:
    rule = Rule.model_validate(result.rule)
    path = tmp_path / "policies" / rule.check_logic.reference.removeprefix("policies/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.rego)
    evaluated = OpaRegoEvaluator(policies_root=tmp_path / "policies").evaluate(rule, props)
    assert evaluated is not None
    return evaluated.denied


def test_short_circuited_branches_translate_with_every_read_property_required() -> None:
    # The secure-transfer built-in: an apiVersion branch is decided false by its exists conjunct.
    condition = {
        "anyOf": [
            {
                "allOf": [
                    {"value": "[requestContext().apiVersion]", "less": "2019-04-01"},
                    {"field": HTTPS, "exists": "false"},
                ]
            },
            {"field": HTTPS, "equals": "false"},
        ]
    }

    result = _translate(_definition(condition))

    assert result.status == "translated"
    rule = Rule.model_validate(result.rule)
    assert rule.evaluates == ["property.object-storage.enable_https_traffic_only"]
    assert result.translation["activation"] == "inert"
    assert result.translation["translator_digest"].startswith("sha256:")
    schema = PackageResourceSchemaRegistry().get("rule")
    assert not list(Draft202012Validator(dict(schema)).iter_errors(dict(result.rule)))


@requires_opa
def test_translated_conditions_match_azure_policy_semantics(tmp_path: Path) -> None:
    https = _translate(_definition({"field": HTTPS, "equals": "false"}))
    tls = _translate(
        _definition(
            {"field": TLS, "notEquals": "[parameters('minimumTlsVersion')]"},
            parameters={"minimumTlsVersion": {"type": "String", "defaultValue": "TLS1_2"}},
        )
    )

    assert _evaluate(tmp_path, https, {"enable_https_traffic_only": False})
    assert not _evaluate(tmp_path, https, {"enable_https_traffic_only": True})
    assert _evaluate(tmp_path, tls, {"min_tls_version": "TLS1_0"})
    assert not _evaluate(tmp_path, tls, {"min_tls_version": "tls1_2"})
    assert not _evaluate(tmp_path, tls, {"min_tls_version": 12})
    assert tls.translation["condition_parameters"] == ["minimumTlsVersion"]


@requires_opa
def test_request_only_create_mode_is_absent_on_stored_vaults(tmp_path: Path) -> None:
    condition = {
        "allOf": [
            {"not": {"field": f"{VAULT}/createMode", "equals": "recover"}},
            {
                "anyOf": [
                    {"field": f"{VAULT}/enableSoftDelete", "equals": "false"},
                    {"field": f"{VAULT}/enableSoftDelete", "exists": "false"},
                ]
            },
        ]
    }

    result = _translate(_definition(condition, resource_type=VAULT))

    assert result.status == "translated"
    assert _evaluate(tmp_path, result, {"soft_delete_enabled": False})
    assert not _evaluate(tmp_path, result, {"soft_delete_enabled": True})


@pytest.mark.parametrize(
    ("definition", "reason"),
    [
        (_definition({"field": HTTPS, "equals": "false"}, effect="Modify"), "unsupported_effect"),
        (
            _definition({"field": HTTPS, "equals": "false"}, mode="Microsoft.KeyVault.Data"),
            "unsupported_mode",
        ),
        (
            _definition({"value": "[requestContext().apiVersion]", "less": "2019"}),
            "value_condition",
        ),
        (
            _definition({"field": f"{STORAGE}/networkAcls.defaultAction", "equals": "Allow"}),
            "unmapped_field",
        ),
        (
            _definition({"field": f"{STORAGE}/networkAcls.ipRules[*].value", "equals": "x"}),
            "array_alias",
        ),
        (_definition({"count": {"field": f"{STORAGE}/x[*]"}, "greater": 0}), "count_condition"),
        (_definition({"field": HTTPS, "like": "f*"}), "unsupported_operator"),
        (
            _definition(
                {"field": f"{VAULT}/enablePurgeProtection", "exists": "false"}, resource_type=VAULT
            ),
            "exists_on_defaulted_alias",
        ),
        (
            _definition({"field": f"{VAULT}/enableSoftDelete", "equals": "false"}),
            "alias_type_mismatch",
        ),
        (
            _definition({"field": HTTPS, "equals": "[parameters('missing')]"}),
            "parameter_without_default",
        ),
        (_definition({"field": HTTPS, "exists": "true"}), "constant_condition"),
        (
            _definition(
                {"field": f"{VAULT}/enablePurgeProtection", "notEquals": "false"},
                resource_type=VAULT,
            ),
            "comparison_on_defaulted_alias",
        ),
        (
            _definition({"field": TLS, "notIn": ["[concat('TLS', '1_2')]", "TLS1_3"]}),
            "expression_literal",
        ),
        (
            _definition({"field": HTTPS, "equals": "false"}, resource_type="Microsoft.Web/sites"),
            "unmapped_resource_type",
        ),
    ],
)
def test_conditions_outside_the_grammar_are_refused(
    definition: dict[str, Any], reason: str
) -> None:
    result = _translate(definition)

    assert (result.status, result.reason, result.rule) == ("refused", reason, None)


def test_unreviewed_or_inconsistent_alias_maps_are_rejected(tmp_path: Path) -> None:
    raw = yaml.safe_load((ROOT / "rule-catalog/translation/azure-policy/aliases.yaml").read_text())
    variants = [
        {**raw, "review_state": "draft"},
        {**raw, "aliases": [{**raw["aliases"][0], "codec": "regex"}]},
        {**raw, "aliases": [{**raw["aliases"][0], "rationale": " "}]},
        {**raw, "aliases": [raw["aliases"][0], raw["aliases"][0]]},
    ]
    for index, variant in enumerate(variants):
        path = tmp_path / f"aliases-{index}.yaml"
        path.write_text(yaml.safe_dump(variant))
        with pytest.raises(AzurePolicyTranslationError):
            load_alias_map(path)


def test_snapshot_translation_dedupes_and_requires_a_pinned_revision(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    for folder in ("Storage", "Azure Government"):
        (tree / folder).mkdir(parents=True)
        (tree / folder / "policy.json").write_text(
            json.dumps(_definition({"field": HTTPS, "equals": "false"}))
        )

    result = translate_snapshot(
        tree, alias_map=ALIASES, resolved_ref=REVISION, retrieved_at="2026-10-08T00:00:00Z"
    )

    assert result.summary()["definitions"] == 1
    assert result.summary()["outcomes"] == {"translated": 1}
    with pytest.raises(AzurePolicyTranslationError):
        translate_snapshot(
            tree, alias_map=ALIASES, resolved_ref="0" * 40, retrieved_at="2026-10-08T00:00:00Z"
        )


def test_parameters_inside_lists_resolve_and_are_recorded() -> None:
    result = _translate(
        _definition(
            {"field": TLS, "notIn": ["[parameters('tls')]", "TLS1_3"]},
            parameters={"tls": {"type": "String", "defaultValue": "TLS1_2"}},
        )
    )

    assert result.status == "translated"
    assert '{"tls1_2", "tls1_3"}' in result.rego
    assert result.translation["condition_parameters"] == ["tls"]

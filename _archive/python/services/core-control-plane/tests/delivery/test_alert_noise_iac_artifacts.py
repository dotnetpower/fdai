"""No-network alert IaC artifact coverage for exact-source safety boundaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.delivery.alert_noise_artifacts import (
    AlertPlanArtifactPreparer,
    parse_alert_iac_bindings,
)
from fdai.delivery.alert_noise_iac import (
    AlertIaCBinding,
    conditional_restore,
    render_alert_iac,
)
from fdai_service_contracts.alert_noise import digest_record

from tests.core.detection.alert_noise.conftest import evidence as evidence
from tests.core.detection.alert_noise.conftest import now as now
from tests.core.detection.alert_noise.test_execution import harness as harness


class _Source:
    def __init__(self, rows: dict[str, str | None]) -> None:
        self.rows, self.paths = rows, []

    async def read(self, *, path: str) -> str | None:
        self.paths.append(path)
        return self.rows.get(path)


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _source(resource_type: str, body: dict[str, Any]) -> str:
    return json.dumps({"resource": {resource_type: {"example": body}}}) + "\n"


def _binding(
    *,
    target_ref: str = "rule:example",
    resource_type: str = "azurerm_monitor_metric_alert",
    source: str,
    field: str = "action",
    group_ids: dict[str, str] | None = None,
) -> AlertIaCBinding:
    return AlertIaCBinding(
        path="infra/example.tf.json",
        source_digest=_sha(source),
        resource_type=resource_type,
        resource_name="example",
        field=field,
        group_ids=group_ids or {"group:old": "native-old", "group:new": "native-new"},
        target_ref=target_ref,
    )


def _binding_row(binding: AlertIaCBinding) -> dict[str, Any]:
    return {
        "path": binding.path,
        "source_digest": binding.source_digest,
        "resource_type": binding.resource_type,
        "resource_name": binding.resource_name,
        "field": binding.field,
        "group_ids": dict(binding.group_ids),
        "target_ref": binding.target_ref,
    }


async def test_artifact_preparer_retains_exact_patch_once(harness: SimpleNamespace) -> None:
    h = harness
    assert h.source.content is not None
    binding = _binding(
        source=h.source.content,
        group_ids={"group:old": "group:old", "group:new": "group:new"},
    )
    source = _Source({binding.path: h.source.content})
    preparer = AlertPlanArtifactPreparer(
        source=source,
        store=h.store,
        bindings={binding.target_ref: binding},
    )

    await preparer.prepare(plan=h.plan, evidence=h.evidence)
    await preparer.prepare(plan=h.plan, evidence=h.evidence)

    retained = await h.store.read_state("alert-noise:patch:" + digest_record(h.plan))
    assert retained is not None
    assert retained["plan_digest"] == digest_record(h.plan)
    assert retained["source_digest"] == binding.source_digest
    assert retained["result_digest"].startswith("sha256:")
    assert source.paths == [binding.path, binding.path]


async def test_artifact_preparer_holds_unbound_missing_and_conflicting_source(
    harness: SimpleNamespace,
) -> None:
    h = harness
    assert h.source.content is not None
    binding = _binding(
        source=h.source.content,
        group_ids={"group:old": "group:old", "group:new": "group:new"},
    )
    key = "alert-noise:patch:" + digest_record(h.plan)

    with pytest.raises(AlertExecutionHeld, match="iac_target_unbound"):
        await AlertPlanArtifactPreparer(source=_Source({}), store=h.store, bindings={}).prepare(
            plan=h.plan, evidence=h.evidence
        )
    with pytest.raises(AlertExecutionHeld, match="iac_source_missing"):
        await AlertPlanArtifactPreparer(
            source=_Source({binding.path: None}),
            store=h.store,
            bindings={binding.target_ref: binding},
        ).prepare(plan=h.plan, evidence=h.evidence)

    await h.store.write_state(key, {"plan_digest": "sha256:" + "0" * 64})
    with pytest.raises(AlertExecutionHeld, match="iac_artifact_conflict"):
        await AlertPlanArtifactPreparer(
            source=_Source({binding.path: h.source.content}),
            store=h.store,
            bindings={binding.target_ref: binding},
        ).prepare(plan=h.plan, evidence=h.evidence)


def test_parse_alert_iac_bindings_accepts_only_bounded_unique_json() -> None:
    source = _source("azurerm_monitor_metric_alert", {"action": []})
    row = _binding_row(_binding(source=source))
    assert parse_alert_iac_bindings({}) == {}
    parsed = parse_alert_iac_bindings({"FDAI_ALERT_NOISE_IAC_BINDINGS_JSON": json.dumps([row])})
    assert parsed["rule:example"] == AlertIaCBinding(**row)

    invalid_values = [
        "",
        "{}",
        "[]",
        "[1]",
        json.dumps([row, row]),
        json.dumps([{**row, "path": "../example.tf.json"}]),
        '[{"path":"infra/example.tf.json","path":"infra/other.tf.json"}]',
        json.dumps([row] * 65),
    ]
    for raw in invalid_values:
        with pytest.raises(ValueError, match="alert IaC configuration"):
            parse_alert_iac_bindings({"FDAI_ALERT_NOISE_IAC_BINDINGS_JSON": raw})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", "/infra/example.tf.json"),
        ("path", "infra/../example.tf.json"),
        ("source_digest", "sha256:" + "g" * 64),
        ("resource_name", "1bad"),
        ("target_ref", "Rule:Example"),
        ("resource_type", "azurerm_monitor_action_group"),
        ("group_ids", {1: "native-old"}),
    ],
)
def test_iac_bindings_reject_untrusted_selectors(field: str, value: object) -> None:
    source = _source("azurerm_monitor_metric_alert", {"action": []})
    values = _binding_row(_binding(source=source))
    values[field] = value
    with pytest.raises(ValueError):
        AlertIaCBinding(**values)


async def test_metric_and_log_routing_patch_only_exact_declared_group(
    harness: SimpleNamespace,
) -> None:
    h = harness
    metric_source = _source(
        "azurerm_monitor_metric_alert",
        {"action": [{"action_group_id": "native-old"}], "description": "keep"},
    )
    patch = render_alert_iac(
        h.plan,
        h.evidence,
        binding=_binding(source=metric_source),
        source=metric_source,
    )
    assert '"action_group_id": "native-new"' in patch.forward
    assert '"description": "keep"' in patch.forward
    assert conditional_restore(patch, current=patch.forward) == patch.rollback
    with pytest.raises(ValueError, match="newer IaC revision"):
        conditional_restore(patch, current=patch.rollback)

    log_source = _source(
        "azurerm_monitor_scheduled_query_rules_alert_v2",
        {"action": [{"action_groups": ["native-old", "native-keep"]}]},
    )
    log_patch = render_alert_iac(
        h.plan,
        h.evidence,
        binding=_binding(
            source=log_source,
            resource_type="azurerm_monitor_scheduled_query_rules_alert_v2",
        ),
        source=log_source,
    )
    assert '"native-new"' in log_patch.forward and '"native-keep"' in log_patch.forward


async def test_renderer_refuses_malformed_documents_and_incomplete_group_mapping(
    harness: SimpleNamespace,
) -> None:
    h = harness
    scalar = '"not-an-object"'
    with pytest.raises(ValueError, match="document MUST be an object"):
        render_alert_iac(
            h.plan,
            h.evidence,
            binding=_binding(source=scalar),
            source=scalar,
        )
    missing_resource = json.dumps({"resource": {"azurerm_monitor_metric_alert": {}}}) + "\n"
    with pytest.raises(ValueError, match="existing resource"):
        render_alert_iac(
            h.plan,
            h.evidence,
            binding=_binding(source=missing_resource),
            source=missing_resource,
        )
    malformed_resource = (
        json.dumps({"resource": {"azurerm_monitor_metric_alert": {"example": []}}}) + "\n"
    )
    with pytest.raises(ValueError, match="resource is malformed"):
        render_alert_iac(
            h.plan,
            h.evidence,
            binding=_binding(source=malformed_resource),
            source=malformed_resource,
        )
    source = _source("azurerm_monitor_metric_alert", {"action": [{"action_group_id": "old"}]})
    with pytest.raises(ValueError, match="group mapping"):
        render_alert_iac(
            h.plan,
            h.evidence,
            binding=_binding(source=source, group_ids={"group:old": "old"}),
            source=source,
        )
    with pytest.raises(ValueError, match="exact existing action list"):
        render_alert_iac(
            h.plan,
            h.evidence,
            binding=_binding(source=source, field="schedule"),
            source=source,
        )


@pytest.mark.parametrize(
    "body",
    [
        {"action": []},
        {"action": [{"action_groups": "native-old"}]},
        {"action": [{"action_groups": ["native-old", "native-new"]}]},
        {"action": [{"action_groups": ["native-old", True]}]},
    ],
)
async def test_log_routing_refuses_malformed_or_ambiguous_actions(
    harness: SimpleNamespace, body: dict[str, Any]
) -> None:
    source = _source("azurerm_monitor_scheduled_query_rules_alert_v2", body)
    with pytest.raises(ValueError, match="alert IaC"):
        render_alert_iac(
            harness.plan,
            harness.evidence,
            binding=_binding(
                source=source,
                resource_type="azurerm_monitor_scheduled_query_rules_alert_v2",
            ),
            source=source,
        )


@pytest.mark.parametrize(
    "body",
    [
        {"action": [{"action_group_id": "native-old"}, {"action_group_id": "native-old"}]},
        {"action": [{"action_group_id": "native-old"}, {"action_group_id": "native-new"}]},
        {"action": [{"action_group_id": True}]},
    ],
)
async def test_metric_routing_refuses_ambiguous_or_malformed_actions(
    harness: SimpleNamespace, body: dict[str, Any]
) -> None:
    source = _source("azurerm_monitor_metric_alert", body)
    with pytest.raises(ValueError, match="alert IaC"):
        render_alert_iac(
            harness.plan,
            harness.evidence,
            binding=_binding(source=source),
            source=source,
        )


@pytest.mark.parametrize("harness", ["suppression"], indirect=True)
async def test_suppression_patch_requires_inert_declared_schedule_target(
    harness: SimpleNamespace,
) -> None:
    h = harness
    assert h.source.content is not None
    binding = _binding(
        source=h.source.content,
        resource_type="azurerm_monitor_alert_processing_rule_suppression",
        target_ref="processing:example",
        field="schedule",
    )
    patch = render_alert_iac(h.plan, h.evidence, binding=binding, source=h.source.content)
    assert '"enabled": true' in patch.forward
    assert '"time_zone": "UTC"' in patch.forward

    active = h.source.content.replace('"enabled": false', '"enabled": true')
    with pytest.raises(ValueError, match="inert existing rule"):
        render_alert_iac(
            h.plan,
            h.evidence,
            binding=replace(binding, source_digest=_sha(active)),
            source=active,
        )

    with pytest.raises(ValueError, match="suppression target mismatch"):
        metric_source = _source("azurerm_monitor_metric_alert", {"enabled": False})
        render_alert_iac(
            h.plan,
            h.evidence,
            binding=replace(
                binding,
                resource_type="azurerm_monitor_metric_alert",
                source_digest=_sha(metric_source),
            ),
            source=metric_source,
        )


@pytest.mark.parametrize("harness", ["evaluation"], indirect=True)
async def test_evaluation_patch_is_bound_to_observed_metric_axis(
    harness: SimpleNamespace,
) -> None:
    h = harness
    assert h.source.content is not None
    binding = _binding(source=h.source.content, field="criteria.0.threshold")
    patch = render_alert_iac(h.plan, h.evidence, binding=binding, source=h.source.content)
    assert '"threshold": 85.0' in patch.forward

    with pytest.raises(ValueError, match="evaluation mapping"):
        render_alert_iac(
            h.plan,
            h.evidence,
            binding=replace(binding, field="window_size"),
            source=h.source.content,
        )
    with pytest.raises(ValueError, match="evaluation mapping"):
        unsupported = h.evidence.model_copy(
            update={"rules": (h.evidence.rules[0].model_copy(update={"evaluation": None}),)}
        )
        render_alert_iac(
            h.plan.model_copy(update={"evidence_digest": digest_record(unsupported)}),
            unsupported,
            binding=binding,
            source=h.source.content,
        )

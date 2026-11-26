"""Alert IaC renderer mismatch tests split to keep files small."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fdai.delivery.alert_noise_iac import render_alert_iac

from tests.core.detection.alert_noise.conftest import evidence as evidence
from tests.core.detection.alert_noise.conftest import now as now
from tests.core.detection.alert_noise.test_execution import harness as harness
from tests.delivery.test_alert_noise_iac_artifacts import _binding, _sha


async def test_renderer_rejects_mismatched_source_evidence_target_and_json(
    harness: SimpleNamespace,
) -> None:
    h = harness
    assert h.source.content is not None
    binding = _binding(
        source=h.source.content,
        group_ids={"group:old": "group:old", "group:new": "group:new"},
    )
    with pytest.raises(ValueError, match="source revision"):
        render_alert_iac(h.plan, h.evidence, binding=binding, source=h.source.content + " ")
    with pytest.raises(ValueError, match="evidence mismatch"):
        render_alert_iac(
            h.plan.model_copy(update={"evidence_digest": "sha256:" + "0" * 64}),
            h.evidence,
            binding=binding,
            source=h.source.content,
        )
    with pytest.raises(ValueError, match="target differs"):
        render_alert_iac(
            h.plan,
            h.evidence,
            binding=replace(binding, target_ref="rule:other"),
            source=h.source.content,
        )

    duplicate = (
        '{"resource":{"azurerm_monitor_metric_alert":{"example":{"action":[],"action":[]}}}}\n'
    )
    with pytest.raises(ValueError, match="duplicate IaC field"):
        render_alert_iac(
            h.plan,
            h.evidence,
            binding=replace(binding, source_digest=_sha(duplicate)),
            source=duplicate,
        )

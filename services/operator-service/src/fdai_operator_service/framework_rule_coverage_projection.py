"""Attach server-owned scoped Rule coverage to a WAF control detail, read-only.

The coverage record is a separate authority-free read model written by the framework assessment
job. It is shown only while it still belongs to Forseti's current version 2 baseline; otherwise
the detail reports why counts are unavailable instead of showing outdated numbers. The browser
never derives coverage, satisfaction, or activation from these counts.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from fdai_service_contracts.baseline_evaluation import BaselineEvaluationCoverage
from fdai_service_contracts.framework_rule_coverage import (
    FRAMEWORK_RULE_COVERAGE_LATEST_KEY,
    ScopedRuleCoverageIdentityError,
    ScopedRuleCoverageRecord,
    ScopedRuleCoverageRule,
    verify_scoped_rule_coverage_identity,
)
from pydantic import ValidationError
from starlette.exceptions import HTTPException

BASELINE_EVALUATION_LATEST_COVERAGE_KEY = "baseline-evaluation:latest:coverage"


def _has_rule_requirement(control: Mapping[str, object]) -> bool:
    requirements = control.get("requirements")
    return isinstance(requirements, list) and any(
        isinstance(item, dict) and item.get("kind") == "rule" for item in requirements
    )


async def attach_rule_coverage(
    control: Mapping[str, object],
    reader: object,
) -> tuple[dict[str, object], str | None]:
    """Return the control with ``rule_coverage`` and per-requirement ``coverage`` attached.

    The second value is the revision material of the coverage read, or ``None`` when nothing was
    attached. A malformed stored record raises ``HTTPException(503)`` instead of reading as zero.
    """

    read_state = getattr(reader, "read_state", None)
    if not callable(read_state) or not _has_rule_requirement(control):
        return dict(control), None
    raw_record = await read_state(FRAMEWORK_RULE_COVERAGE_LATEST_KEY)
    if raw_record is None:
        return _with_status(control, {"status": "unavailable", "reason": "no_record"})
    record = _validated(ScopedRuleCoverageRecord, raw_record, "scoped Rule coverage")
    raw_baseline = await read_state(BASELINE_EVALUATION_LATEST_COVERAGE_KEY)
    if raw_baseline is None:
        return _with_status(control, _summary(record, status="stale", reason="no_baseline"))
    baseline = _validated(BaselineEvaluationCoverage, raw_baseline, "baseline coverage")
    try:
        verify_scoped_rule_coverage_identity(record, baseline=baseline)
    except ScopedRuleCoverageIdentityError:
        return _with_status(control, _summary(record, status="stale", reason="baseline_changed"))
    summary = _summary(record, status="current", reason=None)
    summary["matches_assessment_scope"] = control.get("evaluation_scope") == record.scope_digest
    attached, _ = _with_status(control, summary)
    requirements = attached.get("requirements")
    if isinstance(requirements, list):
        attached["requirements"] = [
            _requirement_with_coverage(item, record) if isinstance(item, dict) else item
            for item in requirements
        ]
    return attached, _revision(summary)


def _requirement_with_coverage(
    requirement: Mapping[str, object],
    record: ScopedRuleCoverageRecord,
) -> dict[str, object]:
    updated = dict(requirement)
    if requirement.get("kind") != "rule":
        return updated
    rule_id = requirement.get("ref")
    rule = record.rule(rule_id) if isinstance(rule_id, str) else None
    updated["coverage"] = _rule_counts(rule)
    return updated


def _rule_counts(rule: ScopedRuleCoverageRule | None) -> dict[str, object]:
    if rule is None or rule.member_rule_digest is None:
        return {"activated": False}
    return {
        "activated": True,
        "eligible": rule.eligible_count,
        "covered": rule.covered_count,
        "compliant": rule.compliant_count,
        "violated": rule.violated_count,
        "held_for_review": rule.abstained_count,
        "missing": rule.missing_count,
        "duplicate": rule.duplicate_count,
        "conflicting": rule.conflicting_count,
        "unexpected": rule.unexpected_count,
        "revision_mismatch": rule.revision_mismatch_count,
    }


def _summary(
    record: ScopedRuleCoverageRecord,
    *,
    status: str,
    reason: str | None,
) -> dict[str, object]:
    return {
        "status": status,
        "reason": reason,
        "framework_id": record.framework_id,
        "scope_digest": record.scope_digest,
        "resource_count": len(record.resources),
        "inventory_generation": record.inventory_generation,
        "inventory_observed_at": record.inventory_observed_at.isoformat(),
        "recorded_at": record.recorded_at.isoformat(),
        "rule_activation_generation_id": record.rule_activation_generation_id,
        "record_digest": record.record_digest,
        "execution_authority": False,
    }


def _with_status(
    control: Mapping[str, object],
    summary: dict[str, object],
) -> tuple[dict[str, object], str]:
    attached = dict(control)
    attached["rule_coverage"] = summary
    return attached, _revision(summary)


def _revision(summary: Mapping[str, object]) -> str:
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validated[T: (ScopedRuleCoverageRecord, BaselineEvaluationCoverage)](
    model: type[T],
    value: Mapping[str, object],
    label: str,
) -> T:
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise HTTPException(status_code=503, detail=f"{label} record is malformed") from exc


__all__ = ["attach_rule_coverage"]

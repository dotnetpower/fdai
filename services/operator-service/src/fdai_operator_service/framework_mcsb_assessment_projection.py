"""Join the MCSB shadow assessment projection onto the MCSB catalog read.

The MCSB catalog (``mcsb.list``) describes benchmark controls and their crosswalk coverage. The
``azure-mcsb`` shadow assessment lives in its own projection (``mcsb-assessment.list``), which the
framework assessment consumer updates. This join adds each v1 control's assessed state without
letting the browser compute status, and never grants execution authority.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from typing import Final

from starlette.exceptions import HTTPException

MCSB_ASSESSMENT_PROJECTION_KEY: Final = "operator-projection:workflow:mcsb-assessment.list"
MCSB_ASSESSMENT_FRAMEWORK_ID: Final = "azure-mcsb"
_ASSESSED_VERSION: Final = "v1"
_CONTROL_FIELDS: Final = (
    "applicability",
    "evaluation_status",
    "satisfaction",
    "evaluated_at",
    "evidence_complete",
    "limitations",
)


async def attach_mcsb_assessment(
    payload: Mapping[str, object],
    reader: object,
    *,
    detail: bool,
) -> tuple[dict[str, object], str | None]:
    """Return the MCSB payload with ``assessment`` attached, plus the assessment revision.

    A missing projection reads as ``unavailable``; a malformed one raises ``HTTPException(503)``
    instead of reading as unknown. Only v1 controls are assessed.
    """

    attached = dict(payload)
    version = _payload_version(attached, detail=detail)
    read_state = getattr(reader, "read_state", None)
    if version != _ASSESSED_VERSION:
        return _without_assessment(attached, detail=detail, status="not_assessed")
    stored = await read_state(MCSB_ASSESSMENT_PROJECTION_KEY) if callable(read_state) else None
    if stored is None:
        return _without_assessment(attached, detail=detail, status="unavailable")
    if not isinstance(stored, Mapping) or stored.get("framework_id") != (
        MCSB_ASSESSMENT_FRAMEWORK_ID
    ):
        raise HTTPException(status_code=503, detail="MCSB assessment projection is malformed")
    revision = stored.get("_revision")
    controls_value = stored.get("controls")
    if not isinstance(revision, str) or not revision or not isinstance(controls_value, list):
        raise HTTPException(status_code=503, detail="MCSB assessment projection is malformed")
    by_id: dict[str, Mapping[str, object]] = {}
    for item in controls_value:
        control_id = item.get("control_id") if isinstance(item, Mapping) else None
        if not isinstance(control_id, str) or control_id in by_id:
            raise HTTPException(status_code=503, detail="MCSB assessment projection is malformed")
        if item.get("execution_authority") is not False:
            raise HTTPException(status_code=503, detail="MCSB assessment projection is malformed")
        by_id[control_id] = item
    evaluated = stored.get("evaluation_source") == "framework-shadow-assessment"
    summary: dict[str, object] = {
        "status": "evaluated" if evaluated else "not_evaluated",
        "framework_id": MCSB_ASSESSMENT_FRAMEWORK_ID,
        "framework_version": stored.get("framework_version"),
        "catalog_digest": stored.get("catalog_digest"),
        "last_evaluated_at": stored.get("last_evaluated_at"),
        "satisfaction_counts": dict(
            sorted(Counter(str(item.get("satisfaction")) for item in by_id.values()).items())
        ),
        "execution_authority": False,
    }
    if detail:
        control_id = attached.get("control_id")
        source = by_id.get(control_id) if isinstance(control_id, str) else None
        attached["assessment"] = _control_assessment(source, detail=True)
    else:
        controls = attached.get("controls")
        if isinstance(controls, list):
            attached["controls"] = [
                {
                    **item,
                    "assessment": _control_assessment(
                        by_id.get(str(item.get("control_id"))), detail=False
                    ),
                }
                if isinstance(item, dict)
                else item
                for item in controls
            ]
    attached["assessment_summary"] = summary
    return attached, _revision(revision)


def _payload_version(payload: Mapping[str, object], *, detail: bool) -> str | None:
    if detail:
        value = payload.get("benchmark_version")
        return value if isinstance(value, str) else None
    benchmark = payload.get("benchmark")
    value = benchmark.get("benchmark_version") if isinstance(benchmark, Mapping) else None
    return value if isinstance(value, str) else None


def _without_assessment(
    payload: dict[str, object],
    *,
    detail: bool,
    status: str,
) -> tuple[dict[str, object], str | None]:
    if detail:
        payload["assessment"] = None
    else:
        controls = payload.get("controls")
        if isinstance(controls, list):
            payload["controls"] = [
                {**item, "assessment": None} if isinstance(item, dict) else item
                for item in controls
            ]
    payload["assessment_summary"] = {
        "status": status,
        "framework_id": MCSB_ASSESSMENT_FRAMEWORK_ID,
        "execution_authority": False,
    }
    return payload, None


def _control_assessment(
    source: Mapping[str, object] | None,
    *,
    detail: bool,
) -> dict[str, object] | None:
    if source is None:
        return None
    value: dict[str, object] = {field: source.get(field) for field in _CONTROL_FIELDS}
    if detail:
        requirements = source.get("requirements")
        specifications = source.get("evidence_specifications")
        value["requirements"] = (
            requirements
            if isinstance(requirements, list)
            else [
                {
                    "kind": item.get("kind"),
                    "ref": item.get("source_ref"),
                    "evidence_role": item.get("evidence_role"),
                    "status": "unknown",
                    "evidence_refs": [],
                    "limitations": ["not_evaluated"],
                }
                for item in specifications
                if isinstance(item, Mapping)
            ]
            if isinstance(specifications, list)
            else []
        )
    return value


def _revision(value: str) -> str:
    return hashlib.sha256(
        json.dumps({"mcsb_assessment": value}, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "MCSB_ASSESSMENT_FRAMEWORK_ID",
    "MCSB_ASSESSMENT_PROJECTION_KEY",
    "attach_mcsb_assessment",
]

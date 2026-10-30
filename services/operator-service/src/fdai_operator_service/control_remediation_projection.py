"""Read-only links from exact Rule evidence to governed action candidates."""

import hashlib
import json
from collections.abc import Mapping


def control_remediation(
    detail: Mapping[str, object],
    rule_catalog: Mapping[str, object] | None,
) -> dict[str, object]:
    rule_ids = _rule_ids(detail)
    if not rule_ids:
        return {
            "status": "manual_guidance",
            "candidates": [],
            "limitations": ["manual_or_process_evidence_required"],
            "execution_authority": False,
        }
    details = rule_catalog.get("details") if rule_catalog is not None else None
    revision = rule_catalog.get("_revision") if rule_catalog is not None else None
    if not isinstance(details, Mapping) or not isinstance(revision, str) or not revision:
        return {
            "status": "unavailable",
            "candidates": [],
            "limitations": ["authoritative_rule_details_unavailable"],
            "execution_authority": False,
        }
    candidates: list[dict[str, str]] = []
    limitations = {"rule_activation_runtime_support_and_safety_gates_required"}
    for rule_id in rule_ids:
        rule = details.get(f"active:{rule_id}")
        if (
            not isinstance(rule, Mapping)
            or rule.get("id") != rule_id
            or rule.get("origin") != "active"
        ):
            limitations.add("rule_not_in_active_catalog")
            continue
        versions = detail.get("rule_versions")
        if isinstance(versions, Mapping) and rule_id in versions:
            if rule.get("version") != versions[rule_id]:
                limitations.add("rule_revision_drift")
                continue
        action_type = rule.get("remediates")
        if not isinstance(action_type, str) or not action_type.strip():
            limitations.add("rule_has_no_reviewed_action_binding")
            continue
        candidates.append({"rule_id": rule_id, "action_type_ref": action_type})
    return {
        "status": "governed_candidates" if candidates else "unavailable",
        "candidates": candidates,
        "limitations": sorted(limitations),
        "execution_authority": False,
    }


def control_detail_revision(
    catalog_revision: str, detail: Mapping[str, object], rule_revision: str | None
) -> str:
    guidance = detail.get("guidance")
    material = {
        "catalog_revision": catalog_revision,
        "guidance_digest": (
            guidance.get("content_digest") if isinstance(guidance, Mapping) else None
        ),
        "remediation": detail.get("remediation"),
        "rule_catalog_revision": rule_revision,
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _rule_ids(detail: Mapping[str, object]) -> tuple[str, ...]:
    identifiers: set[str] = set()
    raw_ids = detail.get("rule_ids")
    if isinstance(raw_ids, (list, tuple)):
        identifiers.update(item for item in raw_ids if isinstance(item, str) and item)
    requirements = detail.get("requirements")
    if isinstance(requirements, (list, tuple)):
        for requirement in requirements:
            if isinstance(requirement, Mapping) and requirement.get("kind") == "rule":
                reference = requirement.get("ref")
                if isinstance(reference, str) and reference:
                    identifiers.add(reference)
    return tuple(sorted(identifiers))

"""Trusted policy for protected deployment decision-evidence admission."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class DecisionEvidencePolicyError(ValueError):
    """The trusted decision-evidence policy is missing or malformed."""


@dataclass(frozen=True, slots=True)
class DeploymentDecisionEvidencePolicy:
    """Reviewed static trust inputs for one protected deployment evidence class."""

    source_workflow_path: str
    source_identity_prefix: str
    authority_class: str
    purpose_id: str
    producer_id: str
    producer_version: str
    method_id: str
    method_version: str
    freshness_policy_id: str
    freshness_policy_version: str
    freshness_ceiling_seconds: int
    verifier_id: str
    verifier_version: str
    trust_anchor_id: str

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> DeploymentDecisionEvidencePolicy:
        """Validate one exact policy mapping without ignoring unknown fields."""

        expected = {
            "schema_version",
            "source_workflow_path",
            "source_identity_prefix",
            "authority_class",
            "purpose_id",
            "producer_id",
            "producer_version",
            "method_id",
            "method_version",
            "freshness_policy_id",
            "freshness_policy_version",
            "freshness_ceiling_seconds",
            "verifier_id",
            "verifier_version",
            "trust_anchor_id",
        }
        if set(raw) != expected or raw.get("schema_version") != "1.0.0":
            raise DecisionEvidencePolicyError(
                "decision evidence deployment policy shape is invalid"
            )
        values = {
            field: _text(raw, field)
            for field in expected
            - {
                "schema_version",
                "freshness_ceiling_seconds",
            }
        }
        ceiling = raw.get("freshness_ceiling_seconds")
        if type(ceiling) is not int or not 60 <= ceiling <= 86400:
            raise DecisionEvidencePolicyError(
                "decision evidence freshness ceiling MUST be in [60, 86400]"
            )
        for field in (
            "authority_class",
            "purpose_id",
            "producer_id",
            "method_id",
            "freshness_policy_id",
            "verifier_id",
        ):
            if _IDENTIFIER.fullmatch(values[field]) is None:
                raise DecisionEvidencePolicyError(f"decision evidence policy {field} is invalid")
        for field in (
            "producer_version",
            "method_version",
            "freshness_policy_version",
            "verifier_version",
        ):
            if _SEMVER.fullmatch(values[field]) is None:
                raise DecisionEvidencePolicyError(f"decision evidence policy {field} is invalid")
        workflow = values["source_workflow_path"]
        if (
            not workflow.startswith(".github/workflows/")
            or not workflow.endswith(".yml")
            or ".." in workflow
            or "\\" in workflow
        ):
            raise DecisionEvidencePolicyError("decision evidence source workflow path is invalid")
        return cls(
            source_workflow_path=workflow,
            source_identity_prefix=values["source_identity_prefix"],
            authority_class=values["authority_class"],
            purpose_id=values["purpose_id"],
            producer_id=values["producer_id"],
            producer_version=values["producer_version"],
            method_id=values["method_id"],
            method_version=values["method_version"],
            freshness_policy_id=values["freshness_policy_id"],
            freshness_policy_version=values["freshness_policy_version"],
            freshness_ceiling_seconds=ceiling,
            verifier_id=values["verifier_id"],
            verifier_version=values["verifier_version"],
            trust_anchor_id=values["trust_anchor_id"],
        )


def load_deployment_decision_evidence_policy(
    path: Path,
) -> DeploymentDecisionEvidencePolicy:
    """Load a bounded regular JSON policy file from the reviewed checkout."""

    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise DecisionEvidencePolicyError(
            "decision evidence deployment policy MUST be a bounded regular file"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecisionEvidencePolicyError(
            "decision evidence deployment policy is invalid JSON"
        ) from exc
    if not isinstance(raw, dict):
        raise DecisionEvidencePolicyError("decision evidence deployment policy MUST be an object")
    return DeploymentDecisionEvidencePolicy.from_mapping(raw)


def deployment_freshness_policy_digest(
    policy: DeploymentDecisionEvidencePolicy,
) -> str:
    """Return the canonical freshness policy digest used by trusted requirements."""

    return content_digest(
        {
            "freshness_ceiling_seconds": policy.freshness_ceiling_seconds,
            "policy_id": policy.freshness_policy_id,
            "policy_version": policy.freshness_policy_version,
        }
    )


def _text(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise DecisionEvidencePolicyError(
            f"decision evidence policy {field} MUST be bounded non-empty text"
        )
    return value


__all__ = [
    "DecisionEvidencePolicyError",
    "DeploymentDecisionEvidencePolicy",
    "deployment_freshness_policy_digest",
    "load_deployment_decision_evidence_policy",
]

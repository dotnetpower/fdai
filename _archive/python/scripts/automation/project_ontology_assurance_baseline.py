"""Project one passing live ontology assurance artifact into repository-safe evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.automation.run_ontology_assurance import full_artifact_accepted


class BaselineProjectionError(ValueError):
    """The source artifact cannot support a governed repository baseline."""


def _digest_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _required_text(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise BaselineProjectionError(f"source artifact {key} MUST be non-empty text")
    return value


def project_repository_safe_baseline(
    payload: Mapping[str, Any],
    *,
    source_artifact_digest: str,
) -> dict[str, Any]:
    """Return exact-identity evidence without retaining environment UUIDs or raw payloads."""
    source_revision = _required_text(payload, "source_revision")
    if not full_artifact_accepted(payload, source_revision):
        raise BaselineProjectionError("source artifact does not pass the full assurance gate")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 100:
        raise BaselineProjectionError("source artifact MUST retain exactly 100 results")

    projected_results: list[dict[str, Any]] = []
    for raw in results:
        if not isinstance(raw, Mapping):
            raise BaselineProjectionError("source artifact results MUST be objects")
        request_id = _required_text(raw, "request_id")
        projection_id = _required_text(raw, "projection_id")
        projected_results.append(
            {
                key: raw[key]
                for key in (
                    "question_id",
                    "locale",
                    "operation",
                    "disposition",
                    "reason_code",
                    "semantic_route",
                    "ontology_release_digest",
                    "principal_manifest_digest",
                    "plan_digest",
                    "execution_receipt_digest",
                    "checks_completed",
                    "checks_total",
                    "evidence_ref_count",
                    "plan_capabilities",
                    "plan_capability_match",
                    "unauthorized_execution_claim",
                )
                if key in raw
            }
            | {
                "request_id_digest": _digest_text(request_id),
                "projection_id_digest": _digest_text(projection_id),
            }
        )

    return {
        "schema_version": "1.0.0",
        "evidence_type": "repository_safe_bilingual_ontology_query_assurance",
        "source_artifact_digest": source_artifact_digest,
        "source_revision": source_revision,
        "configuration_digest": _required_text(payload, "configuration_digest"),
        "workspace_patch_digest": _required_text(payload, "workspace_patch_digest"),
        "evidence_identity_digest": _required_text(payload, "evidence_identity_digest"),
        "receipt_source": payload["receipt_source"],
        "run_scope": payload["run_scope"],
        "run_mode": payload["run_mode"],
        "started_at": payload["started_at"],
        "completed_at": payload["completed_at"],
        "authentication": payload["authentication"],
        "authentication_attestation": payload["authentication_attestation"],
        "run_configuration": payload["run_configuration"],
        "transport_evidence": payload["transport_evidence"],
        "passed": payload["passed"],
        "production_ready": payload["production_ready"],
        "summary": payload["summary"],
        "results": projected_results,
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    source_bytes = args.source.read_bytes()
    payload = json.loads(source_bytes)
    if not isinstance(payload, dict):
        raise BaselineProjectionError("source artifact root MUST be an object")
    baseline = project_repository_safe_baseline(
        payload,
        source_artifact_digest=f"sha256:{hashlib.sha256(source_bytes).hexdigest()}",
    )
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

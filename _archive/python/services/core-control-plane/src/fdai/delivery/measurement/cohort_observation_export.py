"""Customer-agnostic per-arm cohort observation batch exporter and CLI.

Compiles normalized SRE metric and guard observations into a canonical,
content-sealed ``CohortObservationBatch`` artifact without importer-owned trust
fields (``arm``, ``fdai_revision``, ``protocol``, ``origin``, ``admission``,
``source_id``, or ``authority``). The protected importer supplies those values
independently at import time.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai.core.measurement.cohort_claim_policy import (
    COHORT_CLAIM_POLICY_PATH,
    REQUIRED_SUCCESS_METRIC_IDS,
    ZERO_THRESHOLD_GUARD_IDS,
    CohortClaimPolicy,
    load_cohort_claim_policy,
)
from fdai.delivery.measurement.cohort_observation_import import (
    MAX_COHORT_OBSERVATION_BATCH_BYTES,
    MAX_COHORT_OBSERVATIONS,
    CohortObservationBatch,
    NormalizedCohortGuardObservation,
    NormalizedCohortMetricObservation,
    NormalizedCohortObservation,
    cohort_observation_batch_digest,
    load_cohort_observation_batch,
)

_FORBIDDEN_EXPORTER_TRUST_KEYS = frozenset(
    {
        "admission",
        "admissions",
        "admitted_receipt_digests",
        "arm",
        "artifact_origin",
        "authority",
        "claim_eligible",
        "claim_eligibility_authority",
        "execution_authority",
        "fdai_revision",
        "import_origin",
        "measurement_protocol_digest",
        "measurement_protocol_version",
        "origin",
        "policy",
        "protocol",
        "requirement",
        "revision",
        "source_artifact_name",
        "source_binding_id",
        "source_id",
        "source_run_attempt",
        "source_run_id",
        "source_workflow_path",
        "verification_bundles",
    }
)


class CohortObservationExportError(ValueError):
    """Raised when raw exporter inputs contain trust fields, unknown measures, or invalid bounds."""


@dataclass(frozen=True, slots=True)
class CohortObservationExportReceipt:
    """Summary receipt returned after writing and verifying a sealed observation batch."""

    output_path: str
    batch_digest: str
    observation_count: int
    metric_count: int
    guard_count: int
    distinct_metric_ids: tuple[str, ...]
    distinct_guard_ids: tuple[str, ...]
    execution_authority: bool = False
    claim_eligibility_authority: bool = False

    def to_mapping(self) -> dict[str, object]:
        return {
            "output_path": self.output_path,
            "batch_digest": self.batch_digest,
            "observation_count": self.observation_count,
            "metric_count": self.metric_count,
            "guard_count": self.guard_count,
            "distinct_metric_ids": list(self.distinct_metric_ids),
            "distinct_guard_ids": list(self.distinct_guard_ids),
            "execution_authority": False,
            "claim_eligibility_authority": False,
        }

    def protocol_summary(self) -> dict[str, object]:
        return {
            "batch_digest": self.batch_digest,
            "observation_count": self.observation_count,
            "metric_count": self.metric_count,
            "guard_count": self.guard_count,
            "has_all_required_metrics": len(self.distinct_metric_ids)
            == len(REQUIRED_SUCCESS_METRIC_IDS),
            "has_all_required_guards": len(self.distinct_guard_ids)
            == len(ZERO_THRESHOLD_GUARD_IDS),
        }


def build_cohort_observation_batch(
    records: Iterable[Mapping[str, Any] | NormalizedCohortObservation],
    *,
    policy: CohortClaimPolicy | None = None,
) -> CohortObservationBatch:
    """Validate, canonicalize, and content-seal a normalized cohort observation batch."""
    allowed_metrics = (
        frozenset(policy.required_metric_ids)
        if policy is not None
        else frozenset(REQUIRED_SUCCESS_METRIC_IDS)
    )
    allowed_guards = (
        frozenset(policy.required_guard_ids)
        if policy is not None
        else frozenset(ZERO_THRESHOLD_GUARD_IDS)
    )

    normalized: list[NormalizedCohortObservation] = []
    for raw in records:
        if isinstance(raw, (NormalizedCohortMetricObservation, NormalizedCohortGuardObservation)):
            item: NormalizedCohortObservation = raw
        elif isinstance(raw, Mapping):
            forbidden = _FORBIDDEN_EXPORTER_TRUST_KEYS & {str(k) for k in raw}
            if forbidden:
                joined = ", ".join(sorted(forbidden))
                raise CohortObservationExportError(
                    f"exporter input MUST NOT declare importer-owned trust fields: {joined}"
                )
            kind = raw.get("kind")
            try:
                if kind == "metric":
                    item = NormalizedCohortMetricObservation.model_validate(dict(raw))
                elif kind == "guard":
                    item = NormalizedCohortGuardObservation.model_validate(dict(raw))
                else:
                    raise CohortObservationExportError(
                        "observation kind MUST be 'metric' or 'guard'"
                    )
            except ValueError as exc:
                raise CohortObservationExportError(str(exc)) from exc
        else:
            raise CohortObservationExportError("observation item MUST be a mapping or observation")

        if isinstance(item, NormalizedCohortMetricObservation):
            if item.metric_id not in allowed_metrics:
                raise CohortObservationExportError(
                    f"metric_id {item.metric_id!r} is not in the governed cohort policy"
                )
        elif item.guard_id not in allowed_guards:
            raise CohortObservationExportError(
                f"guard_id {item.guard_id!r} is not in the governed cohort policy"
            )
        normalized.append(item)

    if not normalized:
        raise CohortObservationExportError("cohort observation export requires at least one item")
    if len(normalized) > MAX_COHORT_OBSERVATIONS:
        raise CohortObservationExportError(
            f"cohort observation export exceeds {MAX_COHORT_OBSERVATIONS} observations"
        )

    ordered = tuple(sorted(normalized, key=_canonical_sort_key))
    seen_keys: set[tuple[str, str, str]] = set()
    for obs in ordered:
        key = _canonical_sort_key(obs)
        if key in seen_keys:
            raise CohortObservationExportError(
                f"duplicate observation for ({key[0]}, {key[1]}, {key[2]})"
            )
        seen_keys.add(key)

    serialized_obs = [obs.model_dump(mode="json") for obs in ordered]
    digest = cohort_observation_batch_digest(
        schema_version="1.0.0",
        observations=serialized_obs,
    )
    return CohortObservationBatch.model_validate(
        {
            "schema_version": "1.0.0",
            "observations": serialized_obs,
            "batch_digest": digest,
        }
    )


def export_cohort_observation_batch(
    *,
    input_path: Path,
    output_path: Path,
    policy_path: Path | None = None,
) -> CohortObservationExportReceipt:
    """Read raw observations from ``input_path`` and write a sealed batch to ``output_path``."""
    if input_path.is_symlink() or not input_path.is_file():
        raise CohortObservationExportError("exporter input path MUST be a regular file")
    if output_path.exists() and output_path.is_symlink():
        raise CohortObservationExportError("exporter output path MUST NOT be a symlink")
    raw_bytes = input_path.read_bytes()
    if len(raw_bytes) > MAX_COHORT_OBSERVATION_BATCH_BYTES:
        raise CohortObservationExportError("exporter input exceeds 8 MiB ceiling")
    try:
        parsed = json.loads(raw_bytes.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CohortObservationExportError(f"invalid exporter JSON input: {exc}") from exc

    if isinstance(parsed, Mapping):
        forbidden = _FORBIDDEN_EXPORTER_TRUST_KEYS & {str(k) for k in parsed}
        if forbidden:
            joined = ", ".join(sorted(forbidden))
            raise CohortObservationExportError(
                f"exporter bundle MUST NOT declare importer-owned trust fields: {joined}"
            )
        raw_observations = parsed.get("observations")
    elif isinstance(parsed, list):
        raw_observations = parsed
    else:
        raise CohortObservationExportError(
            "exporter input MUST be a JSON array or an object with an 'observations' array"
        )
    if not isinstance(raw_observations, list):
        raise CohortObservationExportError("exporter 'observations' field MUST be a JSON list")

    policy = load_cohort_claim_policy(policy_path) if policy_path is not None else None
    batch = build_cohort_observation_batch(raw_observations, policy=policy)
    payload_text = (
        json.dumps(
            batch.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    encoded = payload_text.encode("utf-8")
    if len(encoded) > MAX_COHORT_OBSERVATION_BATCH_BYTES:
        raise CohortObservationExportError("rendered cohort observation batch exceeds 8 MiB limit")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f".{output_path.name}.tmp")
    tmp_path.write_bytes(encoded)
    tmp_path.replace(output_path)
    verified = load_cohort_observation_batch(output_path)

    metrics = sorted(
        {
            item.metric_id
            for item in verified.observations
            if isinstance(item, NormalizedCohortMetricObservation)
        }
    )
    guards = sorted(
        {
            item.guard_id
            for item in verified.observations
            if isinstance(item, NormalizedCohortGuardObservation)
        }
    )
    metric_count = sum(
        isinstance(item, NormalizedCohortMetricObservation) for item in verified.observations
    )
    guard_count = sum(
        isinstance(item, NormalizedCohortGuardObservation) for item in verified.observations
    )
    return CohortObservationExportReceipt(
        output_path=str(output_path),
        batch_digest=verified.batch_digest,
        observation_count=len(verified.observations),
        metric_count=metric_count,
        guard_count=guard_count,
        distinct_metric_ids=tuple(metrics),
        distinct_guard_ids=tuple(guards),
    )


def _canonical_sort_key(observation: NormalizedCohortObservation) -> tuple[str, str, str]:
    measure_id = (
        observation.metric_id
        if isinstance(observation, NormalizedCohortMetricObservation)
        else observation.guard_id
    )
    return observation.kind, measure_id, observation.source_cluster_digest


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"exporter input repeats JSON key: {key}")
        result[key] = value
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Raw JSON observations path")
    parser.add_argument("--output", type=Path, required=True, help="Sealed batch output JSON path")
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path(COHORT_CLAIM_POLICY_PATH),
        help="Path to trusted SRE cohort claim policy JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for customer-agnostic cohort observation batch export."""
    args = _parser().parse_args(argv)
    policy_path = args.policy if args.policy and args.policy.is_file() else None
    receipt = export_cohort_observation_batch(
        input_path=args.input,
        output_path=args.output,
        policy_path=policy_path,
    )
    print(json.dumps(receipt.to_mapping(), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Trusted repository policy for the governed SRE operational cohort claim.

The policy is a versioned repository artifact loaded independently of any
cohort evidence. It pins the required success metrics, every zero-threshold
guard, a prospective operational measurement protocol, the benchmark revision
used for separate regression checks, and the minimum retained sample size. The
only value a caller supplies is the expected pinned revision, because that is
the one fact the repository cannot know in advance, and it MUST be an immutable
full commit digest rather than a movable branch or tag name.

Evidence never contributes to this policy, so a cohort artifact cannot weaken
the expectation it is measured against.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_service_contracts.baseline_cohort import (
    MINIMUM_COHORT_SAMPLE_SIZE,
    CohortClaimRequirement,
)
from fdai_service_contracts.ontology_query import content_digest

#: Repository-relative location of the trusted cohort claim policy.
COHORT_CLAIM_POLICY_PATH = "config/sre-cohort-claim-policy.json"

#: The only policy schema this loader accepts.
COHORT_CLAIM_POLICY_SCHEMA_VERSION = "1.0.0"

#: The expected revision MUST be the same immutable full commit digest
#: operational promotion requires, so a movable branch or tag name such as
#: `main` can never pin a published cohort claim.
_COMMIT_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_WORKFLOW_PATH = re.compile(r"^\.github/workflows/[a-z0-9][a-z0-9-]{0,99}\.yml$")
_SOURCE_BINDING_ID = re.compile(r"^[a-z][a-z0-9.-]{2,63}$")

#: Success metrics from `docs/roadmap/architecture/goals-and-metrics.md` that a
#: published cohort claim MUST report as an absolute value with an interval.
REQUIRED_SUCCESS_METRIC_IDS: tuple[str, ...] = (
    "auto_resolution_rate",
    "change_lead_time_seconds",
    "cost_per_unit_usd",
    "human_touchpoints_per_100_events",
    "mttr_seconds",
)

#: The four guards whose threshold is exactly zero in the same document.
ZERO_THRESHOLD_GUARD_IDS: tuple[str, ...] = (
    "policy_violation_escape_rate",
    "unauthorized_execution_rate",
    "unverified_success_claim_rate",
    "wrong_target_or_stale_revision_execution_rate",
)

REQUIRED_INTERVAL_METHODS: Mapping[str, str] = {
    "auto_resolution_rate": "wilson_95",
    "change_lead_time_seconds": "deterministic_bootstrap_95",
    "cost_per_unit_usd": "deterministic_bootstrap_95",
    "human_touchpoints_per_100_events": "deterministic_bootstrap_95",
    "mttr_seconds": "deterministic_bootstrap_95",
}


class CohortClaimPolicyError(ValueError):
    """Raised when the trusted cohort claim policy is absent or weakened."""


@dataclass(frozen=True, slots=True)
class CohortExporterMeasureBinding:
    """Measures one trusted exporter workflow may contribute to one arm."""

    source_id: str
    workflow_path: str
    metric_ids: tuple[str, ...]
    guard_ids: tuple[str, ...]

    def allows_metric(self, metric_id: str) -> bool:
        """Return whether this workflow owns one metric in its cohort arm."""

        return metric_id in self.metric_ids

    def allows_guard(self, guard_id: str) -> bool:
        """Return whether this workflow owns one guard in its cohort arm."""

        return guard_id in self.guard_ids


@dataclass(frozen=True, slots=True)
class CohortClaimPolicy:
    """One loaded, floor-checked cohort claim policy revision."""

    policy_id: str
    policy_version: str
    benchmark_scenario_set_version: str
    benchmark_scenario_set_digest: str
    measurement_basis_kind: str
    measurement_protocol_version: str
    measurement_protocol_digest: str
    maximum_window_seconds: int
    interval_methods: tuple[tuple[str, str], ...]
    allowed_exporter_workflow_paths: tuple[tuple[str, tuple[str, ...]], ...]
    exporter_measure_bindings: tuple[tuple[str, tuple[CohortExporterMeasureBinding, ...]], ...]
    minimum_sample_size: int
    required_metric_ids: tuple[str, ...]
    required_guard_ids: tuple[str, ...]
    freshness_policy_digest: str
    freshness_ceiling_seconds: int
    allowed_authority_classes: tuple[str, ...]
    allowed_source_identities: tuple[str, ...]
    purpose_id: str
    producer_id: str
    producer_version: str
    method_id: str
    method_version: str
    minimum_completeness_basis_points: int

    def verify_scenario_set(self, root: Path) -> None:
        """Verify the separate synthetic benchmark used for regression checks."""

        actual = frozen_scenario_set_digest(root)
        if actual != self.benchmark_scenario_set_digest:
            raise CohortClaimPolicyError(
                "cohort claim policy does not pin the actual benchmark scenario-set digest"
            )

    def requirement(self, *, expected_revision: str) -> CohortClaimRequirement:
        """Build the evaluated requirement from this policy and one trusted revision."""

        require_commit_revision(expected_revision)
        evidence = {
            "allowed_authority_classes": self.allowed_authority_classes,
            "allowed_source_identities": self.allowed_source_identities,
            "scope_digest": self.measurement_protocol_digest,
            "purpose_id": self.purpose_id,
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "method_id": self.method_id,
            "method_version": self.method_version,
            "source_revision": expected_revision,
            "freshness_policy_digest": self.freshness_policy_digest,
            "freshness_ceiling_seconds": self.freshness_ceiling_seconds,
            "minimum_completeness_basis_points": self.minimum_completeness_basis_points,
        }
        try:
            return CohortClaimRequirement.model_validate(
                {
                    "policy_id": self.policy_id,
                    "policy_version": self.policy_version,
                    "measurement_basis_kind": self.measurement_basis_kind,
                    "measurement_protocol_version": self.measurement_protocol_version,
                    "measurement_protocol_digest": self.measurement_protocol_digest,
                    "fdai_revision": expected_revision,
                    "minimum_sample_size": self.minimum_sample_size,
                    "required_metric_ids": self.required_metric_ids,
                    "required_guard_ids": self.required_guard_ids,
                    "baseline_evidence": evidence,
                    "treatment_evidence": evidence,
                }
            )
        except ValueError as error:
            raise CohortClaimPolicyError(
                f"cohort claim policy cannot pin the expected revision: {error}"
            ) from error

    def allowed_exporters(self, arm: str) -> tuple[str, ...]:
        """Return reviewed exporter workflows for one cohort arm."""

        exporters = dict(self.allowed_exporter_workflow_paths)
        try:
            return exporters[arm]
        except KeyError as error:
            raise CohortClaimPolicyError(f"unknown cohort arm: {arm}") from error

    def exporter_binding(self, arm: str, workflow_path: str) -> CohortExporterMeasureBinding:
        """Return the trusted measure ownership for one arm and workflow."""

        bindings = dict(self.exporter_measure_bindings)
        try:
            arm_bindings = bindings[arm]
        except KeyError as error:
            raise CohortClaimPolicyError(f"unknown cohort arm: {arm}") from error
        for binding in arm_bindings:
            if binding.workflow_path == workflow_path:
                return binding
        raise CohortClaimPolicyError(
            f"cohort {arm} source workflow has no measure binding: {workflow_path}"
        )


def require_commit_revision(value: str) -> str:
    """Return one immutable full commit digest, or fail closed.

    A branch or tag name such as `main` moves, so it can never identify the
    code a published claim was measured on.
    """

    if not isinstance(value, str) or _COMMIT_REVISION.fullmatch(value) is None:
        raise CohortClaimPolicyError(
            "cohort claim revision MUST be an immutable full 40- or 64-hex commit digest"
        )
    return value


def frozen_scenario_set_digest(root: Path) -> str:
    """Return the canonical content digest of one frozen scenario-set directory."""

    try:
        paths = sorted(root.glob("*.json"))
    except OSError as error:  # pragma: no cover - unreadable directory
        raise CohortClaimPolicyError(f"unreadable frozen scenario set: {error}") from error
    if not paths:
        raise CohortClaimPolicyError(f"no frozen scenarios found under {root}")
    entries = [
        {
            "content_digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            "name": path.name,
        }
        for path in paths
    ]
    return content_digest({"entries": entries, "scenario_count": len(entries)})


def load_cohort_claim_policy(path: Path) -> CohortClaimPolicy:
    """Load and floor-check the trusted cohort claim policy revision."""

    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise CohortClaimPolicyError(f"unreadable cohort claim policy: {error}") from error
    body = _mapping(raw, "policy")
    if body.get("schema_version") != COHORT_CLAIM_POLICY_SCHEMA_VERSION:
        raise CohortClaimPolicyError(
            f"cohort claim policy schema MUST be {COHORT_CLAIM_POLICY_SCHEMA_VERSION}"
        )
    minimum = body.get("minimum_sample_size")
    if not isinstance(minimum, int) or isinstance(minimum, bool):
        raise CohortClaimPolicyError("cohort claim policy minimum_sample_size MUST be an integer")
    if minimum < MINIMUM_COHORT_SAMPLE_SIZE:
        raise CohortClaimPolicyError(
            f"cohort claim policy MUST NOT weaken the {MINIMUM_COHORT_SAMPLE_SIZE}-sample floor"
        )
    metric_ids = _identifiers(body.get("required_metric_ids"), "required_metric_ids")
    guard_ids = _identifiers(body.get("required_guard_ids"), "required_guard_ids")
    _require_floor(metric_ids, REQUIRED_SUCCESS_METRIC_IDS, "success metric")
    _require_floor(guard_ids, ZERO_THRESHOLD_GUARD_IDS, "zero-threshold guard")
    basis = _mapping(body.get("measurement_basis"), "measurement_basis")
    _validate_measurement_basis(basis, minimum=minimum, metric_ids=metric_ids)
    observation_import = _mapping(body.get("observation_import"), "observation_import")
    exporter_paths = _exporter_workflow_paths(
        observation_import.get("allowed_exporter_workflow_paths"),
        policy_path=path,
    )
    exporter_bindings = _exporter_measure_bindings(
        observation_import.get("exporter_measure_bindings"),
        exporter_paths=exporter_paths,
        metric_ids=metric_ids,
        guard_ids=guard_ids,
    )
    evidence = _mapping(body.get("evidence"), "evidence")
    freshness = _mapping(body.get("freshness_policy"), "freshness_policy")
    ceiling = freshness.get("ceiling_seconds")
    if not isinstance(ceiling, int) or isinstance(ceiling, bool) or not 0 < ceiling <= 31_536_000:
        raise CohortClaimPolicyError("cohort claim freshness ceiling MUST be bounded seconds")
    completeness = evidence.get("minimum_completeness_basis_points", 10_000)
    if not isinstance(completeness, int) or isinstance(completeness, bool):
        raise CohortClaimPolicyError("cohort claim completeness floor MUST be basis points")
    if completeness != 10_000:
        raise CohortClaimPolicyError("cohort claim policy MUST require complete evidence")
    return CohortClaimPolicy(
        policy_id=_text(body.get("policy_id"), "policy_id"),
        policy_version=_text(body.get("policy_version"), "policy_version"),
        benchmark_scenario_set_version=_text(
            body.get("benchmark_scenario_set_version"),
            "benchmark_scenario_set_version",
        ),
        benchmark_scenario_set_digest=_digest(
            body.get("benchmark_scenario_set_digest"),
            "benchmark_scenario_set_digest",
        ),
        measurement_basis_kind=_text(basis.get("kind"), "measurement basis kind"),
        measurement_protocol_version=_text(
            basis.get("protocol_version"),
            "measurement protocol_version",
        ),
        measurement_protocol_digest=content_digest(
            {
                "measurement_basis": dict(basis),
                "observation_import": dict(observation_import),
            }
        ),
        maximum_window_seconds=_integer(
            basis.get("maximum_window_seconds"),
            "measurement maximum_window_seconds",
        ),
        interval_methods=tuple(
            sorted(
                (
                    _text(metric_id, "measurement interval metric"),
                    _text(method, "measurement interval method"),
                )
                for metric_id, method in _mapping(
                    basis.get("interval_methods"),
                    "measurement interval_methods",
                ).items()
            )
        ),
        allowed_exporter_workflow_paths=exporter_paths,
        exporter_measure_bindings=exporter_bindings,
        minimum_sample_size=minimum,
        required_metric_ids=metric_ids,
        required_guard_ids=guard_ids,
        freshness_policy_digest=content_digest(
            {
                "ceiling_seconds": ceiling,
                "policy_id": _text(freshness.get("policy_id"), "freshness policy_id"),
                "policy_version": _text(
                    freshness.get("policy_version"), "freshness policy_version"
                ),
            }
        ),
        freshness_ceiling_seconds=ceiling,
        allowed_authority_classes=_identifiers(
            evidence.get("allowed_authority_classes"),
            "allowed_authority_classes",
        ),
        allowed_source_identities=_identifiers(
            evidence.get("allowed_source_identities"),
            "allowed_source_identities",
        ),
        purpose_id=_text(evidence.get("purpose_id"), "purpose_id"),
        producer_id=_text(evidence.get("producer_id"), "producer_id"),
        producer_version=_text(evidence.get("producer_version"), "producer_version"),
        method_id=_text(evidence.get("method_id"), "method_id"),
        method_version=_text(evidence.get("method_version"), "method_version"),
        minimum_completeness_basis_points=completeness,
    )


def _mapping(raw: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be an object")
    return raw


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _text(raw: Any, name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be non-empty text")
    return raw


def _digest(raw: Any, name: str) -> str:
    value = _text(raw, name)
    if not value.startswith("sha256:") or len(value) != 71:
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be a SHA-256 digest")
    return value


def _integer(raw: Any, name: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be an integer")
    return int(raw)


def _identifiers(raw: Any, name: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be a non-empty array")
    values = tuple(_text(item, name) for item in raw)
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be unique and ordered")
    return values


def _optional_identifiers(raw: Any, name: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be an array")
    values = tuple(_text(item, name) for item in raw)
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise CohortClaimPolicyError(f"cohort claim policy {name} MUST be unique and ordered")
    return values


def _exporter_workflow_paths(
    raw: Any,
    *,
    policy_path: Path,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    mapping = _mapping(raw, "allowed_exporter_workflow_paths")
    if set(mapping) != {"baseline", "treatment"}:
        raise CohortClaimPolicyError("cohort exporter allowlist MUST define baseline and treatment")
    repo_root = policy_path.resolve().parent.parent
    result: list[tuple[str, tuple[str, ...]]] = []
    for arm in ("baseline", "treatment"):
        configured = mapping[arm]
        if not isinstance(configured, list):
            raise CohortClaimPolicyError(f"cohort exporter allowlist {arm} MUST be an array")
        paths = tuple(configured)
        if (
            any(
                not isinstance(item, str) or _WORKFLOW_PATH.fullmatch(item) is None
                for item in paths
            )
            or paths != tuple(sorted(paths))
            or len(paths) != len(set(paths))
        ):
            raise CohortClaimPolicyError(
                f"cohort exporter allowlist {arm} MUST contain ordered workflow paths"
            )
        invalid: list[str] = []
        for item in paths:
            candidate = repo_root / item
            resolved = candidate.resolve()
            if (
                candidate.is_symlink()
                or not candidate.is_file()
                or not resolved.is_relative_to(repo_root)
            ):
                invalid.append(item)
        if invalid:
            raise CohortClaimPolicyError(
                "cohort exporter workflow MUST be a regular in-repository file in the "
                "policy revision: " + ", ".join(invalid)
            )
        result.append((arm, paths))
    return tuple(result)


def _exporter_measure_bindings(
    raw: Any,
    *,
    exporter_paths: tuple[tuple[str, tuple[str, ...]], ...],
    metric_ids: tuple[str, ...],
    guard_ids: tuple[str, ...],
) -> tuple[tuple[str, tuple[CohortExporterMeasureBinding, ...]], ...]:
    mapping = _mapping(raw, "exporter_measure_bindings")
    if set(mapping) != {"baseline", "treatment"}:
        raise CohortClaimPolicyError(
            "cohort exporter measure bindings MUST define baseline and treatment"
        )
    allowed_by_arm = dict(exporter_paths)
    shared_paths = set(allowed_by_arm["baseline"]) & set(allowed_by_arm["treatment"])
    if shared_paths:
        raise CohortClaimPolicyError(
            "cohort exporter workflows MUST NOT be shared across baseline and treatment"
        )

    result: list[tuple[str, tuple[CohortExporterMeasureBinding, ...]]] = []
    source_ids: set[str] = set()
    for arm in ("baseline", "treatment"):
        configured = _mapping(mapping[arm], f"exporter_measure_bindings {arm}")
        paths = tuple(configured)
        if paths != allowed_by_arm[arm]:
            raise CohortClaimPolicyError(
                f"cohort exporter measure bindings {arm} MUST match its ordered allowlist"
            )
        metric_owners: dict[str, str] = {}
        guard_owners: dict[str, str] = {}
        bindings: list[CohortExporterMeasureBinding] = []
        for workflow_path in paths:
            body = _mapping(
                configured[workflow_path],
                f"exporter measure binding {workflow_path}",
            )
            if set(body) != {"guard_ids", "metric_ids", "source_id"}:
                raise CohortClaimPolicyError(
                    "cohort exporter measure binding MUST define source_id, metric_ids, and "
                    "guard_ids"
                )
            source_id = _text(body["source_id"], f"exporter source_id {workflow_path}")
            if _SOURCE_BINDING_ID.fullmatch(source_id) is None:
                raise CohortClaimPolicyError(
                    "cohort exporter source_id MUST be lowercase ASCII with 3-64 characters"
                )
            if source_id in source_ids:
                raise CohortClaimPolicyError(
                    f"cohort exporter source_id MUST be unique: {source_id}"
                )
            source_ids.add(source_id)
            metrics = _optional_identifiers(
                body["metric_ids"],
                f"exporter metric_ids {workflow_path}",
            )
            guards = _optional_identifiers(
                body["guard_ids"],
                f"exporter guard_ids {workflow_path}",
            )
            if not metrics and not guards:
                raise CohortClaimPolicyError(
                    "cohort exporter measure binding MUST own at least one measure"
                )
            unknown_metrics = sorted(set(metrics) - set(metric_ids))
            unknown_guards = sorted(set(guards) - set(guard_ids))
            if unknown_metrics or unknown_guards:
                raise CohortClaimPolicyError(
                    "cohort exporter measure binding contains unknown measures: "
                    + ", ".join((*unknown_metrics, *unknown_guards))
                )
            _assign_measure_owners(metric_owners, metrics, workflow_path, "metric")
            _assign_measure_owners(guard_owners, guards, workflow_path, "guard")
            bindings.append(
                CohortExporterMeasureBinding(
                    source_id=source_id,
                    workflow_path=workflow_path,
                    metric_ids=metrics,
                    guard_ids=guards,
                )
            )
        if paths:
            missing_metrics = sorted(set(metric_ids) - set(metric_owners))
            missing_guards = sorted(set(guard_ids) - set(guard_owners))
            if missing_metrics or missing_guards:
                raise CohortClaimPolicyError(
                    f"cohort exporter measure bindings {arm} MUST cover every required measure: "
                    + ", ".join((*missing_metrics, *missing_guards))
                )
        result.append((arm, tuple(bindings)))
    return tuple(result)


def _assign_measure_owners(
    owners: dict[str, str],
    measure_ids: tuple[str, ...],
    workflow_path: str,
    measure_kind: str,
) -> None:
    for measure_id in measure_ids:
        existing = owners.get(measure_id)
        if existing is not None:
            raise CohortClaimPolicyError(
                f"cohort exporter {measure_kind} {measure_id} MUST have exactly one workflow owner"
            )
        owners[measure_id] = workflow_path


def _require_floor(values: tuple[str, ...], floor: tuple[str, ...], label: str) -> None:
    missing = sorted(set(floor) - set(values))
    if missing:
        raise CohortClaimPolicyError(
            f"cohort claim policy MUST require every {label}: missing {', '.join(missing)}"
        )


def _validate_measurement_basis(
    basis: Mapping[str, Any],
    *,
    minimum: int,
    metric_ids: tuple[str, ...],
) -> None:
    if basis.get("kind") != "prospective_operational":
        raise CohortClaimPolicyError(
            "cohort claim measurement basis MUST be prospective_operational"
        )
    if basis.get("arm_design") != "historical_baseline_prospective_treatment":
        raise CohortClaimPolicyError(
            "cohort claim arm design MUST avoid dual execution of one live event"
        )
    if basis.get("baseline_source") != "observed_non_fdai_operating_process":
        raise CohortClaimPolicyError(
            "cohort claim baseline MUST use the observed non-FDAI operating process"
        )
    if basis.get("treatment_source") != "deployed_fdai":
        raise CohortClaimPolicyError("cohort claim treatment MUST use deployed FDAI")
    if basis.get("dual_execution_allowed") is not False:
        raise CohortClaimPolicyError("cohort claim protocol MUST prohibit dual execution")
    if basis.get("independence_key") != "source_cluster_digest":
        raise CohortClaimPolicyError(
            "cohort claim protocol MUST deduplicate by source_cluster_digest"
        )
    if (
        _integer(
            basis.get("minimum_samples_per_measure"),
            "measurement minimum_samples_per_measure",
        )
        != minimum
    ):
        raise CohortClaimPolicyError(
            "cohort claim protocol sample floor MUST match the claim policy"
        )
    maximum_window = _integer(
        basis.get("maximum_window_seconds"),
        "measurement maximum_window_seconds",
    )
    if not 86_400 <= maximum_window <= 7_776_000:
        raise CohortClaimPolicyError("cohort claim protocol window MUST be between one and 90 days")
    methods = _mapping(basis.get("interval_methods"), "measurement interval_methods")
    if set(methods) != set(metric_ids):
        raise CohortClaimPolicyError(
            "cohort claim protocol MUST select an interval method for every required metric"
        )
    allowed = {"deterministic_bootstrap_95", "wilson_95"}
    if any(method not in allowed for method in methods.values()):
        raise CohortClaimPolicyError("cohort claim interval method is not supported")
    incorrect = sorted(
        metric_id
        for metric_id, expected in REQUIRED_INTERVAL_METHODS.items()
        if methods.get(metric_id) != expected
    )
    if incorrect:
        raise CohortClaimPolicyError(
            "cohort claim required interval methods are incorrect: " + ", ".join(incorrect)
        )


__all__ = [
    "COHORT_CLAIM_POLICY_PATH",
    "COHORT_CLAIM_POLICY_SCHEMA_VERSION",
    "REQUIRED_INTERVAL_METHODS",
    "REQUIRED_SUCCESS_METRIC_IDS",
    "ZERO_THRESHOLD_GUARD_IDS",
    "CohortClaimPolicy",
    "CohortClaimPolicyError",
    "CohortExporterMeasureBinding",
    "frozen_scenario_set_digest",
    "load_cohort_claim_policy",
    "require_commit_revision",
]

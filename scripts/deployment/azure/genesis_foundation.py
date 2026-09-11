#!/usr/bin/env python3
"""Generate or reverify an exact private Foundation plan without applying it."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.foundation_input import snapshot_foundation_input
from fdai_deployment_cli.foundation_plan import REVIEW_NAME
from fdai_deployment_cli.plan_input import read_plan_input
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.profile import load_profile

_DIGEST = re.compile(r"[0-9a-f]{64}")
_REQUIRED_INPUT_COUNT = 5
_REPORT_KEYS = {
    "schema_version",
    "state",
    "plan_ref",
    "attempt",
    "review_digest",
    "plan_digest",
    "expires_at",
    "integrity_verified",
    "apply_authorized",
    "mutation_performed",
    "subscription_ready",
}

CaptureCommand = Callable[..., str]


class FoundationPlanError(RuntimeError):
    """Carry one stable Foundation planning failure reason."""

    def __init__(self, reason_code: str, exit_code: int = 4) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True)
class FoundationPlanInputs:
    """Complete non-secret path set needed by signed-kit Foundation planning."""

    offline_kit: Path
    release_root: Path
    bundle_public_key: Path
    profile: Path
    variables_file: Path

    def validate(self) -> None:
        """Require stable absolute path interpretation before any external command."""

        if not all(path.is_absolute() for path in self.paths):
            raise FoundationPlanError("foundation_input_paths_must_be_absolute", 64)

    @property
    def paths(self) -> tuple[Path, ...]:
        """Return the complete path set in command-contract order."""

        return (
            self.offline_kit,
            self.release_root,
            self.bundle_public_key,
            self.profile,
            self.variables_file,
        )


def missing_foundation_report() -> dict[str, object]:
    """Return an identifier-free report for the externally supplied input boundary."""

    return {
        "schema_version": "fdai.genesis-foundation-prerequisites.v1",
        "state": "waiting",
        "required_count": _REQUIRED_INPUT_COUNT,
        "supplied_count": 0,
        "missing": [
            "signed_offline_kit",
            "release_public_key",
            "bundle_public_key",
            "foundation_profile",
            "foundation_variables",
        ],
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def prepare_foundation_plan(
    *,
    inputs: FoundationPlanInputs,
    repository_root: Path,
    orchestration_work_dir: Path,
    attempt: int,
    prior_report: dict[str, object] | None,
    timeout: int,
    capture: CaptureCommand,
    allow_expired_after_claim: bool = False,
) -> dict[str, object]:
    """Create or reverify one exact plan, then return only sanitized review metadata."""

    inputs.validate()
    if attempt < 1:
        raise FoundationPlanError("invalid_foundation_plan_attempt")
    if prior_report is not None:
        verified = _reverify_current_plan(
            inputs=inputs,
            repository_root=repository_root,
            orchestration_work_dir=orchestration_work_dir,
            prior_report=prior_report,
            timeout=timeout,
            capture=capture,
            allow_expired_after_claim=allow_expired_after_claim,
        )
        if verified is not None:
            return verified

    plan_ref = f"foundation-plan-attempt-{attempt}"
    plan_directory = orchestration_work_dir / plan_ref
    command = (
        "uv",
        "run",
        "--frozen",
        "--project",
        str(repository_root / "packages/deployment-cli"),
        "fdaictl",
        "provision",
        "plan",
        "--stage",
        "foundation",
        "--offline-kit",
        str(inputs.offline_kit),
        "--release-root",
        str(inputs.release_root),
        "--bundle-public-key",
        str(inputs.bundle_public_key),
        "--profile",
        str(inputs.profile),
        "--work-dir",
        str(plan_directory),
        "--variables-file",
        str(inputs.variables_file),
        "--save-plan",
        "--output",
        "json",
    )
    raw = capture(
        command,
        "foundation_plan_generation_failed",
        strip=False,
        timeout=timeout,
    )
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FoundationPlanError("foundation_plan_result_invalid") from exc
    if not isinstance(result, dict):
        raise FoundationPlanError("foundation_plan_result_invalid")
    saved = result.get("saved_plan")
    if (
        result.get("schema_version") != "fdai.provision-plan.v1"
        or result.get("stage") != "foundation"
        or result.get("state") != "review"
        or result.get("apply_authorized") is not False
        or result.get("mutation_performed") is not False
        or result.get("subscription_ready") is not False
        or not isinstance(saved, dict)
    ):
        raise FoundationPlanError("foundation_plan_result_invalid")
    report = _report_from_saved_plan(saved, plan_ref=plan_ref, attempt=attempt)
    _validate_report(report)
    return report


def _reverify_current_plan(
    *,
    inputs: FoundationPlanInputs,
    repository_root: Path,
    orchestration_work_dir: Path,
    prior_report: dict[str, object],
    timeout: int,
    capture: CaptureCommand,
    allow_expired_after_claim: bool,
) -> dict[str, object] | None:
    _validate_report(prior_report)
    plan_ref = str(prior_report["plan_ref"])
    plan_directory = orchestration_work_dir / plan_ref
    expires_at = _parse_utc(str(prior_report["expires_at"]))
    now = datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint
    if not allow_expired_after_claim and expires_at <= now:
        return None
    if plan_directory.exists():
        review = load_json_object(
            read_private_bytes(plan_directory / REVIEW_NAME, max_bytes=65_536),
            label="Foundation review",
        )
        context = review.get("context")
        current_variables_digest = _current_variables_digest(
            inputs=inputs,
            orchestration_work_dir=orchestration_work_dir,
        )
        if (
            not isinstance(context, dict)
            or context.get("variables_digest") != current_variables_digest
        ):
            if allow_expired_after_claim:
                raise FoundationPlanError("foundation_plan_input_changed_after_claim", 3)
            return None
    command = (
        "uv",
        "run",
        "--frozen",
        "--project",
        str(repository_root / "packages/deployment-cli"),
        "fdaictl",
        "provision",
        "verify-foundation-plan",
        "--directory",
        str(orchestration_work_dir / plan_ref),
        "--profile",
        str(inputs.profile),
        "--expected-review-digest",
        str(prior_report["review_digest"]),
        "--output",
        "json",
    )
    if allow_expired_after_claim:
        command = (*command, "--allow-expired-after-claim")
    raw = capture(
        command,
        "foundation_plan_verification_failed",
        strip=False,
        timeout=timeout,
    )
    try:
        verification = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FoundationPlanError("foundation_plan_verification_invalid") from exc
    if (
        not isinstance(verification, dict)
        or verification.get("schema_version") != "fdai.foundation-plan-integrity.v1"
        or verification.get("state") != "review"
        or verification.get("review_digest") != prior_report["review_digest"]
        or verification.get("plan_digest") != prior_report["plan_digest"]
        or verification.get("integrity_verified") is not True
        or verification.get("apply_authorized") is not False
        or verification.get("mutation_performed") is not False
        or verification.get("subscription_ready") is not False
    ):
        raise FoundationPlanError("foundation_plan_verification_invalid")
    return prior_report


def _current_variables_digest(*, inputs: FoundationPlanInputs, orchestration_work_dir: Path) -> str:
    profile = load_profile(inputs.profile)
    with TemporaryDirectory(
        prefix="foundation-plan-input-", dir=orchestration_work_dir
    ) as temporary:
        normalized = Path(temporary) / "variables.json"
        snapshot_foundation_input(
            inputs.variables_file,
            normalized,
            expected_target_binding=profile.target_binding,
            expected_region=profile.region,
            expected_environment=profile.environment,
        )
        return canonical_digest(read_plan_input(normalized))


def _report_from_saved_plan(
    saved: dict[str, object], *, plan_ref: str, attempt: int
) -> dict[str, object]:
    if (
        saved.get("schema_version") != "fdai.foundation-saved-plan.v1"
        or saved.get("state") != "review"
        or saved.get("apply_authorized") is not False
        or saved.get("mutation_performed") is not False
        or saved.get("subscription_ready") is not False
    ):
        raise FoundationPlanError("foundation_plan_result_invalid")
    return {
        "schema_version": "fdai.genesis-foundation-plan.v1",
        "state": "review",
        "plan_ref": plan_ref,
        "attempt": attempt,
        "review_digest": saved.get("review_digest"),
        "plan_digest": saved.get("plan_digest"),
        "expires_at": saved.get("expires_at"),
        "integrity_verified": True,
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _validate_report(report: dict[str, object]) -> None:
    attempt = report.get("attempt")
    if (
        set(report) != _REPORT_KEYS
        or report.get("schema_version") != "fdai.genesis-foundation-plan.v1"
        or report.get("state") != "review"
        or report.get("integrity_verified") is not True
        or report.get("apply_authorized") is not False
        or report.get("mutation_performed") is not False
        or report.get("subscription_ready") is not False
        or not isinstance(attempt, int)
        or isinstance(attempt, bool)
        or attempt < 1
        or re.fullmatch(r"foundation-plan-attempt-[1-9][0-9]*", str(report.get("plan_ref"))) is None
    ):
        raise FoundationPlanError("foundation_plan_report_invalid")
    for key in ("review_digest", "plan_digest"):
        if not isinstance(report.get(key), str) or _DIGEST.fullmatch(str(report[key])) is None:
            raise FoundationPlanError("foundation_plan_report_invalid")
    _parse_utc(str(report.get("expires_at")))


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FoundationPlanError("foundation_plan_report_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise FoundationPlanError("foundation_plan_report_invalid")
    return parsed.astimezone(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint

#!/usr/bin/env python3
"""Coordinate the resumable private Foundation lifecycle behind Genesis."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from genesis_approval import GenesisApproval
from genesis_checks import GenesisChecks
from genesis_foundation import (
    FoundationPlanError,
    FoundationPlanInputs,
    missing_foundation_report,
    prepare_foundation_plan,
)
from genesis_private_command import (
    CommandRunner,
    PrivateCommandContext,
    PrivateCommandExecutor,
    require_private_result,
    safe_private_projection,
)
from genesis_private_errors import PrivateExecutionError, PrivateExecutionWaitError
from genesis_runner_image_contract import (
    CLAIM_NAME as IMAGE_CLAIM_NAME,
)
from genesis_runner_image_contract import (
    RECEIPT_NAME as IMAGE_RECEIPT_NAME,
)
from genesis_runner_image_contract import (
    load_review as load_runner_image_review,
)
from genesis_runner_image_contract import verify_foundation_image_input
from genesis_status import StatusStore

_DIGEST = re.compile(r"[0-9a-f]{64}")
_IMAGE_PLAN_REF = re.compile(r"runner-image-attempt-[1-9][0-9]*")
FoundationPlanner = Callable[..., dict[str, object]]


@dataclass(frozen=True, slots=True)
class PrivateExecutionConfig:
    """Non-secret inputs needed to compose the private Foundation checkpoints."""

    repository_root: Path
    repository: str
    subscription_id: str
    tenant_id: str
    source_commit: str
    work_dir: Path
    foundation_inputs: FoundationPlanInputs | None
    approval: GenesisApproval | None
    create_runner_image: bool
    runner_image_terraform: Path | None
    runner_ssh_private_key: Path | None
    execution_timeout_seconds: int


class PrivateExecutionCoordinator:
    """Advance exact private checkpoints and resume claimed effects by verification only."""

    def __init__(
        self,
        *,
        config: PrivateExecutionConfig,
        store: StatusStore,
        checks: GenesisChecks,
        run_child: CommandRunner | None = None,
        prepare_plan: FoundationPlanner | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.checks = checks
        command_context = PrivateCommandContext(
            repository_root=config.repository_root,
            subscription_id=config.subscription_id,
            tenant_id=config.tenant_id,
        )
        self._commands = (
            PrivateCommandExecutor(command_context)
            if run_child is None
            else PrivateCommandExecutor(command_context, run_child=run_child)
        )
        self._prepare_plan = prepare_plan or prepare_foundation_plan
        self._active_stage = "foundation-plan"

    def run(self) -> None:
        """Advance until the protected application-plan boundary or a safe wait."""

        inputs = self.config.foundation_inputs
        if inputs is None:
            stage = "runner-image-plan" if self.config.create_runner_image else "foundation-plan"
            self.store.foundation_report = missing_foundation_report()
            self._pause(
                stage=stage,
                checkpoint="foundation-prerequisites",
                reason="private_foundation_external_artifacts_required",
                next_action=(
                    "provide_signed_offline_kit_exact_runner_image_and_foundation_profile_"
                    "then_generate_exact_plan"
                ),
            )
        variables_file = self._run_runner_image(inputs)
        plan_report = self._prepare_foundation(inputs, variables_file)
        plan_directory = self.config.work_dir / str(plan_report["plan_ref"])
        foundation_started = self._checkpoint_started(
            plan_directory,
            "foundation-apply-claim.json",
            "foundation-apply-receipt.json",
        )
        if not foundation_started and not self._approval_matches(
            "foundation-apply",
            stage="foundation-apply",
            review_digest=str(plan_report["review_digest"]),
            plan_digest=str(plan_report["plan_digest"]),
        ):
            self._pause(
                stage="foundation-apply",
                checkpoint="foundation-plan",
                reason="foundation_exact_plan_approval_required",
                next_action="review_foundation_plan_and_supply_exact_approval",
            )
        foundation = self._run_foundation_apply(inputs, variables_file, plan_report)
        enrollment = self._run_runner_enrollment(inputs, plan_report, foundation)
        state = self._run_foundation_state(
            inputs,
            variables_file,
            plan_report,
            foundation,
            enrollment,
        )
        self._record_checkpoint(
            stage="foundation-state",
            checkpoint="foundation-state",
            state="verified",
            field="state_handoff",
            result=state,
            completed=True,
        )
        self._pause(
            stage="application-plan",
            checkpoint="application-plan",
            reason="protected_application_plan_required",
            next_action="run_exact_protected_application_plan_from_attested_runner",
        )

    def _run_runner_image(self, inputs: FoundationPlanInputs) -> Path:
        if not self.config.create_runner_image:
            self.store.mark_skipped("runner-image-plan", "runner-image-apply")
            return inputs.variables_file
        terraform = self.config.runner_image_terraform
        if terraform is None:
            raise PrivateExecutionError("runner-image-plan", "runner_image_terraform_required", 64)
        terraform = terraform.resolve(strict=True)
        plan_report = self._current_runner_image_plan()
        image_directory: Path
        review: dict[str, object]
        if plan_report is not None:
            image_directory = self.config.work_dir / str(plan_report["plan_ref"])
            started = self._checkpoint_started(
                image_directory,
                IMAGE_CLAIM_NAME,
                IMAGE_RECEIPT_NAME,
            )
            try:
                review = load_runner_image_review(
                    image_directory,
                    expected_review_digest=str(plan_report["review_digest"]),
                    require_unexpired=not started,
                )
            except ValueError as exc:
                if str(exc) != "runner image review is expired" or started:
                    raise PrivateExecutionError(
                        "runner-image-plan", "runner_image_plan_verification_failed", 3
                    ) from exc
                plan_report = None
        if plan_report is None:
            image_directory = self.config.work_dir / f"runner-image-attempt-{self.store.attempt}"
            self._begin("runner-image-plan")
            result = self._run_json_child(
                "genesis-runner-image.sh",
                (
                    "plan",
                    "--work-dir",
                    str(image_directory),
                    "--profile",
                    str(inputs.profile),
                    "--foundation-variables",
                    str(inputs.variables_file),
                    "--terraform",
                    str(terraform),
                    "--timeout-seconds",
                    str(self._bounded_timeout(7800, minimum=900)),
                    "--output",
                    "json",
                ),
                stage="runner-image-plan",
                reason="runner_image_plan_failed",
                timeout=self._bounded_timeout(7800, minimum=900),
            )
            result["plan_ref"] = image_directory.name
            self._require_result(
                result,
                stage="runner-image-plan",
                schema="fdai.genesis-runner-image-plan-result.v1",
                state="review",
            )
            self._record_checkpoint(
                stage="runner-image-plan",
                checkpoint="runner-image-plan",
                state="review",
                field="runner_image_plan",
                result=result,
                completed=True,
            )
            plan_report = result
            review = load_runner_image_review(
                image_directory,
                expected_review_digest=str(result["review_digest"]),
            )
        else:
            self._record_checkpoint(
                stage="runner-image-plan",
                checkpoint="runner-image-plan",
                state="review",
                field="runner_image_plan",
                result=plan_report,
                completed=True,
            )
        started = self._checkpoint_started(
            image_directory,
            IMAGE_CLAIM_NAME,
            IMAGE_RECEIPT_NAME,
        )
        if not started and not self._approval_matches(
            "runner-image",
            stage="runner-image-apply",
            review_digest=str(review["review_digest"]),
            plan_digest=str(review["plan_digest"]),
        ):
            self._pause(
                stage="runner-image-apply",
                checkpoint="runner-image-plan",
                reason="runner_image_exact_plan_approval_required",
                next_action="review_runner_image_plan_and_supply_exact_approval",
            )
        mode = "--resume-verification" if started else "--approve"
        self._begin("runner-image-apply")
        result = self._run_json_child(
            "genesis-runner-image.sh",
            (
                "apply",
                "--work-dir",
                str(image_directory),
                "--profile",
                str(inputs.profile),
                "--terraform",
                str(terraform),
                "--expected-review-digest",
                str(review["review_digest"]),
                "--expected-plan-digest",
                str(review["plan_digest"]),
                "--repository",
                self.config.repository,
                mode,
                "--timeout-seconds",
                str(self._bounded_timeout(7800, minimum=900)),
                "--output",
                "json",
            ),
            stage="runner-image-apply",
            reason="runner_image_apply_or_verification_failed",
            timeout=self._bounded_timeout(7800, minimum=900),
        )
        self._require_result(
            result,
            stage="runner-image-apply",
            schema="fdai.genesis-runner-image-apply-receipt.v1",
            state="applied",
            receipt=True,
        )
        self.store.mutation_performed = True
        self._record_checkpoint(
            stage="runner-image-apply",
            checkpoint="runner-image-apply",
            state="applied",
            field="runner_image_apply",
            result=result,
            completed=True,
        )
        variables_file = self.config.work_dir / "foundation-variables-with-image.json"
        if not variables_file.exists():
            prepared = self._run_json_child(
                "genesis-runner-image.sh",
                (
                    "foundation-input",
                    "--source",
                    str(inputs.variables_file),
                    "--image-receipt",
                    str(image_directory / IMAGE_RECEIPT_NAME),
                    "--profile",
                    str(inputs.profile),
                    "--destination",
                    str(variables_file),
                    "--output",
                    "json",
                ),
                stage="runner-image-apply",
                reason="foundation_image_input_preparation_failed",
                timeout=self._bounded_timeout(300, minimum=30),
            )
            self._require_result(
                prepared,
                stage="runner-image-apply",
                schema="fdai.genesis-foundation-image-input.v1",
                state="prepared",
            )
        verify_foundation_image_input(
            source=inputs.variables_file,
            image_receipt=image_directory / IMAGE_RECEIPT_NAME,
            profile_path=inputs.profile,
            destination=variables_file,
        )
        return variables_file

    def _prepare_foundation(
        self,
        inputs: FoundationPlanInputs,
        variables_file: Path,
    ) -> dict[str, object]:
        prior = self._current_foundation_plan()
        started = False
        if prior is not None:
            plan_directory = self.config.work_dir / str(prior["plan_ref"])
            started = self._checkpoint_started(
                plan_directory,
                "foundation-apply-claim.json",
                "foundation-apply-receipt.json",
            )
        effective_inputs = FoundationPlanInputs(
            offline_kit=inputs.offline_kit,
            release_root=inputs.release_root,
            bundle_public_key=inputs.bundle_public_key,
            profile=inputs.profile,
            variables_file=variables_file,
        )
        self._begin("foundation-plan")
        try:
            report = self._prepare_plan(
                inputs=effective_inputs,
                repository_root=self.config.repository_root,
                orchestration_work_dir=self.config.work_dir,
                attempt=self.store.attempt,
                prior_report=prior,
                timeout=self._bounded_timeout(
                    self.config.execution_timeout_seconds,
                    minimum=300,
                ),
                capture=self.checks.capture,
                allow_expired_after_claim=started,
            )
        except FoundationPlanError as exc:
            raise PrivateExecutionError("foundation-plan", exc.reason_code, exc.exit_code) from exc
        self.checks.verify_checkout_unchanged()
        self._record_checkpoint(
            stage="foundation-plan",
            checkpoint="foundation-plan",
            state="review",
            field="foundation_plan",
            result=report,
            completed=True,
        )
        return report

    def _run_foundation_apply(
        self,
        inputs: FoundationPlanInputs,
        variables_file: Path,
        plan_report: dict[str, object],
    ) -> dict[str, object]:
        plan_directory = self.config.work_dir / str(plan_report["plan_ref"])
        started = self._checkpoint_started(
            plan_directory,
            "foundation-apply-claim.json",
            "foundation-apply-receipt.json",
        )
        mode = "--resume-verification" if started else "--approve"
        self._begin("foundation-apply")
        result = self._run_json_child(
            "genesis-foundation-apply.sh",
            (
                "--plan-directory",
                str(plan_directory),
                "--profile",
                str(inputs.profile),
                "--variables-file",
                str(variables_file),
                "--offline-kit",
                str(inputs.offline_kit),
                "--release-root",
                str(inputs.release_root),
                "--bundle-public-key",
                str(inputs.bundle_public_key),
                "--expected-review-digest",
                str(plan_report["review_digest"]),
                "--expected-plan-digest",
                str(plan_report["plan_digest"]),
                "--repository",
                self.config.repository,
                mode,
                "--timeout-seconds",
                str(self._bounded_timeout(7200, minimum=900)),
                "--output",
                "json",
            ),
            stage="foundation-apply",
            reason="foundation_apply_or_verification_failed",
            timeout=self._bounded_timeout(7200, minimum=900),
        )
        self._require_result(
            result,
            stage="foundation-apply",
            schema="fdai.genesis-foundation-apply-receipt.v1",
            state="applied",
            receipt=True,
        )
        self.store.mutation_performed = True
        self._record_checkpoint(
            stage="foundation-apply",
            checkpoint="foundation-apply",
            state="applied",
            field="foundation_apply",
            result=result,
            completed=True,
        )
        return result

    def _run_runner_enrollment(
        self,
        inputs: FoundationPlanInputs,
        plan_report: dict[str, object],
        foundation: dict[str, object],
    ) -> dict[str, object]:
        private_key = self.config.runner_ssh_private_key
        if private_key is None:
            self._pause(
                stage="runner-enrollment",
                checkpoint="runner-enrollment",
                reason="runner_ssh_private_key_required",
                next_action="supply_exact_runner_ssh_private_key_path",
            )
        plan_directory = self.config.work_dir / str(plan_report["plan_ref"])
        foundation_digest = self._required_digest(
            foundation, "receipt_digest", stage="runner-enrollment"
        )
        started = self._checkpoint_started(
            plan_directory,
            "runner-enrollment-claim.json",
            "runner-enrollment-receipt.json",
        )
        if not started and not self._approval_matches(
            "runner-enrollment",
            stage="runner-enrollment",
            foundation_receipt_digest=foundation_digest,
        ):
            self._pause(
                stage="runner-enrollment",
                checkpoint="runner-enrollment",
                reason="runner_enrollment_approval_required",
                next_action=("review_foundation_receipt_and_supply_runner_enrollment_approval"),
            )
        mode = "--resume-verification" if started else "--approve"
        self._begin("runner-enrollment")
        result = self._run_json_child(
            "genesis-runner-enrollment.sh",
            (
                "--foundation-plan-directory",
                str(plan_directory),
                "--profile",
                str(inputs.profile),
                "--repository",
                self.config.repository,
                "--ssh-private-key",
                str(private_key),
                "--expected-foundation-receipt-digest",
                foundation_digest,
                mode,
                "--timeout-seconds",
                str(self._bounded_timeout(1800, minimum=300)),
                "--output",
                "json",
            ),
            stage="runner-enrollment",
            reason="runner_enrollment_or_verification_failed",
            timeout=self._bounded_timeout(1800, minimum=300),
        )
        self._require_result(
            result,
            stage="runner-enrollment",
            schema="fdai.genesis-runner-enrollment-receipt.v1",
            state="attested",
            receipt=True,
        )
        self.store.mutation_performed = True
        self._record_checkpoint(
            stage="runner-enrollment",
            checkpoint="runner-enrollment",
            state="attested",
            field="runner_enrollment",
            result=result,
            completed=True,
        )
        return result

    def _run_foundation_state(
        self,
        inputs: FoundationPlanInputs,
        variables_file: Path,
        plan_report: dict[str, object],
        foundation: dict[str, object],
        enrollment: dict[str, object],
    ) -> dict[str, object]:
        private_key = self.config.runner_ssh_private_key
        if private_key is None:
            raise PrivateExecutionError("foundation-state", "runner_ssh_private_key_required", 64)
        plan_directory = self.config.work_dir / str(plan_report["plan_ref"])
        foundation_digest = self._required_digest(
            foundation, "receipt_digest", stage="foundation-state"
        )
        enrollment_digest = self._required_digest(
            enrollment, "receipt_digest", stage="foundation-state"
        )
        started = self._checkpoint_started(
            plan_directory,
            "foundation-state-handoff-claim.json",
            "foundation-state-handoff-receipt.json",
        )
        if not started and not self._approval_matches(
            "foundation-state",
            stage="foundation-state",
            foundation_receipt_digest=foundation_digest,
            enrollment_receipt_digest=enrollment_digest,
        ):
            self._pause(
                stage="foundation-state",
                checkpoint="foundation-state",
                reason="foundation_state_handoff_approval_required",
                next_action="review_enrollment_receipt_and_supply_state_handoff_approval",
            )
        mode = "--resume-verification" if started else "--approve"
        self._begin("foundation-state")
        result = self._run_json_child(
            "genesis-foundation-state.sh",
            (
                "--foundation-plan-directory",
                str(plan_directory),
                "--profile",
                str(inputs.profile),
                "--variables-file",
                str(variables_file),
                "--offline-kit",
                str(inputs.offline_kit),
                "--release-root",
                str(inputs.release_root),
                "--bundle-public-key",
                str(inputs.bundle_public_key),
                "--repository",
                self.config.repository,
                "--ssh-private-key",
                str(private_key),
                "--expected-foundation-receipt-digest",
                foundation_digest,
                "--expected-enrollment-receipt-digest",
                enrollment_digest,
                mode,
                "--timeout-seconds",
                str(self._bounded_timeout(3600, minimum=900)),
                "--output",
                "json",
            ),
            stage="foundation-state",
            reason="foundation_state_handoff_or_verification_failed",
            timeout=self._bounded_timeout(3600, minimum=900),
        )
        self._require_result(
            result,
            stage="foundation-state",
            schema="fdai.genesis-foundation-state-handoff-receipt.v1",
            state="verified",
            receipt=True,
        )
        self.store.mutation_performed = True
        return result

    def _current_runner_image_plan(self) -> dict[str, object] | None:
        value = self._private_report().get("runner_image_plan")
        if not isinstance(value, dict):
            return None
        plan_ref = value.get("plan_ref")
        if not isinstance(plan_ref, str) or _IMAGE_PLAN_REF.fullmatch(plan_ref) is None:
            raise PrivateExecutionError("runner-image-plan", "runner_image_plan_report_invalid", 3)
        return {str(key): item for key, item in value.items()}

    def _current_foundation_plan(self) -> dict[str, object] | None:
        value = self._private_report().get("foundation_plan")
        if not isinstance(value, dict):
            return None
        return {str(key): item for key, item in value.items()}

    def _run_json_child(
        self,
        script_name: str,
        arguments: tuple[str, ...],
        *,
        stage: str,
        reason: str,
        timeout: int,
    ) -> dict[str, object]:
        return self._commands.run_json(
            script_name,
            arguments,
            stage=stage,
            reason=reason,
            timeout=timeout,
        )

    def _private_report(self) -> dict[str, object]:
        current = self.store.foundation_report
        if (
            current is not None
            and current.get("schema_version") == "fdai.genesis-private-foundation.v1"
        ):
            return {str(key): value for key, value in current.items()}
        report: dict[str, object] = {
            "schema_version": "fdai.genesis-private-foundation.v1",
            "state": "running",
            "current_checkpoint": "foundation-prerequisites",
            "prerequisites": None,
            "runner_image_plan": None,
            "runner_image_apply": None,
            "foundation_plan": None,
            "foundation_apply": None,
            "runner_enrollment": None,
            "state_handoff": None,
            "mutation_performed": False,
            "subscription_ready": False,
        }
        if (
            current is not None
            and current.get("schema_version") == "fdai.genesis-foundation-plan.v1"
        ):
            report["foundation_plan"] = current
        elif (
            current is not None
            and current.get("schema_version") == "fdai.genesis-foundation-prerequisites.v1"
        ):
            report["prerequisites"] = current
        return report

    def _record_checkpoint(
        self,
        *,
        stage: str,
        checkpoint: str,
        state: str,
        field: str,
        result: Mapping[str, object],
        completed: bool,
    ) -> None:
        report = self._private_report()
        safe = safe_private_projection(result, stage=stage)
        report["current_checkpoint"] = checkpoint
        report["state"] = state
        report[field] = safe
        report["mutation_performed"] = self.store.mutation_performed or bool(
            result.get("mutation_performed")
        )
        report["subscription_ready"] = False
        self.store.foundation_report = report
        self.store.update(stage=stage, state="running", completed=completed)

    def _pause(
        self,
        *,
        stage: str,
        checkpoint: str,
        reason: str,
        next_action: str,
    ) -> NoReturn:
        report = self._private_report()
        report["current_checkpoint"] = checkpoint
        report["state"] = "waiting"
        report["mutation_performed"] = self.store.mutation_performed
        report["subscription_ready"] = False
        self.store.foundation_report = report
        raise PrivateExecutionWaitError(stage, reason, next_action)

    def _approval_matches(self, approval_stage: str, *, stage: str, **expected: str) -> bool:
        approval = self.config.approval
        if approval is None:
            return False
        try:
            return approval.authorizes(approval_stage, **expected)
        except ValueError as exc:
            raise PrivateExecutionError(stage, "genesis_approval_evidence_mismatch", 3) from exc

    def _begin(self, stage: str) -> None:
        self._active_stage = stage
        self._bounded_timeout(1)
        self.store.update(stage=stage, state="running")

    def _bounded_timeout(self, maximum: int, *, minimum: int = 1) -> int:
        remaining = self.store.remaining_seconds()
        if remaining < minimum:
            raise PrivateExecutionError(self._active_stage, "orchestration_deadline_exceeded", 3)
        return min(maximum, remaining)

    @staticmethod
    def _checkpoint_started(directory: Path, claim_name: str, receipt_name: str) -> bool:
        return (directory / claim_name).exists() or (directory / receipt_name).exists()

    @staticmethod
    def _required_digest(value: Mapping[str, object], name: str, *, stage: str) -> str:
        item = value.get(name)
        if not isinstance(item, str) or _DIGEST.fullmatch(item) is None:
            raise PrivateExecutionError(stage, "private_checkpoint_receipt_invalid")
        return item

    @staticmethod
    def _require_result(
        value: Mapping[str, object],
        *,
        stage: str,
        schema: str,
        state: str,
        receipt: bool = False,
    ) -> None:
        require_private_result(
            value,
            stage=stage,
            schema=schema,
            state=state,
            receipt=receipt,
        )

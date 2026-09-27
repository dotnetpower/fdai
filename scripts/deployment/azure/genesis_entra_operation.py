#!/usr/bin/env python3
"""Run bounded FDAI app/group convergence from an immutable source snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.doctor import azure_active_target_binding
from fdai_deployment_cli.entra_profiles import (
    EntraControlProfile,
    EntraTargetProfile,
    load_control_profile_descriptor,
    load_target_profile_descriptor,
)
from fdai_deployment_cli.identity_profile import IdentityProfileObservation
from fdai_deployment_cli.private_output import write_private_output
from fdai_deployment_cli.source_snapshot import verify_source_snapshot
from genesis_approval import load_genesis_approval
from genesis_approval_prompt import create_approval, current_actor_digest
from genesis_entra import (
    EntraPlan,
    apply_entra_bounded,
    plan_entra,
)
from genesis_entra_operation_support import (
    descriptor_from_environment as _descriptor_from_environment,
)
from genesis_entra_operation_support import (
    operation_context as _operation_context,
)
from genesis_entra_operation_support import (
    operation_lock as _operation_lock,
)
from genesis_entra_operation_support import (
    public_result as _public_result,
)
from genesis_entra_operation_support import (
    remove_stale_approval as _remove_stale_approval,
)
from genesis_entra_operation_support import (
    require_private_directory as _require_private_directory,
)
from genesis_entra_operation_support import (
    result_from_receipt as _result_from_receipt,
)
from genesis_entra_operation_support import (
    snapshot_from_environment as _snapshot_from_environment,
)
from genesis_entra_readback import EntraEffectReadback, read_entra_effects
from genesis_entra_records import (
    OperationContext,
    claim_record,
    load_claim,
    load_receipt,
    write_receipt,
)
from genesis_identity_executor import executor_execution_context
from genesis_identity_profile import observe_identity_profile

_COMMIT = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


def run_entra_operation(
    *,
    work_dir: Path,
    target: EntraTargetProfile,
    controls: EntraControlProfile,
    snapshot_directory: Path,
    snapshot_digest: str,
    apply: bool,
) -> dict[str, object]:
    """Observe or apply only after snapshot, target, and reviewed-control verification."""

    if target.control_profile_digest != controls.digest:
        raise ValueError("Entra target profile does not bind the reviewed control profile")
    if apply and target.environment != "dev":
        raise ValueError("Entra apply is supported only for a profile-bound dev target")
    source = verify_source_snapshot(snapshot_directory, expected_digest=snapshot_digest)
    source_commit = source.get("source_commit")
    if not isinstance(source_commit, str) or _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("Entra source snapshot commit is invalid")
    active_binding = azure_active_target_binding()
    if active_binding is None or active_binding != target.target_binding:
        raise ValueError("active Azure target does not match the private Entra target profile")
    _require_private_directory(work_dir)
    context = _operation_context(
        source_commit=source_commit,
        target=target,
        controls=controls,
        snapshot_digest=snapshot_digest,
    )
    observation, human_id = observe_identity_profile(target, controls)
    plan: EntraPlan | None
    plan_blockers: tuple[str, ...] = ()
    try:
        plan = plan_entra(
            bounded=True,
            approved_role_groups=controls.role_groups,
        )
    except (OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError, TimeoutError):
        plan = None
        plan_blockers = ("entra_app_group_plan_readback_unavailable",)
    if not observation.ready or human_id is None or plan is None:
        return _public_result(
            state="blocked",
            environment=target.environment,
            observation=observation,
            plan=plan.projection() if plan is not None else None,
            blockers=(
                *plan_blockers,
                *(("current_human_identity_unavailable",) if human_id is None else ()),
            ),
        )
    if not apply:
        return _public_result(
            state="observed",
            environment=target.environment,
            observation=observation,
            plan=plan.projection(),
        )

    with _operation_lock(work_dir):
        receipt_path = work_dir / "entra-only-receipt.json"
        claim_path = work_dir / "entra-only-claim.json"
        if receipt_path.exists():
            receipt = load_receipt(receipt_path, context)
            retained = _retained_plan(receipt, controls.role_groups)
            with executor_execution_context(target) as execution_actor_digest:
                _revalidate_executor_context(
                    context=context,
                    target=target,
                    controls=controls,
                    plan=retained,
                    execution_actor_digest=execution_actor_digest,
                )
                if receipt.get("execution_actor_digest") != execution_actor_digest:
                    raise ValueError("Entra-only receipt executor differs from current executor")
                readback = _verify_readback(plan=retained)
            if (
                receipt.get("profile_digest") != observation.digest
                or receipt["readback_digest"] != readback.evidence_digest
            ):
                raise ValueError("Entra-only receipt differs from current independent readback")
            return _result_from_receipt(observation, receipt)
        if claim_path.exists():
            claim = load_claim(claim_path, context, observation)
            retained = _retained_plan(claim, controls.role_groups)
            with executor_execution_context(target) as execution_actor_digest:
                _revalidate_executor_context(
                    context=context,
                    target=target,
                    controls=controls,
                    plan=retained,
                    execution_actor_digest=execution_actor_digest,
                )
                if claim.get("execution_actor_digest") != execution_actor_digest:
                    raise ValueError("Entra-only claim executor differs from current executor")
                try:
                    readback = _verify_readback(plan=retained)
                except ValueError as exc:
                    raise ValueError(
                        "claimed Entra-only apply is incomplete; automatic retry is blocked"
                    ) from exc
            receipt = _terminal_receipt(
                receipt_path=receipt_path,
                context=context,
                observation=observation,
                plan=retained,
                approval_actor_digest=str(claim["approval_actor_digest"]),
                approval_principal_digest=str(claim["approval_principal_digest"]),
                execution_actor_digest=execution_actor_digest,
                readback=readback,
                recovered_from_claim=True,
            )
            return _result_from_receipt(observation, receipt)

        current_plan = plan_entra(
            bounded=True,
            approved_role_groups=controls.role_groups,
        )
        if current_plan != plan:
            raise ValueError("bounded Entra app/group plan changed before approval")
        review = {
            "schema_version": "fdai.genesis-entra-only-review.v2",
            "environment": target.environment,
            "target_profile_digest": target.digest,
            "control_profile_digest": controls.digest,
            "snapshot_digest": snapshot_digest,
            "identity_profile": observation.to_mapping(),
            "plan": plan.projection(),
        }
        print(json.dumps(review, indent=2, sort_keys=True), file=sys.stderr)
        actor_digest = current_actor_digest(context.run_binding)
        approval_path = work_dir / "entra-only-approval.json"
        _remove_stale_approval(approval_path)
        create_approval(
            stage="entra-config",
            evidence={"plan_digest": plan.digest},
            run_binding=context.run_binding,
            source_commit=context.source_commit,
            actor_digest=actor_digest,
            output=approval_path,
        )
        approval = load_genesis_approval(
            approval_path,
            run_binding=context.run_binding,
            source_commit=context.source_commit,
        )
        if (
            approval is None
            or not approval.authorizes("entra-config", plan_digest=plan.digest)
            or approval.actor_digest != actor_digest
        ):
            raise ValueError("Entra-only exact approval is invalid")
        _revalidate_before_claim(
            context=context,
            target=target,
            controls=controls,
            snapshot_directory=snapshot_directory,
            observation=observation,
            human_id=human_id,
            plan=plan,
            actor_digest=actor_digest,
        )
        approval_principal_digest = hashlib.sha256(human_id.casefold().encode()).hexdigest()
        with executor_execution_context(target) as execution_actor_digest:
            _revalidate_executor_context(
                context=context,
                target=target,
                controls=controls,
                plan=plan,
                execution_actor_digest=execution_actor_digest,
            )
            claim = claim_record(
                context,
                observation,
                plan,
                actor_digest,
                approval_principal_digest,
                execution_actor_digest,
            )
            write_private_output(
                claim_path,
                json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
            )
            apply_entra_bounded(plan)
            readback = _verify_readback(plan=plan)
            receipt = _terminal_receipt(
                receipt_path=receipt_path,
                context=context,
                observation=observation,
                plan=plan,
                approval_actor_digest=actor_digest,
                approval_principal_digest=approval_principal_digest,
                execution_actor_digest=execution_actor_digest,
                readback=readback,
                recovered_from_claim=False,
            )
        return _result_from_receipt(observation, receipt)


def _revalidate_before_claim(
    *,
    context: OperationContext,
    target: EntraTargetProfile,
    controls: EntraControlProfile,
    snapshot_directory: Path,
    observation: IdentityProfileObservation,
    human_id: str,
    plan: EntraPlan,
    actor_digest: str,
) -> None:
    verify_source_snapshot(snapshot_directory, expected_digest=context.snapshot_digest)
    if azure_active_target_binding() != context.target_binding:
        raise ValueError("active Azure target changed after approval")
    if current_actor_digest(context.run_binding) != actor_digest:
        raise ValueError("Entra-only authenticated human changed after approval")
    fresh_observation, fresh_human_id = observe_identity_profile(target, controls)
    if (
        not fresh_observation.ready
        or fresh_observation.digest != observation.digest
        or fresh_human_id != human_id
    ):
        raise ValueError("Entra identity control profile changed after approval")
    if (
        plan_entra(
            bounded=True,
            approved_role_groups=controls.role_groups,
        )
        != plan
    ):
        raise ValueError("bounded Entra app/group plan changed after approval")


def _verify_readback(
    *,
    plan: EntraPlan,
) -> EntraEffectReadback:
    return read_entra_effects(plan=plan)


def _revalidate_executor_context(
    *,
    context: OperationContext,
    target: EntraTargetProfile,
    controls: EntraControlProfile,
    plan: EntraPlan,
    execution_actor_digest: str,
) -> None:
    if execution_actor_digest != context.executor_digest:
        raise ValueError("authenticated Entra executor does not match the operation context")
    if azure_active_target_binding() != context.target_binding:
        raise ValueError("executor Azure target does not match the approved target")
    if (
        plan_entra(
            bounded=True,
            approved_role_groups=controls.role_groups,
        )
        != plan
    ):
        raise ValueError("bounded Entra app/group plan changed under the executor identity")
    if target.digest != context.target_profile_digest:
        raise ValueError("Entra executor target profile changed before mutation")


def _terminal_receipt(
    *,
    receipt_path: Path,
    context: OperationContext,
    observation: IdentityProfileObservation,
    plan: EntraPlan,
    approval_actor_digest: str,
    approval_principal_digest: str,
    execution_actor_digest: str,
    readback: EntraEffectReadback,
    recovered_from_claim: bool,
) -> dict[str, object]:
    return write_receipt(
        receipt_path=receipt_path,
        context=context,
        observation=observation,
        plan=plan.projection(),
        plan_digest=plan.digest,
        approval_actor_digest=approval_actor_digest,
        approval_principal_digest=approval_principal_digest,
        execution_actor_digest=execution_actor_digest,
        readback_digest=readback.evidence_digest,
        effects=readback.projection(),
        recovered_from_claim=recovered_from_claim,
    )


def _retained_plan(
    value: dict[str, object],
    approved_role_groups: dict[str, str],
) -> EntraPlan:
    plan = value.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("retained Entra plan is unavailable")
    apps, groups, digest = (
        plan.get("create_apps"),
        plan.get("create_groups"),
        plan.get("plan_digest"),
    )
    role_groups = tuple(sorted(approved_role_groups.items()))
    binding_digest = canonical_digest({"role_groups": dict(role_groups)})
    if (
        not isinstance(apps, list)
        or any(not isinstance(item, str) for item in apps)
        or not isinstance(groups, list)
        or any(not isinstance(item, str) for item in groups)
        or not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or plan.get("role_group_binding_digest") != binding_digest
    ):
        raise ValueError("retained Entra plan is invalid")
    return EntraPlan(
        create_apps=tuple(apps),
        create_groups=tuple(groups),
        configure_roles=True,
        configure_runner_graph=False,
        digest=digest,
        role_groups=role_groups,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    environment = "unknown"
    try:
        target = load_target_profile_descriptor(
            _descriptor_from_environment("FDAI_ENTRA_TARGET_PROFILE_FD")
        )
        controls = load_control_profile_descriptor(
            _descriptor_from_environment("FDAI_ENTRA_CONTROL_PROFILE_FD")
        )
        environment = target.environment
        snapshot_directory, snapshot_digest = _snapshot_from_environment()
        result = run_entra_operation(
            work_dir=args.work_dir,
            target=target,
            controls=controls,
            snapshot_directory=snapshot_directory,
            snapshot_digest=snapshot_digest,
            apply=args.apply,
        )
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
        TimeoutError,
    ):
        result = {
            "schema_version": "fdai.genesis-entra-only-result.v2",
            "state": "incomplete",
            "environment": environment,
            "blockers": ["entra_operation_incomplete"],
            "approval_verified": False,
            "claim_recorded": False,
            "readback_verified": False,
            "provider_admin_consent_granted": False,
            "runner_directory_authority_granted": False,
            "foundation_invoked": False,
            "application_invoked": False,
            "mutation_performed": None,
            "subscription_ready": False,
        }
    if args.output == "json":
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(f"state={result['state']}")
        for blocker in result.get("blockers", []):
            print(f"blocker={blocker}")
    return 0 if result["state"] in {"observed", "applied"} else 3


if __name__ == "__main__":
    raise SystemExit(main())

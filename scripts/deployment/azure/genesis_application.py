#!/usr/bin/env python3
"""Drive protected application plan, approval, apply, and convergence in one process."""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.github_actions import (
    DeploymentSelection,
    dispatch_apply,
    dispatch_plan,
    run_github_cli,
    workflow_status,
)
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.profile import load_profile
from genesis_approval import GenesisApprovalExpiredError, load_genesis_approval
from genesis_approval_prompt import create_approval


@dataclass(frozen=True, slots=True)
class ApplicationConfig:
    """Exact protected deployment inputs retained by the supervised process."""

    repository: str
    source_commit: str
    run_id: str
    run_binding: str
    profile: Path
    work_dir: Path
    actor_digest: str
    selection: DeploymentSelection | None = None
    timeout_seconds: int = 10_800


def run_application(config: ApplicationConfig) -> dict[str, object]:
    """Run or resume standard application deployment through verified no-change closure."""

    profile = load_profile(config.profile)
    selection = config.selection or DeploymentSelection()
    state_path = config.work_dir / "application-status.json"
    state = _read_state(state_path)
    if state and (
        state.get("schema_version") != "fdai.genesis-application-status.v1"
        or state.get("source_commit") != config.source_commit
        or state.get("run_binding") != config.run_binding
    ):
        raise ValueError("application status context differs")
    if "plan_dispatch" not in state:
        dispatch = dispatch_plan(
            repository=config.repository,
            environment=profile.environment,
            commit_sha=config.source_commit,
            target_binding=profile.target_binding,
            region=profile.region,
            run_id=config.run_id,
            selection=selection,
            attempt=1,
        )
        state.update(
            {
                "schema_version": "fdai.genesis-application-status.v1",
                "source_commit": config.source_commit,
                "run_binding": config.run_binding,
                "plan_dispatch": dispatch.to_mapping(),
            }
        )
        _write_state(state_path, state)
    plan_dispatch = _mapping(state["plan_dispatch"], "application plan dispatch")
    plan_status = _wait_for_workflow(
        repository=config.repository,
        request_id=str(plan_dispatch["request_id"]),
        expected_commit=config.source_commit,
        context_digest=str(plan_dispatch["context_digest"]),
        target_binding=profile.target_binding,
        region=profile.region,
        timeout_seconds=config.timeout_seconds,
    )
    plan = _mapping(plan_status.get("plan"), "application plan")
    if plan.get("expired") is True and "apply_dispatch" not in state:
        raise ValueError("protected application plan expired before approval")
    state["plan"] = plan
    _write_state(state_path, state)
    plan_reference_digest = canonical_digest({"plan_id": plan["plan_id"]})
    evidence = {
        "context_digest": str(plan["context_digest"]),
        "plan_digest": str(plan["plan_digest"]),
        "plan_reference_digest": plan_reference_digest,
    }
    if "apply_dispatch" not in state:
        approval_digest = _approval_digest(config, plan, evidence)
        dispatch = dispatch_apply(
            repository=config.repository,
            environment=profile.environment,
            commit_sha=config.source_commit,
            target_binding=profile.target_binding,
            region=profile.region,
            approval_quorum=profile.approval_quorum,
            run_id=f"{config.run_id}.{approval_digest[:16]}",
            plan_id=str(plan["plan_id"]),
            plan_digest=str(plan["plan_digest"]),
            plan_expires_at=str(plan["expires_at"]),
            resume_verification=False,
            selection=selection,
            attempt=1,
        )
        state["apply_dispatch"] = dispatch.to_mapping()
        state["approval_digest"] = approval_digest
        _write_state(state_path, state)
    approval_digest_value = state.get("approval_digest")
    if not isinstance(approval_digest_value, str) or len(approval_digest_value) != 64:
        raise ValueError("application approval digest is unavailable")
    approval_digest = approval_digest_value
    apply_dispatch = _mapping(state["apply_dispatch"], "application apply dispatch")
    apply_status = _wait_for_workflow(
        repository=config.repository,
        request_id=str(apply_dispatch["request_id"]),
        expected_commit=config.source_commit,
        context_digest=str(apply_dispatch["context_digest"]),
        target_binding=profile.target_binding,
        region=profile.region,
        timeout_seconds=config.timeout_seconds,
        expected_plan_id=str(plan["plan_id"]),
        expected_plan_digest=str(plan["plan_digest"]),
        allow_failure=True,
    )
    if apply_status.get("conclusion") != "success":
        if "resume_dispatch" not in state:
            resume = dispatch_apply(
                repository=config.repository,
                environment=profile.environment,
                commit_sha=config.source_commit,
                target_binding=profile.target_binding,
                region=profile.region,
                approval_quorum=profile.approval_quorum,
                run_id=f"{config.run_id}.{approval_digest[:16]}.verification",
                plan_id=str(plan["plan_id"]),
                plan_digest=str(plan["plan_digest"]),
                plan_expires_at=str(plan["expires_at"]),
                resume_verification=True,
                selection=selection,
                attempt=2,
            )
            state["resume_dispatch"] = resume.to_mapping()
            _write_state(state_path, state)
        resume_dispatch = _mapping(
            state["resume_dispatch"], "application verification-resume dispatch"
        )
        apply_status = _wait_for_workflow(
            repository=config.repository,
            request_id=str(resume_dispatch["request_id"]),
            expected_commit=config.source_commit,
            context_digest=str(resume_dispatch["context_digest"]),
            target_binding=profile.target_binding,
            region=profile.region,
            timeout_seconds=config.timeout_seconds,
            expected_plan_id=str(plan["plan_id"]),
            expected_plan_digest=str(plan["plan_digest"]),
            resume_verification=True,
        )
    apply_receipt = _mapping(apply_status.get("apply_receipt"), "application apply receipt")
    state["apply_receipt"] = apply_receipt
    _write_state(state_path, state)
    if "convergence_dispatch" not in state:
        dispatch = dispatch_plan(
            repository=config.repository,
            environment=profile.environment,
            commit_sha=config.source_commit,
            target_binding=profile.target_binding,
            region=profile.region,
            run_id=f"{config.run_id}.convergence",
            selection=selection,
            attempt=2,
        )
        state["convergence_dispatch"] = dispatch.to_mapping()
        _write_state(state_path, state)
    convergence_dispatch = _mapping(
        state["convergence_dispatch"], "application convergence dispatch"
    )
    convergence_status = _wait_for_workflow(
        repository=config.repository,
        request_id=str(convergence_dispatch["request_id"]),
        expected_commit=config.source_commit,
        context_digest=str(convergence_dispatch["context_digest"]),
        target_binding=profile.target_binding,
        region=profile.region,
        timeout_seconds=config.timeout_seconds,
    )
    convergence = _mapping(convergence_status.get("plan"), "application convergence plan")
    _require_no_change(_mapping(convergence.get("plan_summary"), "convergence summary"))
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-application-verification-receipt.v1",
        "state": "verified",
        "source_commit": config.source_commit,
        "run_binding": config.run_binding,
        "application_approval_digest": approval_digest,
        "application_plan_digest": plan["plan_digest"],
        "application_apply_evidence_digest": canonical_digest(apply_receipt),
        "initial_inventory_execution_receipt_digest": apply_receipt[
            "initial_inventory_execution_receipt_digest"
        ],
        "convergence_plan_digest": convergence["plan_digest"],
        "convergence_summary_digest": _mapping(convergence["plan_summary"], "convergence summary")[
            "summary_digest"
        ],
        "terraform_zero_change_verified": True,
        "migration_stage_verified": True,
        "runtime_health_verified": True,
        "canary_verified": True,
        "initial_inventory_execution_succeeded": True,
        "active_inventory_generation_verified": False,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    receipt_path = config.work_dir / "application-verification-receipt.json"
    if receipt_path.exists():
        if _read_private_json(receipt_path, "application verification receipt") != receipt:
            raise ValueError("application verification receipt changed on resume")
    else:
        write_private_output(
            receipt_path,
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        )
    state["state"] = "verified"
    state["receipt_digest"] = receipt["receipt_digest"]
    _write_state(state_path, state)
    return receipt


def ensure_container_supply_chain(
    *, repository: str, source_commit: str, timeout_seconds: int = 5400
) -> None:
    """Require one successful exact-main image publication, dispatching it when absent."""

    deadline = time.monotonic() + timeout_seconds
    dispatched = False
    while True:
        result = run_github_cli(
            (
                "run",
                "list",
                "--repo",
                repository,
                "--workflow",
                "container-supply-chain.yml",
                "--commit",
                source_commit,
                "--limit",
                "20",
                "--json",
                "databaseId,status,conclusion,headSha",
            )
        )
        if result.returncode != 0:
            raise ValueError("container supply-chain status is unavailable")
        runs = json.loads(result.stdout)
        exact = [row for row in runs if row.get("headSha") == source_commit]
        if any(
            row.get("status") == "completed" and row.get("conclusion") == "success" for row in exact
        ):
            return
        failed = [
            row
            for row in exact
            if row.get("status") == "completed" and row.get("conclusion") != "success"
        ]
        active = [row for row in exact if row.get("status") != "completed"]
        if failed and not active:
            raise ValueError("exact container supply-chain run failed")
        if not exact and not dispatched:
            dispatch = run_github_cli(
                (
                    "workflow",
                    "run",
                    "container-supply-chain.yml",
                    "--repo",
                    repository,
                    "--ref",
                    "main",
                    "--field",
                    f"commit_sha={source_commit}",
                )
            )
            if dispatch.returncode != 0:
                raise ValueError("container supply-chain dispatch failed")
            dispatched = True
        if time.monotonic() >= deadline:
            raise TimeoutError("container supply-chain deadline exceeded")
        sys.stderr.write(".")
        sys.stderr.flush()
        time.sleep(15)


def _approval_digest(
    config: ApplicationConfig,
    plan: dict[str, Any],
    evidence: dict[str, str],
) -> str:
    """Create or validate the current exact application approval before dispatch."""

    approval_path = config.work_dir / "application-approval.json"
    approval = None
    if approval_path.exists():
        try:
            approval = load_genesis_approval(
                approval_path,
                run_binding=config.run_binding,
                source_commit=config.source_commit,
            )
        except GenesisApprovalExpiredError:
            approval_path.unlink()
    if approval is None:
        _print_plan(plan)
        create_approval(
            stage="application-apply",
            evidence=evidence,
            run_binding=config.run_binding,
            source_commit=config.source_commit,
            actor_digest=config.actor_digest,
            output=approval_path,
        )
        approval = load_genesis_approval(
            approval_path,
            run_binding=config.run_binding,
            source_commit=config.source_commit,
        )
    if approval is None or not approval.authorizes("application-apply", **evidence):
        raise ValueError("application approval does not match the exact protected plan")
    return canonical_digest(
        load_json_object(
            read_private_bytes(approval_path, max_bytes=65_536),
            label="application approval",
            max_bytes=65_536,
        )
    )


def _wait_for_workflow(
    *,
    repository: str,
    request_id: str,
    expected_commit: str,
    context_digest: str,
    target_binding: str,
    region: str,
    timeout_seconds: int,
    expected_plan_id: str | None = None,
    expected_plan_digest: str | None = None,
    resume_verification: bool = False,
    allow_failure: bool = False,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            value = workflow_status(
                repository=repository,
                request_id_value=request_id,
                expected_commit=expected_commit,
                expected_context_digest=context_digest,
                target_binding=target_binding,
                expected_region=region,
                resume_verification=resume_verification,
                expected_plan_id=expected_plan_id,
                expected_plan_digest=expected_plan_digest,
            )
        except ValueError as exc:
            if str(exc) != "github_workflow_run_not_found":
                raise
            value = {"status": "queued", "conclusion": None}
        if value.get("status") == "completed":
            if value.get("conclusion") != "success" and not allow_failure:
                raise ValueError("protected deployment workflow failed")
            return value
        if time.monotonic() >= deadline:
            raise TimeoutError("protected deployment workflow deadline exceeded")
        sys.stderr.write(".")
        sys.stderr.flush()
        time.sleep(15)


def _print_plan(plan: dict[str, Any]) -> None:
    summary = _mapping(plan.get("plan_summary"), "application plan summary")
    print(
        json.dumps(
            {
                "plan_id": plan["plan_id"],
                "plan_digest": plan["plan_digest"],
                "expires_at": plan["expires_at"],
                "plan_summary": summary,
                "post_apply_observations": plan["post_apply_observations"],
            },
            indent=2,
            sort_keys=True,
        ),
        file=sys.stderr,
    )


def _require_no_change(summary: dict[str, Any]) -> None:
    actions = _mapping(summary.get("action_counts"), "convergence action counts")
    if any(actions.get(name) != 0 for name in ("create", "update", "delete", "replace")):
        raise ValueError("second protected plan is not zero-change")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_private_json(path, "application status")


def _read_private_json(path: Path, label: str) -> dict[str, Any]:
    return dict(
        load_json_object(
            read_private_bytes(path, max_bytes=1_048_576),
            label=label,
            max_bytes=1_048_576,
        )
    )


def _write_state(path: Path, value: dict[str, Any]) -> None:
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}"
    write_private_output(
        temporary,
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
    )
    if path.exists():
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
            temporary.unlink()
            raise PermissionError("application status is not a private regular file")
    os.replace(temporary, path)
    path.chmod(0o600)

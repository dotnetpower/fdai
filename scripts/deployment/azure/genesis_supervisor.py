#!/usr/bin/env python3
"""Supervise one exact-source private Azure Genesis run from login to convergence."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import genesis_foundation_apply as foundation_apply
from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.plan_input import read_plan_input
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from genesis_application import (
    ApplicationConfig,
    ensure_container_supply_chain,
    run_application,
)
from genesis_approval import GenesisApprovalExpiredError, load_genesis_approval
from genesis_approval_prompt import create_approval, current_actor_digest
from genesis_entra import apply_entra, plan_entra, read_entra_bindings
from genesis_images import resolve_exact_images
from genesis_prepare import PreparedGenesis, prepare_genesis
from genesis_repository_config import (
    apply_repository_config,
    create_repository_config_plan,
)

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_COMMIT = re.compile(r"[0-9a-f]{40}")


def supervise(
    *,
    repository_root: Path,
    repository: str,
    region: str,
    monthly_cost_ceiling: int,
    work_dir: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    """Advance every checkpoint, prompting only for the exact current effect."""

    source_commit, subscription_id, tenant_id = _preflight(
        repository_root=repository_root,
        repository=repository,
    )
    prepared = prepare_genesis(
        repository_root=repository_root,
        repository=repository,
        source_commit=source_commit,
        tenant_id=tenant_id,
        subscription_id=subscription_id,
        region=region,
        monthly_cost_ceiling=monthly_cost_ceiling,
        root=work_dir,
    )
    actor_digest = current_actor_digest(prepared.run_binding)
    status = _run_foundation_loop(
        repository_root=repository_root,
        repository=repository,
        subscription_id=subscription_id,
        tenant_id=tenant_id,
        region=region,
        prepared=prepared,
        actor_digest=actor_digest,
        timeout_seconds=timeout_seconds,
    )
    entra_bindings = _configure_entra(
        prepared=prepared,
        status=status,
        actor_digest=actor_digest,
    )
    ensure_container_supply_chain(
        repository=repository,
        source_commit=source_commit,
        timeout_seconds=min(timeout_seconds, 5400),
    )
    repository_receipt = _configure_repository(
        repository_root=repository_root,
        repository=repository,
        prepared=prepared,
        status=status,
        actor_digest=actor_digest,
        image_refs=resolve_exact_images(repository, source_commit),
        entra_bindings=entra_bindings,
    )
    application_receipt = run_application(
        ApplicationConfig(
            repository=repository,
            source_commit=source_commit,
            run_id=str(status["run_id"]),
            run_binding=prepared.run_binding,
            profile=prepared.profile,
            work_dir=prepared.root,
            actor_digest=actor_digest,
            timeout_seconds=timeout_seconds,
        )
    )
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-supervised-terminal-receipt.v1",
        "state": "application-converged",
        "source_commit": source_commit,
        "run_binding": prepared.run_binding,
        "target_binding": prepared.target_binding,
        "foundation_status_digest": canonical_digest(status),
        "repository_config_receipt_digest": repository_receipt["receipt_digest"],
        "application_receipt_digest": application_receipt["receipt_digest"],
        "application_converged": True,
        "initial_inventory_execution_succeeded": True,
        "active_inventory_generation_verified": False,
        "complete_manifest_verified": False,
        "model_capacity_verified": False,
        "subscription_ready": False,
        "mutation_performed": True,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    terminal_path = prepared.root / "terminal-receipt.json"
    if terminal_path.exists():
        if _private_json(terminal_path, "terminal receipt") != receipt:
            raise ValueError("Genesis terminal receipt changed on resume")
    else:
        write_private_output(
            terminal_path,
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        )
    return receipt


def _preflight(*, repository_root: Path, repository: str) -> tuple[str, str, str]:
    """Require a clean exact protected main checkout and current human Azure login."""

    if _REPOSITORY.fullmatch(repository) is None:
        raise ValueError("Genesis repository must be owner/name")
    _required(("git", "fetch", "origin", "main"), cwd=repository_root, timeout=300)
    source_commit = _capture(("git", "rev-parse", "HEAD"), cwd=repository_root)
    origin_main = _capture(("git", "rev-parse", "origin/main"), cwd=repository_root)
    branch = _capture(("git", "branch", "--show-current"), cwd=repository_root)
    dirty = _capture(("git", "status", "--porcelain", "--untracked-files=all"), cwd=repository_root)
    if (
        _COMMIT.fullmatch(source_commit) is None
        or source_commit != origin_main
        or branch != "main"
        or dirty
    ):
        raise ValueError("Genesis requires a clean checkout at exact origin/main")
    remote = _capture(("git", "remote", "get-url", "origin"), cwd=repository_root)
    normalized = remote.removesuffix(".git")
    detected = (
        normalized.split("github.com/", 1)[1]
        if "github.com/" in normalized
        else normalized.split("github.com:", 1)[1]
    )
    if detected.casefold() != repository.casefold():
        raise ValueError("Genesis repository differs from the origin remote")
    check_runs = json.loads(
        _capture(
            (
                "gh",
                "api",
                "-X",
                "GET",
                f"repos/{repository}/commits/{source_commit}/check-runs"
                "?check_name=required&filter=latest&per_page=100",
            ),
            cwd=repository_root,
        )
    )
    required = check_runs.get("check_runs") if isinstance(check_runs, dict) else None
    exact = [
        item
        for item in required or []
        if isinstance(item, dict)
        and item.get("name") == "required"
        and item.get("head_sha") == source_commit
        and isinstance(item.get("id"), int)
    ]
    exact.sort(key=lambda item: int(item["id"]))
    if (
        not exact
        or exact[-1].get("status") != "completed"
        or exact[-1].get("conclusion") != "success"
        or not isinstance(exact[-1].get("app"), dict)
        or exact[-1]["app"].get("slug") != "github-actions"
    ):
        raise ValueError("exact origin/main required CI is not green")
    account = json.loads(
        _capture(
            (
                "az",
                "account",
                "show",
                "--query",
                "{subscription_id:id,tenant_id:tenantId,user_type:user.type}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            cwd=repository_root,
        )
    )
    if not isinstance(account, dict) or account.get("user_type") != "user":
        raise ValueError("Genesis requires an authenticated Azure human")
    return source_commit, str(account["subscription_id"]), str(account["tenant_id"])


def _run_foundation_loop(
    *,
    repository_root: Path,
    repository: str,
    subscription_id: str,
    tenant_id: str,
    region: str,
    prepared: PreparedGenesis,
    actor_digest: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run the existing router repeatedly and create only its current exact approval."""

    status_path = prepared.root / "status.json"
    approval_path = prepared.root / "current-foundation-approval.json"
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = int(deadline - time.monotonic())
        if remaining < 1800:
            raise TimeoutError("Genesis Foundation deadline has insufficient remaining budget")
        if approval_path.exists():
            try:
                load_genesis_approval(
                    approval_path,
                    run_binding=prepared.run_binding,
                    source_commit=prepared.source_commit,
                )
            except GenesisApprovalExpiredError:
                approval_path.unlink()
        command = (
            str(repository_root / ".venv/bin/python"),
            str(repository_root / "scripts/deployment/azure/genesis_orchestrator.py"),
            "--repository",
            repository,
            "--environment",
            "dev",
            "--region",
            region,
            "--apply",
            "--allow-probe-resources",
            "--work-dir",
            str(prepared.root),
            "--foundation-offline-kit",
            str(prepared.stage / "kit"),
            "--foundation-release-root",
            str(prepared.stage / "release-root.pub"),
            "--foundation-bundle-public-key",
            str(prepared.stage / "bundle-key.pub"),
            "--foundation-profile",
            str(prepared.profile),
            "--foundation-variables-file",
            str(prepared.variables),
            "--create-runner-image",
            "--runner-image-terraform",
            str(prepared.stage / "kit/terraform/terraform"),
            "--runner-ssh-private-key",
            str(prepared.ssh_private_key),
            *(("--approval-file", str(approval_path)) if approval_path.exists() else ()),
            "--execution-timeout-seconds",
            str(min(14400, remaining)),
            "--output",
            "json",
        )
        completed = subprocess.run(
            command,
            cwd=repository_root,
            env={
                **os.environ,
                "PYTHONPATH": (
                    f"{repository_root / 'packages/deployment-cli/src'}:"
                    f"{repository_root / 'scripts/deployment/azure'}"
                ),
                "AZURE_SUBSCRIPTION_ID": subscription_id,
                "AZURE_TENANT_ID": tenant_id,
            },
            check=False,
            timeout=min(14400, remaining),
        )
        status = _private_json(status_path, "Genesis status")
        if status.get("current_stage") == "application-plan" and {
            "foundation-state",
        } <= set(status.get("completed_stages", [])):
            return status
        if completed.returncode != 2:
            raise ValueError("Genesis Foundation orchestration failed")
        stage, evidence = _approval_from_status(status)
        approval_path.unlink(missing_ok=True)
        create_approval(
            stage=stage,
            evidence=evidence,
            run_binding=prepared.run_binding,
            source_commit=prepared.source_commit,
            actor_digest=actor_digest,
            output=approval_path,
        )
        if time.monotonic() >= deadline:
            raise TimeoutError("Genesis Foundation deadline exceeded")


def _configure_repository(
    *,
    repository_root: Path,
    repository: str,
    prepared: PreparedGenesis,
    status: dict[str, Any],
    actor_digest: str,
    image_refs: dict[str, str],
    entra_bindings: dict[str, str],
) -> dict[str, object]:
    """Plan, approve, apply, and independently read back repository configuration."""

    report = status.get("foundation_report")
    foundation_plan = report.get("foundation_plan") if isinstance(report, dict) else None
    if not isinstance(foundation_plan, dict) or not isinstance(
        foundation_plan.get("plan_ref"), str
    ):
        raise ValueError("Foundation plan reference is unavailable")
    plan_directory = prepared.root / str(foundation_plan["plan_ref"])
    plan = create_repository_config_plan(
        repository=repository,
        source_commit=prepared.source_commit,
        handoff=_private_json(plan_directory / foundation_apply.HANDOFF_NAME, "Foundation handoff"),
        foundation_variables=read_plan_input(prepared.variables),
        preflight_template=json.loads(
            (repository_root / "config/deployment-preflight-template.json").read_text(
                encoding="utf-8"
            )
        ),
        image_refs=image_refs,
        entra_bindings=entra_bindings,
    )
    plan_path = prepared.root / "repository-config-plan.json"
    plan_projection = {
        "schema_version": "fdai.genesis-repository-config-plan.v1",
        "plan_digest": plan.digest,
        "variable_names": sorted(plan.variables),
        "required_existing_variables": list(plan.required_existing_variables),
        "required_secret_names": list(plan.required_secrets),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    if plan_path.exists():
        if _private_json(plan_path, "repository configuration plan") != plan_projection:
            raise ValueError("repository configuration plan changed")
    else:
        write_private_output(
            plan_path,
            json.dumps(plan_projection, sort_keys=True, separators=(",", ":")) + "\n",
        )
    receipt_path = prepared.root / "repository-config-receipt.json"
    if receipt_path.exists():
        receipt = _private_json(receipt_path, "repository configuration receipt")
        if (
            receipt.get("plan_digest") != plan.digest
            or receipt.get("readback_verified") is not True
        ):
            raise ValueError("repository configuration receipt is invalid")
        return receipt
    approval_path = prepared.root / "repository-config-approval.json"
    if approval_path.exists():
        approval_path.unlink()
    print(json.dumps(plan_projection, indent=2, sort_keys=True), file=sys.stderr)
    create_approval(
        stage="repository-config",
        evidence={"plan_digest": plan.digest},
        run_binding=prepared.run_binding,
        source_commit=prepared.source_commit,
        actor_digest=actor_digest,
        output=approval_path,
    )
    approval = load_genesis_approval(
        approval_path,
        run_binding=prepared.run_binding,
        source_commit=prepared.source_commit,
    )
    if approval is None or not approval.authorizes("repository-config", plan_digest=plan.digest):
        raise ValueError("repository configuration approval is invalid")
    return apply_repository_config(
        repository=repository,
        plan=plan,
        actor_digest=actor_digest,
        receipt_path=receipt_path,
    )


def _configure_entra(
    *,
    prepared: PreparedGenesis,
    status: dict[str, Any],
    actor_digest: str,
) -> dict[str, str]:
    """Plan, approve, apply, and reobserve tenant-local identity bindings."""

    receipt_path = prepared.root / "entra-config-receipt.json"
    if receipt_path.exists():
        receipt = _private_json(receipt_path, "Entra configuration receipt")
        bindings = receipt.get("bindings")
        observed = read_entra_bindings()
        if (
            receipt.get("schema_version") != "fdai.genesis-entra-receipt.v1"
            or receipt.get("state") != "applied"
            or not isinstance(bindings, dict)
            or bindings != observed
        ):
            raise ValueError("Entra configuration receipt differs from current readback")
        return {str(key): str(value) for key, value in observed.items()}
    claim_path = prepared.root / "entra-config-claim.json"
    if claim_path.exists():
        retained_claim = _private_json(claim_path, "Entra configuration claim")
        if (
            retained_claim.get("schema_version") != "fdai.genesis-entra-claim.v1"
            or retained_claim.get("source_commit") != prepared.source_commit
            or retained_claim.get("run_binding") != prepared.run_binding
        ):
            raise ValueError("Entra configuration claim context is invalid")
        try:
            bindings = read_entra_bindings()
        except ValueError as exc:
            raise ValueError(
                "claimed Entra configuration is incomplete; automatic retry is blocked"
            ) from exc
        _write_entra_receipt(
            receipt_path=receipt_path,
            plan_digest=str(retained_claim["plan_digest"]),
            actor_digest=str(retained_claim["actor_digest"]),
            bindings=bindings,
            mutation_performed=True,
        )
        return bindings
    report = status.get("foundation_report")
    foundation_plan = report.get("foundation_plan") if isinstance(report, dict) else None
    if not isinstance(foundation_plan, dict) or not isinstance(
        foundation_plan.get("plan_ref"), str
    ):
        raise ValueError("Foundation plan reference is unavailable for Entra configuration")
    handoff = _private_json(
        prepared.root / str(foundation_plan["plan_ref"]) / foundation_apply.HANDOFF_NAME,
        "Foundation handoff",
    )
    runner = handoff.get("runner")
    runner_principal = runner.get("principal_id") if isinstance(runner, dict) else None
    if not isinstance(runner_principal, str):
        raise ValueError("Foundation runner principal is unavailable")
    plan = plan_entra()
    projection = plan.projection()
    print(json.dumps(projection, indent=2, sort_keys=True), file=sys.stderr)
    approval_path = prepared.root / "entra-config-approval.json"
    approval_path.unlink(missing_ok=True)
    create_approval(
        stage="entra-config",
        evidence={"plan_digest": plan.digest},
        run_binding=prepared.run_binding,
        source_commit=prepared.source_commit,
        actor_digest=actor_digest,
        output=approval_path,
    )
    approval = load_genesis_approval(
        approval_path,
        run_binding=prepared.run_binding,
        source_commit=prepared.source_commit,
    )
    if approval is None or not approval.authorizes("entra-config", plan_digest=plan.digest):
        raise ValueError("Entra configuration approval is invalid")
    claim: dict[str, object] = {
        "schema_version": "fdai.genesis-entra-claim.v1",
        "state": "applying",
        "source_commit": prepared.source_commit,
        "run_binding": prepared.run_binding,
        "plan_digest": plan.digest,
        "actor_digest": actor_digest,
        "idempotency_key": canonical_digest(
            {"run_binding": prepared.run_binding, "plan_digest": plan.digest}
        ),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    write_private_output(
        claim_path,
        json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
    )
    bindings = apply_entra(plan, runner_principal_id=runner_principal)
    _write_entra_receipt(
        receipt_path=receipt_path,
        plan_digest=plan.digest,
        actor_digest=actor_digest,
        bindings=bindings,
        mutation_performed=True,
    )
    return bindings


def _write_entra_receipt(
    *,
    receipt_path: Path,
    plan_digest: str,
    actor_digest: str,
    bindings: dict[str, str],
    mutation_performed: bool,
) -> None:
    """Persist one content-addressed private Entra terminal receipt."""

    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-entra-receipt.v1",
        "state": "applied",
        "plan_digest": plan_digest,
        "actor_digest": actor_digest,
        "bindings": bindings,
        "readback_verified": True,
        "mutation_performed": mutation_performed,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    write_private_output(
        receipt_path,
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
    )


def _approval_from_status(status: dict[str, Any]) -> tuple[str, dict[str, str]]:
    report = status.get("foundation_report")
    if not isinstance(report, dict):
        raise ValueError("Genesis status has no Foundation report")
    current = status.get("current_stage")
    names: tuple[str, ...]
    if current == "runner-image-apply":
        stage, source = "runner-image", report.get("runner_image_plan")
        names = ("review_digest", "plan_digest")
    elif current == "foundation-apply":
        stage, source = "foundation-apply", report.get("foundation_plan")
        names = ("review_digest", "plan_digest")
    elif current == "runner-enrollment":
        stage, source = "runner-enrollment", report.get("foundation_apply")
        names = ("receipt_digest",)
    elif current == "foundation-state":
        foundation = report.get("foundation_apply")
        enrollment = report.get("runner_enrollment")
        if not isinstance(foundation, dict) or not isinstance(enrollment, dict):
            raise ValueError("Foundation state-handoff evidence is unavailable")
        return "foundation-state", {
            "foundation_receipt_digest": str(foundation["receipt_digest"]),
            "enrollment_receipt_digest": str(enrollment["receipt_digest"]),
        }
    else:
        raise ValueError("Genesis is not waiting at an approval checkpoint")
    if not isinstance(source, dict):
        raise ValueError("Genesis checkpoint evidence is unavailable")
    if stage == "runner-enrollment":
        return stage, {"foundation_receipt_digest": str(source["receipt_digest"])}
    return stage, {name: str(source[name]) for name in names}


def _private_json(path: Path, label: str) -> dict[str, Any]:
    return dict(
        load_json_object(
            read_private_bytes(path, max_bytes=1_048_576),
            label=label,
            max_bytes=1_048_576,
        )
    )


def _required(arguments: tuple[str, ...], *, cwd: Path, timeout: int) -> None:
    completed = subprocess.run(
        arguments, cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout
    )
    if completed.returncode != 0:
        raise ValueError("Genesis prerequisite command failed")


def _capture(arguments: tuple[str, ...], *, cwd: Path) -> str:
    completed = subprocess.run(
        arguments, cwd=cwd, check=False, capture_output=True, text=True, timeout=120
    )
    if completed.returncode != 0:
        raise ValueError("Genesis prerequisite query failed")
    return completed.stdout.strip()


def main() -> int:
    """Parse one operator invocation and emit a truthful terminal receipt."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--region", default="koreacentral")
    parser.add_argument("--monthly-cost-ceiling", type=int, default=1000)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=14_400)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[3]
    if not 1800 <= args.timeout_seconds <= 43_200:
        raise ValueError("Genesis timeout must be from 1800 through 43200 seconds")
    work_dir = args.work_dir or repository_root / ".fdai/deploy/fdai-up"
    work_dir = work_dir if work_dir.is_absolute() else repository_root / work_dir
    try:
        result = supervise(
            repository_root=repository_root,
            repository=args.repository,
            region=args.region,
            monthly_cost_ceiling=args.monthly_cost_ceiling,
            work_dir=work_dir,
            timeout_seconds=args.timeout_seconds,
        )
    except TimeoutError:
        print("fdai-up: supervised deployment deadline exceeded", file=sys.stderr)
        return 3
    except (OSError, ValueError, subprocess.SubprocessError):
        print("fdai-up: supervised deployment stopped at a failed safety gate", file=sys.stderr)
        return 4
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Command line for the governed observer installation: apply, activate, roll back, or export."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import ObserverDeploymentProposal

from fdai.delivery.kubernetes_connector_apply import (
    AksRunCommandTransport,
    KubectlTransport,
    KubeTransport,
    ObserverApplyApproval,
    activate_observer,
    apply_observer_installation,
    await_first_observation,
    deactivate_observer,
    rollback_observer_installation,
)
from fdai.delivery.kubernetes_connector_approval import (
    SignedObserverApproval,
    load_approver_grants,
    sign_approval,
    verify_signed_approval,
)
from fdai.delivery.kubernetes_connector_installation import (
    ObserverInstallationInput,
    render_observer_installation,
)
from fdai.delivery.kubernetes_connector_lifecycle import (
    retire_observer_stream,
    uninstall_observer,
    verify_observer,
)
from fdai.delivery.kubernetes_connector_runtime import private_file

APPROVAL_SECONDS = 600
MAX_APPROVAL_SECONDS = 1800
_STOPPING = frozenset({"deactivate", "recover", "rollback", "uninstall"})
_FAILED_STATES = frozenset(
    {"image_pull_failed", "job_failed", "completed_without_delivery", "not_finished"}
)
_FAILED_RESULTS = _FAILED_STATES | {"install_failed_deactivated"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "apply",
            "activate",
            "verify",
            "deactivate",
            "recover",
            "rollback",
            "uninstall",
            "export",
            "wait-observed",
            "sign-approval",
            "install",
        ),
    )
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--proposal", type=Path)
    parser.add_argument("--material-directory", type=Path)
    parser.add_argument("--cluster-uid", help="kube-system namespace UID from the signed preflight")
    parser.add_argument("--approver", help="accountable human reference recorded in the audit")
    parser.add_argument(
        "--approve-recipe-digest",
        help="apply, activate, or verify: the stable recipe digest printed by the dry-run",
    )
    parser.add_argument(
        "--signed-approval", type=Path, help="approval signed by an enrolled approver"
    )
    parser.add_argument("--approval-grants", type=Path, help="deployment-owned approver grants")
    parser.add_argument("--executor-ref", help="identity running this command; not the approver")
    parser.add_argument("--signing-key", type=Path, help="sign-approval: approver Ed25519 key")
    parser.add_argument("--sign-operation", help="sign-approval: the operation to approve")
    parser.add_argument("--approval-seconds", type=int, default=APPROVAL_SECONDS)
    parser.add_argument(
        "--development-self-approval",
        action="store_true",
        help="single-operator development profile only: approve with this invocation's flags",
    )
    parser.add_argument(
        "--approve-target-ref",
        help="deactivate, recover, rollback, or uninstall: type the target reference to confirm",
    )
    parser.add_argument("--audit-file", type=Path)
    parser.add_argument("--lock-directory", type=Path)
    parser.add_argument("--output-directory", type=Path, help="export: GitOps manifest directory")
    parser.add_argument("--kubeconfig", type=Path, help="existing_host or managed_host")
    parser.add_argument("--tools-directory", type=Path, help="directory with kubectl and kubelogin")
    parser.add_argument("--subscription-id", help="run_command")
    parser.add_argument("--resource-group", help="run_command")
    parser.add_argument("--cluster-name", help="run_command")
    parser.add_argument("--timeout-seconds", type=float, default=600.0, help="wait-observed")
    return parser


def _need(value: Any, option: str) -> Any:
    if value is None or value == "":
        raise ValueError(f"--{option} is required for this operation")
    return value


def _transport(inputs: ObserverInstallationInput, args: argparse.Namespace) -> KubeTransport:
    """Select the transport the proposal pinned; never substitute another path."""
    if inputs.method == "run_command":
        return AksRunCommandTransport(
            subscription_id=_need(args.subscription_id, "subscription-id"),
            resource_group=_need(args.resource_group, "resource-group"),
            cluster_name=_need(args.cluster_name, "cluster-name"),
        )
    if inputs.method in {"existing_host", "managed_host"}:
        return KubectlTransport(
            kubeconfig=_need(args.kubeconfig, "kubeconfig"), tools=args.tools_directory
        )
    raise ValueError("the gitops method does not apply to a cluster; use the export operation")


def _audit_sink(path: Path) -> Callable[[dict[str, object]], None]:
    def write(record: dict[str, object]) -> None:
        line = (json.dumps(record, sort_keys=True) + "\n").encode()
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            os.write(descriptor, line)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    return write


def _render(
    args: argparse.Namespace, now: datetime
) -> tuple[ObserverInstallationInput, dict[str, Any]]:
    inputs = ObserverInstallationInput.model_validate_json(
        private_file(_need(args.inputs, "inputs"))
    )
    proposal = ObserverDeploymentProposal.model_validate_json(
        private_file(_need(args.proposal, "proposal"))
    )
    rendered = render_observer_installation(
        inputs,
        proposal,
        now=now,
        material_directory=_need(args.material_directory, "material-directory"),
    )
    return inputs, rendered


def _approval(
    args: argparse.Namespace,
    inputs: ObserverInstallationInput,
    rendered: dict[str, Any] | None,
    *,
    operation: str,
    now: datetime,
) -> ObserverApplyApproval:
    """Resolve the approval: signed by an enrolled approver, or development self-approval."""
    if args.signed_approval is not None:
        return verify_signed_approval(
            SignedObserverApproval.model_validate_json(private_file(args.signed_approval)),
            grants=load_approver_grants(_need(args.approval_grants, "approval-grants")),
            executor_ref=_need(args.executor_ref, "executor-ref"),
            now=now,
        )
    if not args.development_self_approval:
        raise ValueError(
            "this operation requires --signed-approval from an enrolled approver; "
            "--development-self-approval is only for the single-operator development profile"
        )
    return _issue(args, inputs, rendered, operation=operation, now=now)


def _issue(
    args: argparse.Namespace,
    inputs: ObserverInstallationInput,
    rendered: dict[str, Any] | None,
    *,
    operation: str,
    now: datetime,
) -> ObserverApplyApproval:
    bound: dict[str, object] = {}
    if rendered is not None:
        bound = {"recipe_digest": rendered["recipe_digest"]}
    seconds = min(max(int(args.approval_seconds), 1), MAX_APPROVAL_SECONDS)
    return ObserverApplyApproval.model_validate(
        {
            "operation": operation,
            "approver_ref": _need(args.approver, "approver"),
            "target_ref": inputs.target_ref,
            "cluster_uid": _need(args.cluster_uid, "cluster-uid"),
            "method": inputs.method,
            "namespace": inputs.namespace,
            "name": inputs.name,
            "inputs_digest": canonical_digest(inputs.model_dump(mode="json")),
            "approved_at": now,
            "expires_at": now + timedelta(seconds=seconds),
            **bound,
        }
    )


def _mode(args: argparse.Namespace) -> str:
    return "signed" if args.signed_approval is not None else "development_self_issued"


def _sign(args: argparse.Namespace, now: datetime) -> dict[str, object]:
    """Sign one approval as an enrolled approver; the reviewed digest or target must be typed."""
    operation = _need(args.sign_operation, "sign-operation")
    inputs = ObserverInstallationInput.model_validate_json(
        private_file(_need(args.inputs, "inputs"))
    )
    rendered = None
    if operation in _STOPPING:
        if args.approve_target_ref != inputs.target_ref:
            raise ValueError("sign-approval requires --approve-target-ref equal to the target")
    else:
        _, rendered = _render(args, now)
        if args.approve_recipe_digest != rendered["recipe_digest"]:
            raise ValueError("sign-approval requires --approve-recipe-digest equal to the recipe")
    signed = sign_approval(
        _issue(args, inputs, rendered, operation=operation, now=now),
        executor_ref=_need(args.executor_ref, "executor-ref"),
        signing_key=_need(args.signing_key, "signing-key"),
    )
    return {"state": "approval_signed", "signed_approval": signed.model_dump(mode="json")}


def _install(
    args: argparse.Namespace,
    inputs: ObserverInstallationInput,
    rendered: dict[str, Any],
    common: dict[str, Any],
    clock: Callable[[], datetime],
) -> dict[str, object]:
    """Single-operator install: apply, activate, then smoke-verify; stop safely on failure.

    The operator approves one reviewed recipe digest up front. Each step still gets its own
    short-lived approval, claim, and audit record. A failed or unverified smoke run suspends the
    observer again instead of leaving an unproven installation active.
    """
    if not args.development_self_approval:
        raise ValueError(
            "install is the single-operator flow and needs --development-self-approval; "
            "use apply, activate, and verify with signed approvals otherwise"
        )
    if args.approve_recipe_digest is None:
        raise ValueError("install requires --approve-recipe-digest from the dry-run")
    transport = _transport(inputs, args)
    steps: dict[str, object] = {}
    steps["apply"] = apply_observer_installation(
        rendered,
        inputs,
        _issue(args, inputs, rendered, operation="apply", now=clock()),
        transport=transport,
        material_directory=_need(args.material_directory, "material-directory"),
        cluster_uid=_need(args.cluster_uid, "cluster-uid"),
        **common,
    )
    steps["activate"] = activate_observer(
        rendered,
        inputs,
        _issue(args, inputs, rendered, operation="activate", now=clock()),
        transport=transport,
        **common,
    )
    verified = verify_observer(
        rendered,
        inputs,
        _issue(args, inputs, rendered, operation="verify", now=clock()),
        transport=transport,
        **common,
    )
    steps["verify"] = verified
    state = str(verified["state"])
    if state in _FAILED_STATES:
        steps["deactivate"] = deactivate_observer(
            inputs,
            _issue(args, inputs, None, operation="deactivate", now=clock()),
            transport=transport,
            **common,
        )
        state = "install_failed_deactivated"
    return {
        "schema_version": "1.0.0",
        "operation": "install",
        "state": state,
        "approval_mode": "development_self_issued",
        "recipe_digest": rendered["recipe_digest"],
        "steps": {name: _brief(value) for name, value in steps.items()},
        "operational_success": False,
        "observation_required": True,
    }


def _brief(value: object) -> object:
    return (
        {key: value[key] for key in ("state", "operation") if key in value}
        if isinstance(value, dict)
        else value
    )


def _export(args: argparse.Namespace, now: datetime) -> dict[str, object]:
    inputs, rendered = _render(args, now)
    if inputs.method != "gitops":
        raise ValueError("export is only for the gitops method")
    directory = _need(args.output_directory, "output-directory")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    for index, document in enumerate(rendered["documents"], start=1):
        name = f"{index:02d}-{document['kind'].lower()}.json"
        descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
    return {
        "state": "exported",
        "directory": str(directory),
        "manifest_digest": rendered["manifest_digest"],
        "secret_included": False,
        "execution_authority": False,
    }


async def _wait(args: argparse.Namespace, target_ref: str) -> dict[str, object]:
    from fdai.delivery.kubernetes_connector_observed import build_observer_evidence
    from fdai.delivery.kubernetes_connector_runtime import validate_connector_database_venue
    from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig

    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "")
    if not dsn:
        raise ValueError("observation needs the service-owned FDAI_STATE_STORE_DSN")
    validate_connector_database_venue(dsn)
    observing = build_observer_evidence(
        PostgresStateStore(
            config=PostgresStateStoreConfig(dsn=dsn, connect_timeout_s=3, statement_timeout_ms=5000)
        ),
        now=lambda: datetime.now(UTC),
    )
    if observing is None:
        raise ValueError("observation needs FDAI_OBSERVER_REGISTRATIONS_PATH")
    loop = asyncio.get_running_loop()
    observed = await await_first_observation(
        observing,
        target_ref,
        timeout_s=args.timeout_seconds,
        interval_s=15.0,
        sleep=asyncio.sleep,
        monotonic=loop.time,
    )
    return {
        "state": "observed" if observed else "not_observed_yet",
        "operational_success": observed,
    }


def run(args: argparse.Namespace, *, now: datetime | None = None) -> dict[str, object]:
    fixed = now

    def clock() -> datetime:
        return fixed if fixed is not None else datetime.now(UTC)

    now = clock()
    if args.operation == "export":
        return _export(args, now)
    if args.operation == "wait-observed":
        inputs = ObserverInstallationInput.model_validate_json(
            private_file(_need(args.inputs, "inputs"))
        )
        return asyncio.run(_wait(args, inputs.target_ref))
    if args.operation == "sign-approval":
        return _sign(args, now)
    common: dict[str, Any] = {
        "lock_directory": _need(args.lock_directory, "lock-directory"),
        "audit": _audit_sink(_need(args.audit_file, "audit-file")),
        "now": clock,
    }
    if args.operation in _STOPPING:
        inputs = ObserverInstallationInput.model_validate_json(
            private_file(_need(args.inputs, "inputs"))
        )
        if args.approve_target_ref != inputs.target_ref:
            raise ValueError(
                f"{args.operation} requires --approve-target-ref equal to the target reference"
            )
        stop_approval = _approval(args, inputs, None, operation=args.operation, now=now)
        handlers = {
            "deactivate": deactivate_observer,
            "recover": retire_observer_stream,
            "rollback": rollback_observer_installation,
            "uninstall": uninstall_observer,
        }
        stopped = handlers[args.operation](
            inputs, stop_approval, transport=_transport(inputs, args), **common
        )
        return {**stopped, "approval_mode": _mode(args)}
    inputs, rendered = _render(args, now)
    approved = args.signed_approval is not None or args.approve_recipe_digest is not None
    if args.approve_recipe_digest is not None and (
        args.approve_recipe_digest != rendered["recipe_digest"]
    ):
        raise ValueError("the approved recipe digest differs from the current rendered recipe")
    if args.operation == "install":
        return _install(args, inputs, rendered, common, clock)
    if args.operation in {"activate", "verify"}:
        if not approved:
            raise ValueError(
                f"{args.operation} requires --signed-approval or --approve-recipe-digest"
            )
        handler = activate_observer if args.operation == "activate" else verify_observer
        outcome = handler(
            rendered,
            inputs,
            _approval(args, inputs, rendered, operation=args.operation, now=now),
            transport=_transport(inputs, args),
            **common,
        )
        return {**outcome, "approval_mode": _mode(args)}
    approval = _approval(args, inputs, rendered, operation="apply", now=now) if approved else None
    installed = apply_observer_installation(
        rendered,
        inputs,
        approval,
        transport=_transport(inputs, args),
        material_directory=args.material_directory,
        cluster_uid=_need(args.cluster_uid, "cluster-uid"),
        **common,
    )
    return {**installed, "approval_mode": _mode(args)} if approval is not None else installed


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run(args)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result.get("state") in _FAILED_RESULTS else 0
    except (KeyboardInterrupt, SystemExit):
        raise
    except ValueError as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}), file=sys.stderr)
        return 1
    except Exception:
        print(
            json.dumps({"status": "unavailable", "reason": "observer_apply_failed"}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

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
    rollback_observer_installation,
)
from fdai.delivery.kubernetes_connector_installation import (
    ObserverInstallationInput,
    render_observer_installation,
)
from fdai.delivery.kubernetes_connector_runtime import private_file

APPROVAL_SECONDS = 600


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("apply", "activate", "rollback", "export", "wait-observed")
    )
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--proposal", type=Path)
    parser.add_argument("--material-directory", type=Path)
    parser.add_argument("--cluster-uid", help="kube-system namespace UID from the signed preflight")
    parser.add_argument("--approver", help="accountable human reference recorded in the audit")
    parser.add_argument(
        "--approve-manifest-digest",
        help="apply or activate: the exact manifest digest printed by the dry-run",
    )
    parser.add_argument(
        "--approve-target-ref", help="rollback: type the target reference to confirm removal"
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
    bound: dict[str, object] = {}
    if rendered is not None:
        bound = {
            "proposal_digest": rendered["proposal_digest"],
            "manifest_digest": rendered["manifest_digest"],
        }
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
            "expires_at": now + timedelta(seconds=APPROVAL_SECONDS),
            **bound,
        }
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
    common: dict[str, Any] = {
        "lock_directory": _need(args.lock_directory, "lock-directory"),
        "audit": _audit_sink(_need(args.audit_file, "audit-file")),
        "now": clock,
    }
    if args.operation == "rollback":
        inputs = ObserverInstallationInput.model_validate_json(
            private_file(_need(args.inputs, "inputs"))
        )
        if args.approve_target_ref != inputs.target_ref:
            raise ValueError("rollback requires --approve-target-ref equal to the target reference")
        return rollback_observer_installation(
            inputs,
            _approval(args, inputs, None, operation="rollback", now=now),
            transport=_transport(inputs, args),
            **common,
        )
    inputs, rendered = _render(args, now)
    approved = args.approve_manifest_digest is not None
    if approved and args.approve_manifest_digest != rendered["manifest_digest"]:
        raise ValueError("the approved manifest digest differs from the current rendered manifest")
    if args.operation == "activate":
        if not approved:
            raise ValueError("activation requires --approve-manifest-digest")
        return activate_observer(
            rendered,
            inputs,
            _approval(args, inputs, rendered, operation="activate", now=now),
            transport=_transport(inputs, args),
            **common,
        )
    approval = _approval(args, inputs, rendered, operation="apply", now=now) if approved else None
    return apply_observer_installation(
        rendered,
        inputs,
        approval,
        transport=_transport(inputs, args),
        material_directory=args.material_directory,
        cluster_uid=_need(args.cluster_uid, "cluster-uid"),
        **common,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print(json.dumps(run(args), indent=2, sort_keys=True))
        return 0
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

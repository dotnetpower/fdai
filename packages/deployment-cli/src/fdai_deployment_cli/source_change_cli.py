"""CLI adapters for changed-source planning, execution, and timing evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai_deployment_cli.deployment_progress import DeploymentProgress
from fdai_deployment_cli.private_output import write_private_output
from fdai_deployment_cli.source_change_plan import plan_git_changes
from fdai_deployment_cli.source_changed_update import deploy_changed_source
from fdai_deployment_cli.source_service_update import deploy_source_service_update
from fdai_deployment_cli.source_service_update_cli import source_service_update_inputs

PrintMapping = Callable[..., None]


def provision_plan(args: argparse.Namespace, print_mapping: PrintMapping) -> int:
    result = plan_git_changes(args.source, args.base, args.head)
    print_mapping(
        result,
        output=args.output,
        text=(
            f"source change lane: {result['lane']}; "
            f"reason={result['reason_code']}; no deployment performed"
        ),
    )
    return 0


def provision_update(
    args: argparse.Namespace,
    print_mapping: PrintMapping,
    *,
    deploy: Callable[..., dict[str, object]] = deploy_changed_source,
) -> int:
    result = deploy(
        source_root=args.source,
        base=args.base,
        application_work_dir=args.application_work_dir,
        work_dir=args.work_dir,
        timeout_seconds=args.timeout_seconds,
    )
    services = result.get("services")
    if not isinstance(services, list) or any(not isinstance(item, str) for item in services):
        raise ValueError("source changed update returned an invalid service list")
    print_mapping(
        result,
        output=args.output,
        text=f"source changed update: {result['state']}; services={','.join(services) or 'none'}",
    )
    return 0 if result["state"] in {"applied", "no-deploy"} else 2


def provision_service_update(args: argparse.Namespace) -> int:
    source, application, selected, development_profile, clear_development_profile = (
        source_service_update_inputs(args)
    )
    result = deploy_source_service_update(
        source_root=source,
        application_work_dir=application,
        work_dir=selected,
        service=args.service,
        timeout_seconds=args.timeout_seconds,
        adopt_historical_binding=args.adopt_historical_binding,
        adopt_historical_state=args.adopt_historical_state,
        adopt_historical_variables=args.adopt_historical_variables,
        adopt_historical_live=args.adopt_historical_live,
        adopt_historical_plan=args.adopt_historical_plan,
        development_authority_profile=development_profile,
        clear_development_authority_profile=clear_development_profile,
    )
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else f"source service update applied: {result['service']} at {result['source_commit']}"
    )
    return 0


def attach_timing(
    result: Mapping[str, Any],
    *,
    progress: DeploymentProgress,
    work_dir: Path,
) -> dict[str, Any]:
    timing = progress.timing_receipt(
        lane="source-install",
        outcome=str(result.get("state", "unknown")),
        recorded_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    timing_directory = work_dir / "timing"
    timing_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    timing_path = timing_directory / f"{timing['receipt_digest']}.json"
    if not timing_path.exists():
        write_private_output(
            timing_path,
            json.dumps(timing, sort_keys=True, separators=(",", ":")) + "\n",
        )
    return {**result, "timing_receipt_digest": timing["receipt_digest"]}


__all__ = ["attach_timing", "provision_plan", "provision_service_update", "provision_update"]

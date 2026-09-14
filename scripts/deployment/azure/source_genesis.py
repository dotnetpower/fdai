#!/usr/bin/env python3
"""Prepare source-bound Foundation inputs without building a deployment kit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest
from fdai_deployment_cli.plan_input import read_plan_input, write_plan_input
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.profile import load_profile, write_profile
from fdai_deployment_cli.source_input import inspect_source
from fdai_deployment_cli.standalone_deploy import active_azure_target
from fdai_deployment_cli.target import compute_target_binding
from genesis_prepare import _ensure_ed25519_key, _ensure_ssh_public_key, _private_directory
from genesis_prepare_inputs import foundation_values


def prepare(args: argparse.Namespace) -> dict[str, object]:
    """Persist exact target/source inputs and an SSH key, never an artifact-signing key."""
    source = inspect_source(Path(__file__).resolve().parents[3], expected_commit=args.source_commit)
    target = active_azure_target()
    binding = compute_target_binding(
        tenant_id=target.tenant_id, subscription_id=target.subscription_id
    )
    if binding != args.target_binding:
        raise ValueError("source Foundation target changed after preflight")
    root = args.work_dir.absolute()
    _private_directory(root)
    profile = ProvisionProfile(
        environment="dev",
        region=args.region,
        target_binding=binding,
        connectivity="online",
        host="managed-vm",
        transport="manual",
        access_method="bastion",
        shadow_only=True,
        approval_quorum=1,
        monthly_cost_ceiling=args.monthly_cost_ceiling,
    )
    profile_path = root / "profile.json"
    if profile_path.exists():
        if load_profile(profile_path) != profile:
            raise ValueError("source Foundation profile differs from retained input")
    else:
        write_profile(profile_path, profile)
    run_binding = canonical_digest(
        {
            "target_binding": binding,
            "source_input_digest": source.digest,
            "region": args.region,
            "provenance": "operator-selected-source",
        }
    )
    ssh_key = root / "runner_ed25519"
    _ensure_ed25519_key(ssh_key, openssh=True)
    _ensure_ssh_public_key(ssh_key, root / "runner_ed25519.pub")
    variables = root / "foundation-variables.json"
    if variables.exists():
        values = read_plan_input(variables)
        if (
            values.get("source_commit") != source.commit
            or values.get("run_digest") != run_binding
            or values.get("target_binding") != binding
        ):
            raise ValueError("source Foundation retained variables differ")
    else:
        values = foundation_values(
            repository_root=source.root,
            source_commit=source.commit,
            tenant_id=target.tenant_id,
            subscription_id=target.subscription_id,
            region=args.region,
            target_binding=binding,
            run_binding=run_binding,
            ssh_public_key=read_private_bytes(root / "runner_ed25519.pub", max_bytes=16384)
            .decode("ascii")
            .strip(),
            execution_transport="manual",
            evidence_directory=root,
        )
        write_plan_input(variables, values)
    source.reverify()
    result = {
        "schema_version": "fdai.source-genesis-preparation.v1",
        "state": "prepared",
        "source_commit": source.commit,
        "source_input_digest": source.digest,
        "target_binding": binding,
        "run_binding": run_binding,
        "mutation_performed": False,
        "deployment_ready": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    marker = root / "source-genesis.json"
    data = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    if not marker.exists():
        write_private_bytes(marker, data)
    elif read_private_bytes(marker, max_bytes=65536) != data:
        raise ValueError("source Foundation preparation receipt differs")
    return result


def main() -> int:
    """Return only sanitized preparation evidence; no Terraform apply is reachable."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--target-binding", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--monthly-cost-ceiling", type=int, required=True)
    try:
        print(json.dumps(prepare(parser.parse_args()), sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError):
        print("source Foundation preparation failed; preserve retained evidence", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

"""Command line for private Hub-managed installation preparation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from fdai_lifecycle_manager.operations import (
    write_agent_tfvars,
    write_catalog_requests,
    write_native_acceptance,
)
from fdai_lifecycle_manager.preparation import prepare_installation


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fdai-lifecycle-manager")
    command = parser.add_subparsers(dest="command", required=True)
    prepare = command.add_parser("prepare")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--destination", type=Path, required=True)
    prepare.add_argument("--runtime-bundle", type=Path, required=True)
    prepare.add_argument("--component-images", type=Path, required=True)
    prepare.add_argument("--hub-public-key", type=Path, required=True)
    prepare.add_argument("--release-public-key", type=Path, required=True)
    prepare.add_argument("--installation-id", required=True)
    prepare.add_argument("--entity-id", required=True)
    prepare.add_argument("--product", required=True)
    prepare.add_argument("--release-id", required=True)
    prepare.add_argument("--channel", default="DEV")
    prepare.add_argument("--region", required=True)
    prepare.add_argument("--actor", required=True)
    catalog = command.add_parser("catalog-requests")
    catalog.add_argument("--prepared", type=Path, required=True)
    catalog.add_argument("--publication-receipt", type=Path, required=True)
    acceptance = command.add_parser("native-acceptance")
    acceptance.add_argument("--prepared", type=Path, required=True)
    acceptance.add_argument("--proof", type=Path, required=True)
    tfvars = command.add_parser("agent-tfvars")
    tfvars.add_argument("--prepared", type=Path, required=True)
    tfvars.add_argument("--destination", type=Path, required=True)
    tfvars.add_argument("--subscription-id", required=True)
    tfvars.add_argument("--tenant-id", required=True)
    tfvars.add_argument("--location", required=True)
    tfvars.add_argument("--resource-group", required=True)
    tfvars.add_argument("--prefix", required=True)
    tfvars.add_argument("--kubeconfig", required=True)
    tfvars.add_argument("--kube-context", required=True)
    tfvars.add_argument("--oidc-issuer", required=True)
    tfvars.add_argument("--hub-url", required=True)
    tfvars.add_argument("--hub-api-client-id", required=True)
    tfvars.add_argument("--hub-agent-role-id", required=True)
    tfvars.add_argument("--agent-image", required=True)
    tfvars.add_argument("--enable-agent", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            receipt = prepare_installation(
                source_root=args.source,
                destination=args.destination,
                runtime_bundle_path=args.runtime_bundle,
                component_images_path=args.component_images,
                hub_public_key_path=args.hub_public_key,
                release_public_key_path=args.release_public_key,
                installation_id=args.installation_id,
                entity_id=args.entity_id,
                product=args.product,
                release_id=args.release_id,
                channel=args.channel,
                region=args.region,
                actor=args.actor,
                now=datetime.now(UTC),
            ).model_dump(mode="json")
        elif args.command == "catalog-requests":
            imported, recompute = write_catalog_requests(
                args.prepared,
                args.publication_receipt,
            )
            receipt = {"catalog_import": str(imported), "recompute": str(recompute)}
        elif args.command == "native-acceptance":
            receipt = {"native_acceptance": str(write_native_acceptance(args.prepared, args.proof))}
        else:
            receipt = {
                "agent_tfvars": str(
                    write_agent_tfvars(
                        args.prepared,
                        args.destination,
                        subscription_id=args.subscription_id,
                        tenant_id=args.tenant_id,
                        location=args.location,
                        resource_group_name=args.resource_group,
                        prefix=args.prefix,
                        kubeconfig_path=args.kubeconfig,
                        kubeconfig_context=args.kube_context,
                        cluster_oidc_issuer_url=args.oidc_issuer,
                        hub_url=args.hub_url,
                        hub_api_client_id=args.hub_api_client_id,
                        hub_agent_role_id=args.hub_agent_role_id,
                        agent_image=args.agent_image,
                        enable_agent=args.enable_agent,
                    )
                )
            }
    except (OSError, TypeError, ValueError) as error:
        print(
            f"fdai-lifecycle-manager: preparation rejected ({type(error).__name__})",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

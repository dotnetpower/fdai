"""Command line for private Hub-managed installation preparation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

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
    args = parser.parse_args(argv)
    try:
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
        )
    except (OSError, TypeError, ValueError) as error:
        print(
            f"fdai-lifecycle-manager: preparation rejected ({type(error).__name__})",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(receipt.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

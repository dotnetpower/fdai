"""Select bounded PR packaging checks or explicitly requested candidate images."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/deployment-cli/src"))

from fdai_deployment_cli.image_targets import (  # noqa: E402
    IMAGE_TARGETS,
    ImageTarget,
    matrix_json,
    select_image_targets,
    select_requested_images,
)

__all__ = [
    "IMAGE_TARGETS",
    "ImageTarget",
    "matrix_json",
    "select_image_targets",
    "select_requested_images",
]


def main() -> int:
    """Emit a matrix only after explicit selections or changed paths are validated."""
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", dest="select_all")
    selection.add_argument("--images", help="Comma-separated target/image names, or explicit all")
    selection.add_argument("--packaging-only", action="store_true")
    parser.add_argument("--nul", action="store_true")
    args = parser.parse_args()

    if args.select_all:
        targets = IMAGE_TARGETS
    elif args.images is not None:
        try:
            targets = select_requested_images(args.images)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        separator = b"\0" if args.nul else b"\n"
        paths = [
            value.decode("utf-8") for value in sys.stdin.buffer.read().split(separator) if value
        ]
        targets = select_image_targets(paths, packaging_only=args.packaging_only)

    print(f"matrix={matrix_json(targets)}")
    print(f"has_images={'true' if targets else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

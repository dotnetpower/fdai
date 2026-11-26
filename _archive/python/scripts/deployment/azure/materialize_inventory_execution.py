#!/usr/bin/env python3
"""Build an exact inventory execution template with one reviewed image change."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any

_IMAGE_PATTERN = re.compile(r"^[^/]+/fdai@sha256:[0-9a-f]{64}$")
_COMMAND = ["python", "-m", "fdai.delivery.inventory_sync_cli"]


def materialize_inventory_execution(job: object, *, image: str) -> dict[str, Any]:
    """Return the supported execution override with the reviewed inventory image."""
    if not _IMAGE_PATTERN.fullmatch(image):
        raise ValueError("inventory execution image must be one digest-pinned fdai image")
    if not isinstance(job, dict):
        raise ValueError("inventory Job payload must be an object")
    properties = job.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("inventory Job properties must be an object")
    template = properties.get("template")
    if not isinstance(template, dict):
        raise ValueError("inventory Job template must be an object")
    containers = template.get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        raise ValueError("inventory Job must have exactly one container")
    container = containers[0]
    if not isinstance(container, dict):
        raise ValueError("inventory Job container must be an object")
    if (
        container.get("name") != "inventory"
        or container.get("command") != _COMMAND
        or container.get("args", []) != []
        or not isinstance(container.get("env"), list)
        or not container["env"]
    ):
        raise ValueError("inventory Job no longer matches the reviewed runtime contract")

    execution = {"containers": copy.deepcopy(containers)}
    init_containers = template.get("initContainers")
    if init_containers is not None:
        if not isinstance(init_containers, list):
            raise ValueError("inventory Job init containers must be an array")
        execution["initContainers"] = copy.deepcopy(init_containers)
    execution["containers"][0]["image"] = image
    return execution


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-json", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    job = json.loads(args.job_json.read_text(encoding="utf-8"))
    execution = materialize_inventory_execution(job, image=args.image)
    args.output.write_text(
        json.dumps(execution, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

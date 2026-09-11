"""Read-only validation for the exact managed image consumed by Foundation."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

from fdai_deployment_cli.contracts import canonical_digest

RunCommand = Callable[..., subprocess.CompletedProcess[str]]


def verify_foundation_runner_image(
    variables: dict[str, object], *, expected_region: str, run: RunCommand = subprocess.run
) -> str:
    """Verify exact image provenance through ARM and return a content-free observation digest.

    This read grants no image, Foundation, apply, or readiness authority. Provider output is
    never returned or included in an error.
    """

    image_id = variables.get("runner_source_image_id")
    source_commit = variables.get("source_commit")
    toolchain_digest = variables.get("runner_image_toolchain_digest")
    if (
        not isinstance(image_id, str)
        or not image_id
        or not isinstance(source_commit, str)
        or not source_commit
        or not isinstance(toolchain_digest, str)
        or not toolchain_digest
    ):
        raise ValueError("Foundation runner image provenance input is incomplete")
    completed = run(
        [
            "az",
            "resource",
            "show",
            "--ids",
            image_id,
            "--query",
            "{id:id,type:type,location:location,provisioningState:properties.provisioningState,managedOsType:properties.storageProfile.osDisk.osType,galleryOsType:properties.storageProfile.osDiskImage.operatingSystem,tags:tags}",
            "--output",
            "json",
            "--only-show-errors",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise ValueError("Foundation runner image is unavailable")
    try:
        observed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Foundation runner image observation is invalid") from exc
    if not isinstance(observed, dict):
        raise ValueError("Foundation runner image observation is invalid")
    tags = observed.get("tags")
    image_type = str(observed.get("type", "")).casefold()
    os_type = observed.get("managedOsType") or observed.get("galleryOsType")
    if (
        str(observed.get("id", "")).casefold() != image_id.casefold()
        or image_type
        not in {
            "microsoft.compute/images",
            "microsoft.compute/galleries/images/versions",
        }
        or str(observed.get("location", "")).casefold() != expected_region.casefold()
        or observed.get("provisioningState") != "Succeeded"
        or str(os_type).casefold() != "linux"
        or not isinstance(tags, dict)
        or tags.get("fdai:source-commit") != source_commit
        or tags.get("fdai:toolchain-digest") != toolchain_digest
    ):
        raise ValueError("Foundation runner image provenance does not match the reviewed input")
    return canonical_digest(
        {
            "schema_version": "fdai.foundation-runner-image-observation.v1",
            "image_id_digest": canonical_digest(image_id.casefold()),
            "image_type": image_type,
            "location": expected_region,
            "provisioning_state": "Succeeded",
            "os_type": "Linux",
            "source_commit": source_commit,
            "toolchain_digest": toolchain_digest,
        }
    )

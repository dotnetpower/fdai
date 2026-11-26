"""Read-only observer image evidence from the existing pinned deployment-kit trust chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.deployment_kit import acquire_deployment_kit
from fdai_deployment_cli.private_output import read_private_bytes


def inspect_observer_artifact(
    *, offline_kit: Path, work_dir: Path, source_commit: str, image_digest: str
) -> dict[str, Any]:
    """Reverify signed local release bytes and exact Core image, never install or import them.

    Trust roots and all kit verification remain deployment-owned. Output is process-local read
    evidence, not a transferable authorization; an enrolled preflight producer signs it separately.
    """
    if re.fullmatch(r"[a-f0-9]{40}", source_commit) is None:
        raise ValueError("observer artifact source revision is invalid")
    if re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest) is None:
        raise ValueError("observer artifact image digest is invalid")
    kit = acquire_deployment_kit(work_dir=work_dir, online=False, offline_kit=offline_kit)
    catalog = kit.runtime.to_mapping()
    if kit.source_commit != source_commit:
        raise ValueError("observer artifact source revision differs from the selected release")
    services = catalog.get("services")
    core = services.get("core-control-plane") if isinstance(services, dict) else None
    if not isinstance(core, dict) or core.get("image_digest") != image_digest:
        raise ValueError("observer image differs from the signed Core release")
    value: dict[str, Any] = {
        "schema_version": "1.0.0",
        "source_commit": source_commit,
        "image_digest": image_digest,
        "platform_tag": kit.runtime.platform_tag,
        "runtime_digest": "sha256:" + kit.runtime.digest,
        "bundle_digest": "sha256:" + kit.bundle_manifest_digest,
        "release_signature_verified": True,
        "execution_authority": False,
    }
    return {
        **value,
        "evidence_digest": "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest(),
    }


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("observer artifact request contains duplicate fields")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    try:
        request = json.loads(
            read_private_bytes(args.request, max_bytes=16384), object_pairs_hook=_unique
        )
        if not isinstance(request, dict) or set(request) != {
            "offline_kit",
            "work_dir",
            "source_commit",
            "image_digest",
        }:
            raise ValueError("observer artifact request is invalid")
        if not all(isinstance(value, str) and value for value in request.values()):
            raise ValueError("observer artifact request values are invalid")
        if (
            not Path(request["offline_kit"]).is_absolute()
            or not Path(request["work_dir"]).is_absolute()
        ):
            raise ValueError("observer artifact paths must be absolute")
        result = inspect_observer_artifact(
            offline_kit=Path(request["offline_kit"]),
            work_dir=Path(request["work_dir"]),
            source_commit=request["source_commit"],
            image_digest=request["image_digest"],
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError):
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "observer_artifact_verification_failed",
                    "execution_authority": False,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Mirror all signed FDAI images, independently observing every imported digest."""

from __future__ import annotations

import re
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.hub_image_trust import HubImageSelection, load_selection
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.source_image_stage import (
    RegistryBuildService,
    SourceImageStageStopped,
    SourceImageTarget,
)


def prepare_host_selection(
    *, path: Path | None, digest: str | None, work_dir: Path
) -> HubImageSelection | None:
    """Retain the independently verified workstation pin, never a host-fetched TOFU key."""
    retained = work_dir / "hub-selection.json"
    if path is None and digest is None:
        if retained.exists():
            raise ValueError("Hub artifact mode cannot change to source or offline kit")
        return None
    if path is None or digest is None:
        raise ValueError("Hub selection and exact digest are both required")
    selection = load_selection(path, digest)
    content = read_private_bytes(path, max_bytes=12 * 1024 * 1024)
    if retained.exists():
        if read_private_bytes(retained, max_bytes=12 * 1024 * 1024) != content:
            raise ValueError("Hub host immutable image selection changed")
    else:
        write_private_bytes(retained, content)
    return load_selection(retained, selection.digest)


def run_hub_image_stage(
    *,
    selection: HubImageSelection,
    target: SourceImageTarget,
    registry: RegistryBuildService,
    work_dir: Path,
) -> dict[str, object]:
    if (
        re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", target.subscription_id) is None
        or re.fullmatch(r"[a-z0-9]{5,50}", target.registry_name) is None
    ):
        raise ValueError("Hub image target is malformed")
    selection = load_selection(selection.path, selection.digest)
    claim = {
        "schema_version": "fdai.hub-image-stage-claim.v1",
        "hub_selection_digest": selection.digest,
        "subscription_id": target.subscription_id,
        "registry_login_server": target.login_server,
        "image_sources": selection.image_sources,
        "artifact_source": "hub-signed-images",
    }
    work_dir.mkdir(mode=0o700, exist_ok=True)
    claim_path, receipt_path = work_dir / "claim.json", work_dir / "receipt.json"
    if claim_path.exists():
        existing = load_json_object(
            read_private_bytes(claim_path, max_bytes=65_536), label="Hub image claim", strict=True
        )
        if existing != claim:
            raise ValueError("Hub image stage target, mode or selection changed")
    else:
        if any(work_dir.iterdir()):
            raise ValueError("Hub image stage cannot adopt another artifact mode")
        write_private_bytes(claim_path, canonical_bytes(claim))
    digests = {name: ref.rsplit("@", 1)[1] for name, ref in selection.image_sources.items()}
    tag = "hub-" + selection.digest[:32]
    existing_receipt = None
    if receipt_path.exists():
        existing_receipt = load_json_object(
            read_private_bytes(receipt_path, max_bytes=65_536),
            label="Hub image receipt",
            strict=True,
        )
        unsigned = {
            key: value for key, value in existing_receipt.items() if key != "receipt_digest"
        }
        if (
            existing_receipt.get("claim_digest") != canonical_digest(claim)
            or existing_receipt.get("receipt_digest") != canonical_digest(unsigned)
            or existing_receipt.get("image_digests") != digests
        ):
            raise ValueError("Hub image receipt binding differs")
    try:
        if existing_receipt is None:
            registry.require_available(target)
            for name, source in sorted(selection.image_sources.items()):
                registry.import_image(target, source=source, image=f"{name}:{tag}")
        for name, digest in sorted(digests.items()):
            for reference in (f"{name}@{digest}", f"{name}:{tag}"):
                if registry.read_digest(target, reference=reference) != digest:
                    raise ValueError("Hub imported image digest readback differs")
    except SourceImageStageStopped as error:
        raise ValueError("Hub image import or observation failed; no builds or fallback") from error
    if existing_receipt is not None:
        return existing_receipt
    receipt = {
        "schema_version": "fdai.hub-image-stage-receipt.v1",
        **selection.metadata(),
        "claim_digest": canonical_digest(claim),
        "source_commit": selection.source_commit,
        "image_sources": selection.image_sources,
        "image_digests": digests,
        "image_refs": {
            name: f"{target.login_server}/{name}@{digest}" for name, digest in digests.items()
        },
        "builder": "none",
        "effect_verified": True,
        "mutation_performed": True,
        "deployment_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    write_private_bytes(receipt_path, canonical_bytes(receipt))
    return receipt

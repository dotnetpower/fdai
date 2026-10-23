"""Derive later exact operation requests from a prepared installation."""

from __future__ import annotations

import base64
import re
from pathlib import Path
from uuid import uuid4

from fdai_deployment_cli.contracts import canonical_bytes, load_json_object
from fdai_deployment_cli.lifecycle_native import (
    NativeOwnershipAcceptance,
    SignedNativeScope,
)
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes

from fdai_lifecycle_manager.preparation import PreparationReceipt

_IMAGE = re.compile(r".+@sha256:[0-9a-f]{64}\Z", re.ASCII)


def write_catalog_requests(prepared: Path, publication_receipt: Path) -> tuple[Path, Path]:
    """Bind exact Release publication readback into import and recompute requests."""

    root, receipt = _prepared(prepared)
    publication = load_json_object(
        read_private_bytes(publication_receipt.absolute(), max_bytes=64 * 1024),
        label="release publication receipt",
        strict=True,
    )
    if (
        publication.get("schema_version") != "fdai.release-publication-receipt.v1"
        or publication.get("release_id") != receipt.release_id
        or publication.get("manifest_digest") != receipt.release_digest
        or publication.get("effect_verified") is not True
        or not isinstance(publication.get("catalog_revision"), int)
        or not isinstance(publication.get("catalog_sha256"), str)
    ):
        raise ValueError("Release publication receipt differs from preparation.")
    revision = publication["catalog_revision"]
    digest = publication["catalog_sha256"]
    import_path = root / "catalog-import-request.json"
    recompute_path = root / "recompute-request.json"
    _write_json(
        import_path,
        {
            "schema_version": "fdai.catalog-import-request.v1",
            "request_id": str(uuid4()),
            "revision": revision,
            "sha256": digest,
            "reason": "Approved exact Hub-managed catalog publication",
            "confirmation": f"approve {revision} {digest}",
        },
    )
    _write_json(
        recompute_path,
        {
            "schema_version": "fdai.lifecycle-recompute-request.v1",
            "request_id": str(uuid4()),
            "installation_id": receipt.installation_id,
            "catalog_revision": revision,
            "catalog_sha256": digest,
        },
    )
    return import_path, recompute_path


def write_native_acceptance(prepared: Path, proof: Path) -> Path:
    """Create the separate operator acceptance request after local native creation."""

    root, receipt = _prepared(prepared)
    signed = SignedNativeScope.model_validate_json(
        read_private_bytes(proof.absolute(), max_bytes=8192)
    )
    if (
        signed.claim.installation_id != receipt.installation_id
        or signed.claim.entity_id != receipt.entity_id
        or signed.claim.product != receipt.product
        or signed.claim.scope_digest != receipt.native_scope_digest
    ):
        raise ValueError("Native proof differs from preparation.")
    request = NativeOwnershipAcceptance(
        request_id=uuid4(),
        expected_settings_digest=receipt.bound_settings_digest,
        proof=signed,
        reason="Approved Hub-managed native workload creation",
        confirmation="",
    )
    request = request.model_copy(update={"confirmation": request.required_confirmation})
    path = root / "native-ownership-acceptance.json"
    _write_json(path, request.model_dump(mode="json"))
    return path


def write_agent_tfvars(
    prepared: Path,
    destination: Path,
    *,
    subscription_id: str,
    tenant_id: str,
    location: str,
    resource_group_name: str,
    prefix: str,
    kubeconfig_path: str,
    kubeconfig_context: str,
    cluster_oidc_issuer_url: str,
    hub_url: str,
    hub_api_client_id: str,
    hub_agent_role_id: str,
    agent_image: str,
    enable_agent: bool,
    native_state_path: Path | None = None,
) -> Path:
    """Write private Terraform inputs without copying the installation private key."""

    root, receipt = _prepared(prepared)
    if _IMAGE.fullmatch(agent_image) is None:
        raise ValueError("Agent image must be digest-pinned.")
    configuration = read_private_bytes(root / "configuration.json", max_bytes=1024 * 1024)
    signature = read_private_bytes(root / "configuration.sig", max_bytes=64)
    if len(signature) != 64:
        raise ValueError("Configuration signature is invalid.")
    native_state = (
        read_private_bytes(native_state_path.absolute(), max_bytes=1024 * 1024).decode("utf-8")
        if native_state_path is not None
        else None
    )
    value = {
        "subscription_id": subscription_id,
        "tenant_id": tenant_id,
        "location": location,
        "resource_group_name": resource_group_name,
        "prefix": prefix,
        "tags": {
            "fdai:managed": "true",
            "fdai:managed-by": "terraform",
            "fdai:layer": "lifecycle-agent",
        },
        "kubeconfig_path": kubeconfig_path,
        "kubeconfig_context": kubeconfig_context,
        "cluster_oidc_issuer_url": cluster_oidc_issuer_url,
        "hub": {
            "url": hub_url,
            "api_client_id": hub_api_client_id,
            "agent_role_id": hub_agent_role_id,
            "signing_key_id": receipt.hub_key_id,
            "signing_epoch": 1,
            "public_key_pem": (root / "hub-public.pem").read_text(encoding="utf-8"),
            "release_key_pem": (root / "release-public.pem").read_text(encoding="utf-8"),
            "config_key_pem": (root / "configuration-public.pem").read_text(encoding="utf-8"),
        },
        "installation": {
            "id": receipt.installation_id,
            "target_namespace": load_json_object(
                read_private_bytes(root / "runtime-bundle.json", max_bytes=64 * 1024),
                label="runtime bundle",
                strict=True,
            )["namespace"],
            "fencing_generation": 1,
            "local_policy_json": (root / "local-policy.json").read_text(encoding="utf-8"),
            "current_state_json": (root / "current-state.json").read_text(encoding="utf-8"),
            "native_approval_json": (root / "native-approval.json").read_text(encoding="utf-8"),
            "native_state_json": native_state,
            "installation_public_key_pem": (root / "installation-public.pem").read_text(
                encoding="utf-8"
            ),
            "configuration_artifact": {
                "digest": receipt.configuration_digest,
                "payload": configuration.decode("utf-8"),
                "signature_base64": base64.b64encode(signature).decode("ascii"),
            },
            "poll_interval_seconds": 5,
        },
        "agent_image": agent_image,
        "enable_agent": enable_agent,
    }
    destination = destination.absolute()
    _write_json(destination, value)
    return destination


def _prepared(path: Path) -> tuple[Path, PreparationReceipt]:
    root = path.absolute()
    receipt = PreparationReceipt.model_validate_json(
        read_private_bytes(root / "preparation-receipt.json", max_bytes=64 * 1024)
    )
    if Path(receipt.destination) != root:
        raise ValueError("Preparation receipt destination differs.")
    return root, receipt


def _write_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"Lifecycle operation output already exists: {path.name}")
    write_private_bytes(path, canonical_bytes(value))


__all__ = [
    "write_agent_tfvars",
    "write_catalog_requests",
    "write_native_acceptance",
]

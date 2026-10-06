"""Source-only inputs for standalone application continuation."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from fdai_service_contracts.product_profile import ObservationDataSource, ProductAddOn

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.source_host_tools import install_kubernetes_tools
from fdai_deployment_cli.source_image_stage import (
    AzureRegistryBuildService,
    SourceImageSnapshot,
    SourceImageStageStopped,
    SourceImageTarget,
    run_source_image_stage,
)
from fdai_deployment_cli.source_receiver import prepare_source_receiver
from fdai_deployment_cli.source_runtime_support import (
    INPUT_NAME,
    install_source_runtime_support,
    prepare_runtime_support_input,
)
from fdai_deployment_cli.source_snapshot import verify_source_snapshot
from fdai_deployment_cli.source_transport import prepare_source_transport
from fdai_deployment_cli.standalone_terraform_environment import source_terraform_configuration
from fdai_deployment_cli.standalone_terraform_environment import (
    terraform_configuration as mirror_terraform_configuration,
)

_PLACEHOLDER_DIGEST = "sha256:" + ("0" * 64)


class Subparsers(Protocol):
    def add_parser(self, name: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class SourceTransferInputs:
    archive: Path
    archive_digest: str
    receiver: Path
    receiver_digest: str
    runtime_support: Path
    runtime_support_digest: str


@dataclass(frozen=True, slots=True)
class SourceHostArtifacts:
    source_commit: str
    artifact_root: Path
    infra: Path
    terraform: Path
    kit_bin: Path
    digest: str


def add_prepare_source_parser(subcommands: Subparsers, handler: object) -> None:
    """Register the managed-host source preparation command."""

    prepare_source = subcommands.add_parser("prepare-source")
    prepare_source.add_argument("--source-snapshot", type=Path, required=True)
    prepare_source.add_argument("--source-snapshot-digest", required=True)
    prepare_source.add_argument("--runtime-support", type=Path, required=True)
    prepare_source.add_argument("--runtime-support-digest", required=True)
    prepare_source.add_argument("--handoff", type=Path, required=True)
    prepare_source.add_argument("--entra", type=Path)
    prepare_source.add_argument("--foundation-adoption", type=Path)
    prepare_source.add_argument("--adoption-state", type=Path)
    prepare_source.add_argument("--adoption-models", type=Path)
    prepare_source.add_argument("--adoption-descriptor", type=Path)
    prepare_source.add_argument("--catalog-review-profile", type=Path)
    prepare_source.add_argument("--catalog-review-private-key", type=Path)
    prepare_source.add_argument("--operational-evidence-verifier-input", type=Path)
    prepare_source.add_argument("--runtime-platform", default="aks")
    prepare_source.add_argument("--database-placement", default="postgres-flex")
    prepare_source.add_argument("--system-node-count", type=int, default=3)
    prepare_source.add_argument("--system-node-sku", default=None)
    prepare_source.add_argument("--user-node-min-count", type=int, default=3)
    prepare_source.add_argument("--user-node-max-count", type=int, default=5)
    prepare_source.add_argument("--user-node-sku", default="Standard_D4as_v5")
    prepare_source.add_argument("--database-sku")
    prepare_source.add_argument(
        "--product-add-on",
        action="append",
        choices=tuple(item.value for item in ProductAddOn),
        default=[],
    )
    prepare_source.add_argument(
        "--observation-source",
        action="append",
        choices=tuple(item.value for item in ObservationDataSource),
        default=[],
    )
    prepare_source.set_defaults(handler=handler)


def placeholder_image_refs(login_server: str, *, include_pgvector: bool) -> dict[str, str]:
    refs = {
        name: f"{login_server}/{name}@{_PLACEHOLDER_DIGEST}"
        for name in (
            "core-control-plane",
            "operator-service",
            "document-ingestion-api",
            "document-processing-worker",
            "isolated-executor",
            "clamav",
        )
    }
    if include_pgvector:
        refs["pgvector"] = f"{login_server}/pgvector@{_PLACEHOLDER_DIGEST}"
    return refs


def source_tree_copy(snapshot_tree: Path, work_dir: Path) -> Path:
    """Return a private working copy of the verified snapshot tree.

    Terraform writes backend and lock files into its roots and Python may write bytecode beside
    migration code. Doing that inside the snapshot would change the file set that later stages
    verify, so every host step that runs from the tree uses this copy instead.
    """
    copy = work_dir / "source-tree"
    if not copy.exists():
        staging = work_dir / ".source-tree-staging"
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(snapshot_tree, staging, symlinks=True)
        staging.chmod(0o700)
        staging.rename(copy)
    elif copy.is_symlink() or not copy.is_dir():
        raise ValueError("source working tree is invalid")
    return copy


def rebind_source_tree(context: dict[str, object], work_dir: Path) -> bool:
    """Move a retained source context's working paths out of the snapshot."""
    if context.get("artifact_source") != "operator-selected-source":
        return False
    snapshot_tree = Path(str(context["source_snapshot"])) / "tree"
    prefix = str(snapshot_tree)
    copy = str(source_tree_copy(snapshot_tree, work_dir))
    changed = False
    for key, value in list(context.items()):
        if isinstance(value, str) and (value == prefix or value.startswith(prefix + "/")):
            context[key] = copy + value[len(prefix) :]
            changed = True
    return changed


def source_host_artifacts(
    *,
    source_snapshot: Path,
    snapshot_digest: str,
    expected_source_commit: str,
    work_dir: Path,
    runtime_support: Path,
    runtime_support_digest: str,
) -> SourceHostArtifacts:
    source_record = verify_source_snapshot(source_snapshot, expected_digest=snapshot_digest)
    source_commit = str(source_record["source_commit"])
    if source_commit != expected_source_commit:
        raise ValueError("Foundation and source snapshot revisions differ")
    artifact_root = source_snapshot / "tree"
    working_tree = source_tree_copy(artifact_root, work_dir)
    install_source_runtime_support(
        work_dir,
        source_root=working_tree,
        archive=runtime_support,
        archive_digest=runtime_support_digest,
        snapshot_digest=snapshot_digest,
    )
    terraform_path = shutil.which("terraform")
    if terraform_path is None:
        raise ValueError("source deployment requires Terraform on the managed host")
    terraform = Path(terraform_path)
    return SourceHostArtifacts(
        source_commit=source_commit,
        artifact_root=artifact_root,
        infra=working_tree / "infra",
        terraform=terraform,
        kit_bin=install_kubernetes_tools(work_dir / "source-tools"),
        digest=snapshot_digest,
    )


def source_transfer_inputs(
    *, prepared_root: Path, source_snapshot: Path, source_snapshot_digest: str
) -> SourceTransferInputs:
    transfer = prepare_source_transport(
        source_snapshot,
        prepared_root,
        snapshot_digest=source_snapshot_digest,
    )
    receiver_digest = prepare_source_receiver(
        source_snapshot,
        prepared_root,
        snapshot_digest=source_snapshot_digest,
    )
    return SourceTransferInputs(
        archive=prepared_root / "source-transfer.tar",
        archive_digest=str(transfer["archive_digest"]),
        receiver=prepared_root / "source-receiver.pyz",
        receiver_digest=receiver_digest,
        runtime_support=prepared_root / INPUT_NAME,
        runtime_support_digest=prepare_runtime_support_input(
            source_snapshot / "tree", prepared_root
        ),
    )


def build_source_console(
    *,
    source_root: Path,
    source_commit: str,
    prepared_root: Path,
    timeout_seconds: int,
) -> tuple[Path, str]:
    from fdai_deployment_cli.console_artifact import build_console_update_artifact

    artifact = build_console_update_artifact(
        source_root=source_root,
        revision=source_commit,
        output_dir=prepared_root / "source-console-artifact",
        timeout_seconds=timeout_seconds,
    )
    return Path(str(artifact["artifact_directory"])) / "console.tar.gz", str(
        artifact["archive_sha256"]
    )


def source_image_import_receipt(
    *, context: dict[str, object], work_dir: Path
) -> tuple[dict[str, object], dict[str, object]]:
    snapshot_path = Path(str(context.get("source_snapshot", "")))
    snapshot_digest = str(context.get("source_snapshot_digest", ""))
    source_record = verify_source_snapshot(snapshot_path, expected_digest=snapshot_digest)
    commit = str(source_record["source_commit"])
    target = SourceImageTarget(
        subscription_id=str(context["subscription_id"]),
        registry_name=str(context["registry_name"]),
    )
    try:
        receipt = run_source_image_stage(
            snapshot=SourceImageSnapshot(
                root=snapshot_path / "tree",
                commit=commit,
                digest=snapshot_digest,
            ),
            target=target,
            builder=AzureRegistryBuildService(),
            work_dir=work_dir / "source-image-stage",
        )
    except SourceImageStageStopped as exc:
        raise ValueError(exc.reason_code) from exc
    image_refs = _mapping(receipt.get("image_refs"), "source image stage receipt")
    context["image_refs"] = image_refs
    result: dict[str, object] = {
        "schema_version": "fdai.source-image-import-receipt.v1",
        "state": "imported",
        "source_image_stage_receipt_digest": receipt["receipt_digest"],
        "image_digests": _mapping(receipt.get("image_digests"), "source image stage receipt"),
        "provenance": "operator-selected-source",
        "release_signature_verified": False,
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    result["receipt_digest"] = canonical_digest(result)
    return result, context


def terraform_configuration(*, source_mode: bool, provider_mirror: Path | None) -> str:
    if source_mode:
        return source_terraform_configuration()
    if provider_mirror is None:
        raise ValueError("signed-kit provider mirror is unavailable")
    return mirror_terraform_configuration(provider_mirror)


def write_source_image_import_receipt(
    *,
    context: dict[str, object],
    work_dir: Path,
    write_json: Any,
) -> dict[str, object]:
    result, updated_context = source_image_import_receipt(context=context, work_dir=work_dir)
    for name, value in (("context.json", updated_context), ("image-import-receipt.json", result)):
        write_json(work_dir / name, value)
    return result


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {str(key): item for key, item in value.items()}

"""Build source-path service images in the deployment registry and bind their digests.

The registry build service builds each baseline service from the pinned source snapshot and
the registry imports each dependency image by its pinned digest, so the source path needs no
container engine and writes no kit, signature, SBOM, or provenance statement. Every image is
read back by digest and by its `sha-<commit>` tag before the receipt binds it. A completed
receipt permits verification only; an interrupted stage repeats its builds, which only rewrite
the stage's own commit tags.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output

SERVICE_ORDER: Final[tuple[str, ...]] = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)
DEPENDENCY_IMAGES: Final[Mapping[str, str]] = {
    "clamav": "docker.io/clamav/clamav@sha256:"
    "0af8760cd96f9ab67d07977af36e155431581a9fe9f0ec8b256c9f855fda183e",
    "pgvector": "docker.io/pgvector/pgvector@sha256:"
    "ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b",
}
UNAVAILABLE: Final = "source_image_builder_unavailable"
FAILED: Final = "source_image_build_failed"
CHANGED: Final = "source_image_stage_inputs_changed"
RECEIPT_SCHEMA: Final = "fdai.source-image-stage-receipt.v1"
CLAIM_SCHEMA: Final = "fdai.source-image-stage-claim.v1"

_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_SUBSCRIPTION = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_REGISTRY = re.compile(r"[a-z0-9]{5,50}")
_MAX_RECORD_BYTES = 1024 * 1024
_BUILD_TIMEOUT_SECONDS = 3600
_IMPORT_TIMEOUT_SECONDS = 1200
_READ_TIMEOUT_SECONDS = 120

_GUIDANCE = {
    UNAVAILABLE: (
        "The deployment registry's build service is unavailable in this subscription. Enable "
        "Azure Container Registry Tasks for the subscription, then rerun the same command."
    ),
    FAILED: (
        "An image build, import, or digest readback failed. Review the registry runs, then "
        "rerun the same command; the stage rewrites only its own commit tags."
    ),
    CHANGED: (
        "This work directory already holds an image stage for different inputs. Rerun with the "
        "original source and target, or start a new work directory."
    ),
}


class SourceImageStageStopped(RuntimeError):
    """Stop before any service apply with a fixed reason code and guidance."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(_GUIDANCE[reason_code])
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class SourceImageTarget:
    """The deployment's own registry; never a shared or publisher registry."""

    subscription_id: str
    registry_name: str

    @property
    def login_server(self) -> str:
        return f"{self.registry_name}.azurecr.io"


@dataclass(frozen=True, slots=True)
class SourceImageSnapshot:
    """A verified, pinned source tree for exactly one commit."""

    root: Path
    commit: str
    digest: str


class RegistryBuildService(Protocol):
    """The registry operations the stage needs; the stage owns ordering and evidence."""

    def require_available(self, target: SourceImageTarget) -> None: ...

    def build(
        self, target: SourceImageTarget, *, context: Path, dockerfile: str, image: str
    ) -> str: ...

    def import_image(self, target: SourceImageTarget, *, source: str, image: str) -> None: ...

    def read_digest(self, target: SourceImageTarget, *, reference: str) -> str: ...


def run_source_image_stage(
    *,
    snapshot: SourceImageSnapshot,
    target: SourceImageTarget,
    builder: RegistryBuildService,
    work_dir: Path,
) -> dict[str, object]:
    """Build, import, and read back every runtime image, or stop before any service apply."""

    _validate(snapshot, target)
    claim = _claim(snapshot, target)
    work_dir.mkdir(mode=0o700, exist_ok=True)
    receipt_path = work_dir / f"source-images-{snapshot.commit}.receipt.json"
    claim_path = work_dir / f"source-images-{snapshot.commit}.claim.json"
    if receipt_path.exists():
        existing = _load(receipt_path)
        unsigned = {key: value for key, value in existing.items() if key != "receipt_digest"}
        if existing.get("claim_digest") != claim["claim_digest"] or existing.get(
            "receipt_digest"
        ) != canonical_digest(unsigned):
            raise SourceImageStageStopped(CHANGED)
        _read_back(builder, target, snapshot.commit, _digests(existing))
        return existing
    builder.require_available(target)
    if claim_path.exists():
        if _load(claim_path) != claim:
            raise SourceImageStageStopped(CHANGED)
    else:
        write_private_output(claim_path, json.dumps(claim, indent=2, sort_keys=True) + "\n")
    digests: dict[str, str] = {}
    for service in SERVICE_ORDER:
        digests[service] = _require_digest(
            builder.build(
                target,
                context=snapshot.root,
                dockerfile=f"services/{service}/docker/Dockerfile",
                image=f"{service}:sha-{snapshot.commit}",
            )
        )
    for name, source in DEPENDENCY_IMAGES.items():
        builder.import_image(target, source=source, image=f"{name}:sha-{snapshot.commit}")
        digests[name] = source.rsplit("@", 1)[1]
    _read_back(builder, target, snapshot.commit, digests)
    receipt: dict[str, object] = {
        "schema_version": RECEIPT_SCHEMA,
        "claim_digest": claim["claim_digest"],
        "source_commit": snapshot.commit,
        "snapshot_digest": snapshot.digest,
        "registry_login_server": target.login_server,
        "image_digests": dict(sorted(digests.items())),
        "image_refs": {
            name: f"{target.login_server}/{name}@{digest}"
            for name, digest in sorted(digests.items())
        },
        "builder": "azure-container-registry-tasks",
        "provenance": "operator-selected-source",
        "release_signature_verified": False,
        "effect_verified": True,
        "mutation_performed": True,
        "deployment_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    write_private_output(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def _validate(snapshot: SourceImageSnapshot, target: SourceImageTarget) -> None:
    if (
        _COMMIT.fullmatch(snapshot.commit) is None
        or _SHA256.fullmatch(snapshot.digest) is None
        or _SUBSCRIPTION.fullmatch(target.subscription_id) is None
        or _REGISTRY.fullmatch(target.registry_name) is None
    ):
        raise ValueError("source image stage inputs are malformed")
    for service in SERVICE_ORDER:
        dockerfile = snapshot.root / "services" / service / "docker" / "Dockerfile"
        if dockerfile.is_symlink() or not dockerfile.is_file():
            raise ValueError(f"source snapshot lacks the {service} Dockerfile")


def _claim(snapshot: SourceImageSnapshot, target: SourceImageTarget) -> dict[str, object]:
    claim: dict[str, object] = {
        "schema_version": CLAIM_SCHEMA,
        "source_commit": snapshot.commit,
        "snapshot_digest": snapshot.digest,
        "subscription_id": target.subscription_id,
        "registry_login_server": target.login_server,
        "services": list(SERVICE_ORDER),
        "dependency_images": dict(sorted(DEPENDENCY_IMAGES.items())),
    }
    claim["claim_digest"] = canonical_digest(claim)
    return claim


def _load(path: Path) -> dict[str, object]:
    data = read_private_bytes(path, max_bytes=_MAX_RECORD_BYTES)
    return dict(load_json_object(data, label=path.name, max_bytes=_MAX_RECORD_BYTES))


def _digests(receipt: Mapping[str, object]) -> dict[str, str]:
    raw = receipt.get("image_digests")
    expected = set(SERVICE_ORDER) | set(DEPENDENCY_IMAGES)
    if not isinstance(raw, dict) or set(raw) != expected:
        raise SourceImageStageStopped(CHANGED)
    return {str(name): _require_digest(value) for name, value in raw.items()}


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise SourceImageStageStopped(FAILED)
    return value


def _read_back(
    builder: RegistryBuildService,
    target: SourceImageTarget,
    commit: str,
    digests: Mapping[str, str],
) -> None:
    for name, digest in sorted(digests.items()):
        by_digest = builder.read_digest(target, reference=f"{name}@{digest}")
        by_tag = builder.read_digest(target, reference=f"{name}:sha-{commit}")
        if by_digest != digest or by_tag != digest:
            raise SourceImageStageStopped(FAILED)


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _run(
    command: Sequence[str], timeout: int, *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), check=False, capture_output=True, text=True, timeout=timeout, cwd=cwd
    )


class AzureRegistryBuildService:
    """Azure Container Registry Tasks and import through the signed-in Azure CLI.

    Every call carries the explicit subscription. Failures surface as fixed reason codes;
    command output never reaches the error text.
    """

    def __init__(self, runner: Runner = _run) -> None:
        self._runner = runner

    def require_available(self, target: SourceImageTarget) -> None:
        result = self._az(
            target,
            ("acr", "show", "--name", target.registry_name),
            ("--query", "{loginServer:loginServer,state:provisioningState}", "--output", "json"),
            timeout=_READ_TIMEOUT_SECONDS,
            reason=UNAVAILABLE,
        )
        try:
            registry = json.loads(result)
        except json.JSONDecodeError:
            raise SourceImageStageStopped(UNAVAILABLE) from None
        if registry != {"loginServer": target.login_server, "state": "Succeeded"}:
            raise SourceImageStageStopped(UNAVAILABLE)

    def build(
        self, target: SourceImageTarget, *, context: Path, dockerfile: str, image: str
    ) -> str:
        output = self._az(
            target,
            ("acr", "build", "--registry", target.registry_name, "--image", image),
            (
                "--file",
                dockerfile,
                "--platform",
                "linux/amd64",
                "--timeout",
                str(_BUILD_TIMEOUT_SECONDS),
                "--no-logs",
                "--output",
                "json",
                str(context),
            ),
            timeout=_BUILD_TIMEOUT_SECONDS + 300,
            reason=FAILED,
            # The Azure CLI resolves a relative --file against the working directory.
            cwd=context,
        )
        try:
            run = json.loads(output)
        except json.JSONDecodeError:
            raise SourceImageStageStopped(FAILED) from None
        repository, tag = image.split(":", 1)
        if not isinstance(run, dict) or run.get("status") != "Succeeded":
            raise SourceImageStageStopped(FAILED)
        matches = [
            record.get("digest")
            for record in run.get("outputImages") or []
            if isinstance(record, dict)
            and record.get("repository") == repository
            and record.get("tag") == tag
            and record.get("registry") == target.login_server
        ]
        if len(matches) != 1:
            raise SourceImageStageStopped(FAILED)
        return _require_digest(matches[0])

    def import_image(self, target: SourceImageTarget, *, source: str, image: str) -> None:
        self._az(
            target,
            ("acr", "import", "--name", target.registry_name, "--source", source),
            ("--image", image, "--force"),
            timeout=_IMPORT_TIMEOUT_SECONDS,
            reason=FAILED,
        )

    def read_digest(self, target: SourceImageTarget, *, reference: str) -> str:
        output = self._az(
            target,
            ("acr", "manifest", "show-metadata", "--registry", target.registry_name),
            ("--name", reference, "--query", "digest", "--output", "tsv"),
            timeout=_READ_TIMEOUT_SECONDS,
            reason=FAILED,
        )
        return _require_digest(output.strip())

    def _az(
        self,
        target: SourceImageTarget,
        head: tuple[str, ...],
        tail: tuple[str, ...],
        *,
        timeout: int,
        reason: str,
        cwd: Path | None = None,
    ) -> str:
        command = (
            "az",
            *head,
            "--subscription",
            target.subscription_id,
            *tail,
            "--only-show-errors",
        )
        try:
            result = (
                self._runner(command, timeout)
                if cwd is None
                else self._runner(command, timeout, cwd=cwd)
            )
        except subprocess.TimeoutExpired:
            raise SourceImageStageStopped(reason) from None
        if result.returncode != 0:
            if "TasksOperationsNotAllowed" in (result.stderr or ""):
                raise SourceImageStageStopped(UNAVAILABLE)
            raise SourceImageStageStopped(reason)
        return result.stdout

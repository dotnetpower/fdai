from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.runtime_release import RUNTIME_SERVICES, RUNTIME_SIDECARS
from fdai_deployment_cli.source_image_stage import (
    CHANGED,
    DEPENDENCY_IMAGES,
    FAILED,
    SERVICE_ORDER,
    UNAVAILABLE,
    AzureRegistryBuildService,
    SourceImageSnapshot,
    SourceImageStageStopped,
    SourceImageTarget,
    run_source_image_stage,
)

ROOT = Path(__file__).resolve().parents[3]
COMMIT = "0123456789abcdef" * 2 + "01234567"
SNAPSHOT_DIGEST = "b" * 64
TARGET = SourceImageTarget(
    subscription_id="00000000-0000-0000-0000-000000000000", registry_name="crfdaiexample"
)
LOGIN = "crfdaiexample.azurecr.io"


class FakeRegistry:
    """A registry build service that records calls and stores pushed references."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.calls: list[tuple[str, ...]] = []
        self.references: dict[str, str] = {}
        self.overrides: dict[str, str] = {}

    def require_available(self, target: SourceImageTarget) -> None:
        self.calls.append(("probe", target.login_server))
        if not self.available:
            raise SourceImageStageStopped(UNAVAILABLE)

    def build(
        self, target: SourceImageTarget, *, context: Path, dockerfile: str, image: str
    ) -> str:
        self.calls.append(("build", image, dockerfile, str(context)))
        digest = "sha256:" + hashlib.sha256(f"{image}:{len(self.calls)}".encode()).hexdigest()
        self._push(image, digest)
        return digest

    def import_image(self, target: SourceImageTarget, *, source: str, image: str) -> None:
        self.calls.append(("import", source, image))
        self._push(image, source.rsplit("@", 1)[1])

    def read_digest(self, target: SourceImageTarget, *, reference: str) -> str:
        self.calls.append(("read", reference))
        if reference in self.overrides:
            return self.overrides[reference]
        if reference not in self.references:
            raise SourceImageStageStopped(FAILED)
        return self.references[reference]

    def _push(self, image: str, digest: str) -> None:
        repository = image.split(":", 1)[0]
        self.references[image] = digest
        self.references[f"{repository}@{digest}"] = digest


@pytest.fixture
def snapshot(tmp_path: Path) -> SourceImageSnapshot:
    root = tmp_path / "snapshot"
    for service in SERVICE_ORDER:
        dockerfile = root / "services" / service / "docker" / "Dockerfile"
        dockerfile.parent.mkdir(parents=True)
        dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    return SourceImageSnapshot(root=root, commit=COMMIT, digest=SNAPSHOT_DIGEST)


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "work"
    directory.mkdir()
    directory.chmod(0o700)
    return directory


def _files(directory: Path) -> set[str]:
    return {
        path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()
    }


def test_builds_every_service_imports_pinned_dependencies_and_binds_read_back_digests(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    registry = FakeRegistry()

    receipt = run_source_image_stage(
        snapshot=snapshot, target=TARGET, builder=registry, work_dir=work_dir
    )

    effects = [call for call in registry.calls if call[0] in {"build", "import"}]
    assert registry.calls[0] == ("probe", LOGIN)
    assert effects == [
        *(
            (
                "build",
                f"{service}:sha-{COMMIT}",
                f"services/{service}/docker/Dockerfile",
                str(snapshot.root),
            )
            for service in SERVICE_ORDER
        ),
        *(("import", source, f"{name}:sha-{COMMIT}") for name, source in DEPENDENCY_IMAGES.items()),
    ]
    digests = receipt["image_digests"]
    assert isinstance(digests, dict)
    assert set(digests) == set(SERVICE_ORDER) | set(DEPENDENCY_IMAGES)
    for name, digest in digests.items():
        assert registry.references[f"{name}:sha-{COMMIT}"] == digest
        assert ("read", f"{name}@{digest}") in registry.calls
        assert ("read", f"{name}:sha-{COMMIT}") in registry.calls
    assert digests["clamav"] == DEPENDENCY_IMAGES["clamav"].rsplit("@", 1)[1]
    assert receipt["image_refs"] == {
        name: f"{LOGIN}/{name}@{digest}" for name, digest in digests.items()
    }
    assert receipt["provenance"] == "operator-selected-source"
    assert receipt["release_signature_verified"] is False
    assert receipt["deployment_ready"] is False
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    assert receipt["receipt_digest"] == canonical_digest(unsigned)
    stored = json.loads(
        (work_dir / f"source-images-{COMMIT}.receipt.json").read_text(encoding="utf-8")
    )
    assert stored == receipt


def test_the_stage_writes_no_kit_signature_sbom_or_provenance_file(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    before = _files(snapshot.root)

    run_source_image_stage(
        snapshot=snapshot, target=TARGET, builder=FakeRegistry(), work_dir=work_dir
    )

    written = _files(work_dir)
    assert written == {f"source-images-{COMMIT}.claim.json", f"source-images-{COMMIT}.receipt.json"}
    forbidden = re.compile(
        r"kit|\.sig$|signature|sbom|provenance|attestation|intoto", re.IGNORECASE
    )
    assert not [name for name in written if forbidden.search(name)]
    assert _files(snapshot.root) == before


def test_an_unavailable_build_service_stops_before_any_effect(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    registry = FakeRegistry(available=False)

    with pytest.raises(SourceImageStageStopped) as stopped:
        run_source_image_stage(
            snapshot=snapshot, target=TARGET, builder=registry, work_dir=work_dir
        )

    assert stopped.value.reason_code == UNAVAILABLE
    assert "Azure Container Registry Tasks" in str(stopped.value)
    assert registry.calls == [("probe", LOGIN)]
    assert _files(work_dir) == set()


def test_a_digest_that_does_not_read_back_stops_before_any_receipt(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    registry = FakeRegistry()
    registry.overrides[f"core-control-plane:sha-{COMMIT}"] = "sha256:" + "c" * 64

    with pytest.raises(SourceImageStageStopped) as stopped:
        run_source_image_stage(
            snapshot=snapshot, target=TARGET, builder=registry, work_dir=work_dir
        )

    assert stopped.value.reason_code == FAILED
    assert _files(work_dir) == {f"source-images-{COMMIT}.claim.json"}


def test_a_malformed_build_digest_stops_the_stage(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    registry = FakeRegistry()
    registry.build = lambda target, **_: "sha256:short"  # type: ignore[method-assign]

    with pytest.raises(SourceImageStageStopped) as stopped:
        run_source_image_stage(
            snapshot=snapshot, target=TARGET, builder=registry, work_dir=work_dir
        )

    assert stopped.value.reason_code == FAILED
    assert not (work_dir / f"source-images-{COMMIT}.receipt.json").exists()


def test_an_interrupted_stage_repeats_its_builds_under_the_same_claim(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    failing = FakeRegistry()
    failing.overrides[f"pgvector:sha-{COMMIT}"] = "sha256:" + "d" * 64
    with pytest.raises(SourceImageStageStopped):
        run_source_image_stage(snapshot=snapshot, target=TARGET, builder=failing, work_dir=work_dir)
    claim = (work_dir / f"source-images-{COMMIT}.claim.json").read_bytes()

    retry = FakeRegistry()
    receipt = run_source_image_stage(
        snapshot=snapshot, target=TARGET, builder=retry, work_dir=work_dir
    )

    assert sum(call[0] == "build" for call in retry.calls) == len(SERVICE_ORDER)
    assert (work_dir / f"source-images-{COMMIT}.claim.json").read_bytes() == claim
    assert receipt["effect_verified"] is True


def test_a_completed_receipt_permits_verification_only(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    registry = FakeRegistry()
    first = run_source_image_stage(
        snapshot=snapshot, target=TARGET, builder=registry, work_dir=work_dir
    )
    registry.calls.clear()

    second = run_source_image_stage(
        snapshot=snapshot, target=TARGET, builder=registry, work_dir=work_dir
    )

    assert second == first
    assert {call[0] for call in registry.calls} == {"read"}


def test_a_completed_receipt_still_requires_the_images_to_read_back(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    registry = FakeRegistry()
    run_source_image_stage(snapshot=snapshot, target=TARGET, builder=registry, work_dir=work_dir)
    registry.references.pop(f"operator-service:sha-{COMMIT}")

    with pytest.raises(SourceImageStageStopped) as stopped:
        run_source_image_stage(
            snapshot=snapshot, target=TARGET, builder=registry, work_dir=work_dir
        )

    assert stopped.value.reason_code == FAILED


def test_an_edited_receipt_is_refused_instead_of_trusted(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    registry = FakeRegistry()
    run_source_image_stage(snapshot=snapshot, target=TARGET, builder=registry, work_dir=work_dir)
    receipt_path = work_dir / f"source-images-{COMMIT}.receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["provenance"] = "signed-release"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    registry.calls.clear()

    with pytest.raises(SourceImageStageStopped) as stopped:
        run_source_image_stage(
            snapshot=snapshot, target=TARGET, builder=registry, work_dir=work_dir
        )

    assert stopped.value.reason_code == CHANGED
    assert registry.calls == []


def test_a_work_directory_for_other_inputs_is_refused(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    failing = FakeRegistry()
    failing.overrides[f"clamav:sha-{COMMIT}"] = "sha256:" + "e" * 64
    with pytest.raises(SourceImageStageStopped):
        run_source_image_stage(snapshot=snapshot, target=TARGET, builder=failing, work_dir=work_dir)
    changed = SourceImageSnapshot(root=snapshot.root, commit=COMMIT, digest="f" * 64)

    retry = FakeRegistry()
    with pytest.raises(SourceImageStageStopped) as stopped:
        run_source_image_stage(snapshot=changed, target=TARGET, builder=retry, work_dir=work_dir)

    assert stopped.value.reason_code == CHANGED
    assert not [call for call in retry.calls if call[0] in {"build", "import"}]


def test_a_receipt_for_other_inputs_is_refused(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    registry = FakeRegistry()
    run_source_image_stage(snapshot=snapshot, target=TARGET, builder=registry, work_dir=work_dir)
    other = SourceImageTarget(subscription_id=TARGET.subscription_id, registry_name="crfdaiother")

    with pytest.raises(SourceImageStageStopped) as stopped:
        run_source_image_stage(snapshot=snapshot, target=other, builder=registry, work_dir=work_dir)

    assert stopped.value.reason_code == CHANGED


@pytest.mark.parametrize(
    ("commit", "registry_name", "missing"),
    [
        ("not-a-commit", "crfdaiexample", None),
        (COMMIT, "Not_A_Registry", None),
        (COMMIT, "crfdaiexample", "isolated-executor"),
    ],
)
def test_malformed_inputs_are_refused_before_any_call(
    snapshot: SourceImageSnapshot,
    work_dir: Path,
    commit: str,
    registry_name: str,
    missing: str | None,
) -> None:
    if missing is not None:
        (snapshot.root / "services" / missing / "docker" / "Dockerfile").unlink()
    registry = FakeRegistry()

    with pytest.raises(ValueError):
        run_source_image_stage(
            snapshot=SourceImageSnapshot(root=snapshot.root, commit=commit, digest=SNAPSHOT_DIGEST),
            target=SourceImageTarget(
                subscription_id=TARGET.subscription_id, registry_name=registry_name
            ),
            builder=registry,
            work_dir=work_dir,
        )

    assert registry.calls == []


def test_image_names_match_the_runtime_release_contract() -> None:
    assert set(SERVICE_ORDER) == RUNTIME_SERVICES
    assert set(DEPENDENCY_IMAGES) == RUNTIME_SIDECARS


def test_dependency_pins_match_the_offline_kit_builder() -> None:
    script = (ROOT / "scripts/deployment/release/build-standalone-deployment-kit.sh").read_text(
        encoding="utf-8"
    )
    pins = dict(
        re.findall(r"^FROM ([a-z0-9]+)/[a-z0-9]+(@sha256:[0-9a-f]{64})$", script, re.MULTILINE)
    )
    assert pins == {
        name: "@" + source.rsplit("@", 1)[1] for name, source in DEPENDENCY_IMAGES.items()
    }
    for name, source in DEPENDENCY_IMAGES.items():
        assert source.startswith(f"docker.io/{name}/{name}@sha256:")


class FakeRunner:
    def __init__(self, *results: subprocess.CompletedProcess[str] | BaseException) -> None:
        self.results = list(results)
        self.commands: list[tuple[str, ...]] = []
        self.cwds: list[Path | None] = []

    def __call__(
        self, command: Sequence[str], timeout: int, *, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(tuple(command))
        self.cwds.append(cwd)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _completed(
    stdout: str = "", *, code: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=code, stdout=stdout, stderr=stderr)


def _run_record(status: str = "Succeeded", **image: str) -> str:
    output = {"registry": LOGIN, "repository": "operator-service", "tag": f"sha-{COMMIT}"} | image
    other = {
        "registry": LOGIN,
        "repository": "operator-service",
        "tag": "latest",
        "digest": "sha256:" + "9" * 64,
    }
    return json.dumps({"status": status, "outputImages": [other, output]})


def test_azure_build_returns_the_run_record_digest_for_the_exact_image(tmp_path: Path) -> None:
    digest = "sha256:" + "1" * 64
    runner = FakeRunner(_completed(_run_record(digest=digest)))

    observed = AzureRegistryBuildService(runner).build(
        TARGET,
        context=tmp_path,
        dockerfile="services/operator-service/docker/Dockerfile",
        image=f"operator-service:sha-{COMMIT}",
    )

    assert observed == digest
    command = runner.commands[0]
    assert command[:3] == ("az", "acr", "build")
    for flag, value in (
        ("--registry", "crfdaiexample"),
        ("--subscription", TARGET.subscription_id),
        ("--image", f"operator-service:sha-{COMMIT}"),
        ("--file", "services/operator-service/docker/Dockerfile"),
        ("--platform", "linux/amd64"),
        ("--output", "json"),
    ):
        assert command[command.index(flag) + 1] == value
    assert "--no-logs" in command
    assert str(tmp_path) in command
    # A relative --file only resolves when the build runs from its context directory.
    assert runner.cwds == [tmp_path]


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (_completed(_run_record("Failed", digest="sha256:" + "1" * 64)), FAILED),
        (_completed(_run_record(digest="sha256:" + "1" * 64, tag="sha-other")), FAILED),
        (_completed("not json"), FAILED),
        (_completed(code=1, stderr="secret-ish detail TasksOperationsNotAllowed"), UNAVAILABLE),
        (_completed(code=1, stderr="secret-ish detail"), FAILED),
        (subprocess.TimeoutExpired(cmd="az", timeout=1), FAILED),
    ],
)
def test_azure_build_failures_map_to_fixed_reasons(
    tmp_path: Path, result: subprocess.CompletedProcess[str] | BaseException, reason: str
) -> None:
    with pytest.raises(SourceImageStageStopped) as stopped:
        AzureRegistryBuildService(FakeRunner(result)).build(
            TARGET,
            context=tmp_path,
            dockerfile="services/operator-service/docker/Dockerfile",
            image=f"operator-service:sha-{COMMIT}",
        )

    assert stopped.value.reason_code == reason
    assert "secret-ish" not in str(stopped.value)


@pytest.mark.parametrize(
    ("result", "available"),
    [
        (_completed(json.dumps({"loginServer": LOGIN, "state": "Succeeded"})), True),
        (_completed(json.dumps({"loginServer": "other.azurecr.io", "state": "Succeeded"})), False),
        (_completed(json.dumps({"loginServer": LOGIN, "state": "Updating"})), False),
        (_completed(code=3), False),
    ],
)
def test_azure_availability_requires_the_exact_ready_registry(
    result: subprocess.CompletedProcess[str], available: bool
) -> None:
    runner = FakeRunner(result)
    service = AzureRegistryBuildService(runner)

    if available:
        service.require_available(TARGET)
    else:
        with pytest.raises(SourceImageStageStopped) as stopped:
            service.require_available(TARGET)
        assert stopped.value.reason_code == UNAVAILABLE
    assert runner.commands[0][:5] == ("az", "acr", "show", "--name", "crfdaiexample")


def test_azure_import_and_read_back_use_the_exact_references() -> None:
    digest = "sha256:" + "2" * 64
    runner = FakeRunner(_completed(), _completed(digest + "\n"), _completed("sha256:bad\n"))
    service = AzureRegistryBuildService(runner)

    service.import_image(TARGET, source=DEPENDENCY_IMAGES["clamav"], image=f"clamav:sha-{COMMIT}")
    assert service.read_digest(TARGET, reference=f"clamav@{digest}") == digest
    with pytest.raises(SourceImageStageStopped):
        service.read_digest(TARGET, reference=f"clamav:sha-{COMMIT}")

    imported, read, _ = runner.commands
    assert imported[:3] == ("az", "acr", "import")
    assert imported[imported.index("--source") + 1] == DEPENDENCY_IMAGES["clamav"]
    assert imported[imported.index("--image") + 1] == f"clamav:sha-{COMMIT}"
    assert "--force" in imported
    assert read[:4] == ("az", "acr", "manifest", "show-metadata")
    assert read[read.index("--name") + 1] == f"clamav@{digest}"


def test_creates_its_private_work_directory_on_a_fresh_host(
    snapshot: SourceImageSnapshot, work_dir: Path
) -> None:
    stage = work_dir / "source-image-stage"

    run_source_image_stage(snapshot=snapshot, target=TARGET, builder=FakeRegistry(), work_dir=stage)

    assert stage.stat().st_mode & 0o777 == 0o700
    assert any(path.name.endswith(".receipt.json") for path in stage.iterdir())

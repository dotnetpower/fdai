"""CSP-neutral contract for governed Python tasks on managed compute targets."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

_TASK_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$")
_ARTIFACT_REF = re.compile(
    r"^python-task:[a-z][a-z0-9_.-]{0,79}@[A-Za-z0-9_.-]{1,64}#[0-9a-f]{64}$"
)


def validate_python_task_artifact_ref(value: str) -> str:
    """Return a bounded content-addressed artifact ref or raise."""
    if not _ARTIFACT_REF.fullmatch(value):
        raise ValueError("artifact_ref MUST be a valid content-addressed Python task ref")
    return value


class PythonTaskCapability(StrEnum):
    """Explicit host capabilities a task is allowed to use."""

    GPU = "gpu"
    NETWORK = "network"
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    PROCESS = "process"


@dataclass(frozen=True, slots=True)
class PythonTaskFile:
    """One UTF-8 file in a content-addressed task artifact."""

    path: str
    content: str = field(repr=False)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PythonTaskSpec:
    """Immutable source bundle and host requirements for one Python task."""

    task_id: str
    version: str
    entrypoint: str
    files: tuple[PythonTaskFile, ...]
    required_modules: tuple[str, ...] = ()
    capabilities: frozenset[PythonTaskCapability] = frozenset()
    timeout_seconds: int = 900
    python_executable: str = "/usr/bin/python3"

    def __post_init__(self) -> None:
        if not _TASK_ID.fullmatch(self.task_id):
            raise ValueError("task_id MUST be a lowercase dotted identifier")
        if not self.version or len(self.version) > 64:
            raise ValueError("version MUST be a non-empty string of at most 64 characters")
        if not self.files:
            raise ValueError("files MUST contain at least one file")
        if not 1 <= self.timeout_seconds <= 86_400:
            raise ValueError("timeout_seconds MUST be in [1, 86400]")
        if not self.python_executable.startswith("/") or len(self.python_executable) > 200:
            raise ValueError("python_executable MUST be a bounded absolute path")
        if any(not _MODULE.fullmatch(module) for module in self.required_modules):
            raise ValueError("required_modules MUST contain importable module names")
        if len(set(self.required_modules)) != len(self.required_modules):
            raise ValueError("required_modules MUST be unique")

    @property
    def artifact_hash(self) -> str:
        payload = {
            "task_id": self.task_id,
            "version": self.version,
            "entrypoint": self.entrypoint,
            "files": [
                {"path": item.path, "sha256": item.sha256}
                for item in sorted(self.files, key=lambda item: item.path)
            ],
            "required_modules": sorted(self.required_modules),
            "capabilities": sorted(capability.value for capability in self.capabilities),
            "timeout_seconds": self.timeout_seconds,
            "python_executable": self.python_executable,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def artifact_ref(self) -> str:
        return f"python-task:{self.task_id}@{self.version}#{self.artifact_hash}"


@dataclass(frozen=True, slots=True)
class VmTaskTarget:
    """Ontology-resolved compute target supplied by the inventory adapter."""

    resource_ref: str
    provider_ref: str | None = None
    capabilities: frozenset[PythonTaskCapability] = frozenset()
    os_type: str = "linux"
    location: str | None = None

    def __post_init__(self) -> None:
        if not self.resource_ref or len(self.resource_ref) > 2_048:
            raise ValueError("resource_ref MUST be a bounded non-empty string")
        if self.provider_ref is not None and (
            not self.provider_ref or len(self.provider_ref) > 2_048
        ):
            raise ValueError("provider_ref MUST be a bounded non-empty string when set")
        if self.os_type != "linux":
            raise ValueError("Python VM tasks currently support linux targets only")
        if self.location is not None and (not self.location or len(self.location) > 64):
            raise ValueError("location MUST be a bounded non-empty string when set")


@dataclass(frozen=True, slots=True)
class VmTaskRequest:
    """One idempotent task invocation."""

    idempotency_key: str
    task: PythonTaskSpec
    target: VmTaskTarget
    inputs: Mapping[str, str] = field(default_factory=dict)
    dry_run: bool = True

    def __post_init__(self) -> None:
        if not self.idempotency_key or len(self.idempotency_key) > 200:
            raise ValueError("idempotency_key MUST be a bounded non-empty string")
        if len(self.inputs) > 100:
            raise ValueError("inputs MUST contain at most 100 entries")
        if any(
            not isinstance(key, str)
            or not key
            or len(key) > 128
            or not isinstance(value, str)
            or len(value) > 4_000
            for key, value in self.inputs.items()
        ):
            raise ValueError("inputs MUST contain bounded string keys and values")


class VmTaskStatus(StrEnum):
    PLANNED = "planned"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.PLANNED, self.SUCCEEDED, self.FAILED, self.CANCELLED}


@dataclass(frozen=True, slots=True)
class VmTaskReceipt:
    """Provider-neutral status returned by plan, submit, status, and cancel."""

    run_ref: str
    artifact_hash: str
    status: VmTaskStatus
    detail: str
    already_existed: bool = False
    exit_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""


class VmTaskRunnerError(RuntimeError):
    """A VM task provider failed before returning a trustworthy receipt."""


@runtime_checkable
class PythonTaskArtifactStore(Protocol):
    """Immutable source of validated, content-addressed task artifacts."""

    async def put(self, task: PythonTaskSpec, *, created_by: str = "system") -> str: ...

    async def get(self, artifact_ref: str) -> PythonTaskSpec: ...


@runtime_checkable
class VmTaskTargetResolver(Protocol):
    """Resolve a neutral ontology Resource into a provider execution target."""

    async def resolve(self, resource_ref: str) -> VmTaskTarget: ...


@runtime_checkable
class VmTaskRunner(Protocol):
    """Stage and execute governed Python tasks on a compute target."""

    async def run(self, request: VmTaskRequest) -> VmTaskReceipt: ...

    async def status(self, run_ref: str) -> VmTaskReceipt: ...

    async def cancel(self, run_ref: str) -> VmTaskReceipt: ...


def python_task_to_mapping(task: PythonTaskSpec) -> dict[str, object]:
    """Serialize a task artifact into its stable persistence shape."""
    return {
        "task_id": task.task_id,
        "version": task.version,
        "entrypoint": task.entrypoint,
        "files": [{"path": item.path, "content": item.content} for item in task.files],
        "required_modules": list(task.required_modules),
        "capabilities": sorted(value.value for value in task.capabilities),
        "timeout_seconds": task.timeout_seconds,
        "python_executable": task.python_executable,
    }


def python_task_from_mapping(value: Mapping[str, object]) -> PythonTaskSpec:
    """Deserialize the stable persistence shape and re-run contract guards."""
    files_value = value.get("files")
    if not isinstance(files_value, list):
        raise ValueError("Python task files MUST be an array")
    files: list[PythonTaskFile] = []
    for item in files_value:
        if not isinstance(item, Mapping):
            raise ValueError("Python task file MUST be an object")
        path = item.get("path")
        content = item.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise ValueError("Python task file path and content MUST be strings")
        files.append(PythonTaskFile(path=path, content=content))
    modules = value.get("required_modules", [])
    capabilities = value.get("capabilities", [])
    if not isinstance(modules, list) or any(not isinstance(item, str) for item in modules):
        raise ValueError("required_modules MUST be an array of strings")
    if not isinstance(capabilities, list) or any(
        not isinstance(item, str) for item in capabilities
    ):
        raise ValueError("capabilities MUST be an array of strings")
    timeout = value.get("timeout_seconds", 900)
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        raise ValueError("timeout_seconds MUST be an integer")
    required_strings = {
        key: value.get(key) for key in ("task_id", "version", "entrypoint", "python_executable")
    }
    if any(not isinstance(item, str) for item in required_strings.values()):
        raise ValueError("Python task identifiers and executable MUST be strings")
    return PythonTaskSpec(
        task_id=str(required_strings["task_id"]),
        version=str(required_strings["version"]),
        entrypoint=str(required_strings["entrypoint"]),
        files=tuple(files),
        required_modules=tuple(modules),
        capabilities=frozenset(PythonTaskCapability(item) for item in capabilities),
        timeout_seconds=timeout,
        python_executable=str(required_strings["python_executable"]),
    )


__all__ = [
    "PythonTaskCapability",
    "PythonTaskArtifactStore",
    "PythonTaskFile",
    "PythonTaskSpec",
    "VmTaskReceipt",
    "VmTaskRequest",
    "VmTaskRunner",
    "VmTaskRunnerError",
    "VmTaskStatus",
    "VmTaskTarget",
    "VmTaskTargetResolver",
    "python_task_from_mapping",
    "python_task_to_mapping",
    "validate_python_task_artifact_ref",
]

"""In-memory VM task runner for tests and local workflow authoring."""

from __future__ import annotations

from fdai.shared.providers.vm_task import (
    PythonTaskSpec,
    VmTaskReceipt,
    VmTaskRequest,
    VmTaskStatus,
    VmTaskTarget,
)


class InMemoryVmTaskRunner:
    """Record deterministic plans/runs without executing task source."""

    def __init__(self) -> None:
        self.requests: list[VmTaskRequest] = []
        self._by_key: dict[str, VmTaskReceipt] = {}
        self._by_ref: dict[str, VmTaskReceipt] = {}

    async def run(self, request: VmTaskRequest) -> VmTaskReceipt:
        existing = self._by_key.get(request.idempotency_key)
        if existing is not None:
            return VmTaskReceipt(
                run_ref=existing.run_ref,
                artifact_hash=existing.artifact_hash,
                status=existing.status,
                detail=existing.detail,
                already_existed=True,
                exit_code=existing.exit_code,
                stdout_tail=existing.stdout_tail,
                stderr_tail=existing.stderr_tail,
            )
        missing = request.task.capabilities - request.target.capabilities
        if missing:
            names = ", ".join(sorted(capability.value for capability in missing))
            raise ValueError(f"target lacks required capabilities: {names}")
        self.requests.append(request)
        run_ref = f"vm-task:{request.task.task_id}:{request.task.artifact_hash[:16]}"
        status = VmTaskStatus.PLANNED if request.dry_run else VmTaskStatus.SUCCEEDED
        receipt = VmTaskReceipt(
            run_ref=run_ref,
            artifact_hash=request.task.artifact_hash,
            status=status,
            detail=(
                "validated shadow plan; no files copied and no code executed"
                if request.dry_run
                else "simulated task completed"
            ),
            exit_code=None if request.dry_run else 0,
        )
        self._by_key[request.idempotency_key] = receipt
        self._by_ref[run_ref] = receipt
        return receipt

    async def status(self, run_ref: str) -> VmTaskReceipt:
        try:
            return self._by_ref[run_ref]
        except KeyError as exc:
            raise LookupError(f"unknown VM task run {run_ref!r}") from exc

    async def cancel(self, run_ref: str) -> VmTaskReceipt:
        current = await self.status(run_ref)
        cancelled = VmTaskReceipt(
            run_ref=current.run_ref,
            artifact_hash=current.artifact_hash,
            status=VmTaskStatus.CANCELLED,
            detail="task cancelled",
            exit_code=current.exit_code,
            stdout_tail=current.stdout_tail,
            stderr_tail=current.stderr_tail,
        )
        self._by_ref[run_ref] = cancelled
        for key, receipt in tuple(self._by_key.items()):
            if receipt.run_ref == run_ref:
                self._by_key[key] = cancelled
        return cancelled


class InMemoryPythonTaskArtifactStore:
    """Immutable in-memory artifact registry with version conflict checks."""

    def __init__(self) -> None:
        self._by_ref: dict[str, PythonTaskSpec] = {}
        self._version_hashes: dict[tuple[str, str], str] = {}

    async def put(self, task: PythonTaskSpec, *, created_by: str = "system") -> str:
        if not created_by:
            raise ValueError("created_by MUST be non-empty")
        version_key = (task.task_id, task.version)
        existing_hash = self._version_hashes.get(version_key)
        if existing_hash is not None and existing_hash != task.artifact_hash:
            raise ValueError(
                f"task version {task.task_id}@{task.version} is immutable and already registered"
            )
        self._version_hashes[version_key] = task.artifact_hash
        self._by_ref[task.artifact_ref] = task
        return task.artifact_ref

    async def get(self, artifact_ref: str) -> PythonTaskSpec:
        try:
            return self._by_ref[artifact_ref]
        except KeyError as exc:
            raise LookupError(f"unknown Python task artifact {artifact_ref!r}") from exc


class InMemoryVmTaskTargetResolver:
    """Resolve only explicitly registered ontology targets."""

    def __init__(self, targets: tuple[VmTaskTarget, ...] = ()) -> None:
        self._targets = {target.resource_ref: target for target in targets}

    def register(self, target: VmTaskTarget) -> None:
        self._targets[target.resource_ref] = target

    async def resolve(self, resource_ref: str) -> VmTaskTarget:
        try:
            return self._targets[resource_ref]
        except KeyError as exc:
            raise LookupError(f"unknown VM task target {resource_ref!r}") from exc


__all__ = [
    "InMemoryPythonTaskArtifactStore",
    "InMemoryVmTaskRunner",
    "InMemoryVmTaskTargetResolver",
]

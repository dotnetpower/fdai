"""Fail-closed process supervision for isolated ontology assurance runs."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, TypeVar

STATUS_SCHEMA_VERSION: Final = "1.0.0"
_Result = TypeVar("_Result")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")  # noqa: UP017


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    """Declare one child without placing environment values in retained status."""

    label: str
    command: tuple[str, ...]
    command_label: str
    cwd: Path
    log_path: Path
    environment: Mapping[str, str] | None = None


@dataclass(slots=True)
class ManagedProcess:
    """Track one child and its dedicated process group."""

    spec: ProcessSpec
    process: asyncio.subprocess.Process
    log_handle: Any
    wait_task: asyncio.Task[int]

    @property
    def pid(self) -> int:
        if self.process.pid is None:
            raise RuntimeError("managed process has no PID")
        return self.process.pid


@dataclass(frozen=True, slots=True)
class ProcessExit:
    """Describe a child exit without conflating exit codes and signals."""

    label: str
    returncode: int
    exit_code: int | None
    signal_name: str | None


class RequiredChildExitedError(RuntimeError):
    """Raised when a required service exits before the measured phase."""

    def __init__(self, process_exit: ProcessExit) -> None:
        super().__init__(f"required child exited: {process_exit.label}")
        self.process_exit = process_exit


class AtomicRunStatus:
    """Persist provenance and process lifecycle through same-directory replacement."""

    def __init__(self, path: Path, *, run_id: str, source_revision: str) -> None:
        self.path = path
        self.payload: dict[str, Any] = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "run_id": run_id,
            "source_revision": source_revision,
            "runner_pid": os.getpid(),
            "runner_process_group_id": os.getpgrp(),
            "state": "starting",
            "phase": "prepare",
            "processes": {},
            "termination": None,
            "updated_at": _utc_now(),
        }
        self._write()

    def update(self, **values: Any) -> None:
        """Replace top-level status fields and durably publish the new snapshot."""
        self.payload.update(values)
        self.payload["updated_at"] = _utc_now()
        self._write()

    def process_started(self, managed: ManagedProcess) -> None:
        """Record the PID and isolated process group before measurement continues."""
        self.payload["processes"][managed.spec.label] = {
            "pid": managed.pid,
            "process_group_id": os.getpgid(managed.pid),
            "command": managed.spec.command_label,
            "log_path": str(managed.spec.log_path),
            "state": "running",
            "started_at": _utc_now(),
            "ended_at": None,
            "exit_code": None,
            "signal": None,
            "termination_request": None,
        }
        self.payload["updated_at"] = _utc_now()
        self._write()

    def process_termination_requested(self, managed: ManagedProcess, reason: str) -> None:
        """Record why this supervisor signaled one of its own process groups."""
        record = self.payload["processes"][managed.spec.label]
        record["termination_request"] = reason
        self.payload["updated_at"] = _utc_now()
        self._write()

    def process_exited(self, managed: ManagedProcess, returncode: int) -> ProcessExit:
        """Record an ordinary exit or the exact terminating signal."""
        signal_name = signal.Signals(-returncode).name if returncode < 0 else None
        exit_code = returncode if returncode >= 0 else None
        record = self.payload["processes"][managed.spec.label]
        record.update(
            state="exited",
            ended_at=_utc_now(),
            exit_code=exit_code,
            signal=signal_name,
        )
        self.payload["updated_at"] = _utc_now()
        self._write()
        return ProcessExit(
            label=managed.spec.label,
            returncode=returncode,
            exit_code=exit_code,
            signal_name=signal_name,
        )

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        temporary = self.path.with_name(f".{self.path.name}.tmp.{os.getpid()}")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(self.payload, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            temporary.unlink(missing_ok=True)


class AssuranceProcessSupervisor:
    """Own required services and stop a measured phase when any service exits."""

    def __init__(self, status: AtomicRunStatus, *, stop_timeout_seconds: float = 10.0) -> None:
        self.status = status
        self.stop_timeout_seconds = stop_timeout_seconds
        self.services: list[ManagedProcess] = []
        self.phase_process: ManagedProcess | None = None

    async def start_services(self, specs: tuple[ProcessSpec, ...]) -> None:
        """Start all required children in independent process groups."""
        for spec in specs:
            managed = await self._start(spec)
            self.services.append(managed)

    async def run_phase(self, spec: ProcessSpec) -> ProcessExit:
        """Run one measured command and fail closed on the first required child exit."""
        if self.phase_process is not None:
            raise RuntimeError("an assurance phase is already running")
        managed = await self._start(spec)
        self.phase_process = managed
        try:
            waiters = {service.wait_task: service for service in self.services}
            waiters[managed.wait_task] = managed
            done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)

            exited_services = [waiters[task] for task in done if waiters[task] is not managed]
            if exited_services:
                failed = exited_services[0]
                child_exit = self.status.process_exited(failed, failed.wait_task.result())
                self.status.update(
                    state="failed",
                    termination={
                        "reason": "required_child_exited",
                        "child": child_exit.label,
                        "exit_code": child_exit.exit_code,
                        "signal": child_exit.signal_name,
                    },
                )
                await self._terminate(managed, "required_child_exited")
                raise RequiredChildExitedError(child_exit)

            return self.status.process_exited(managed, managed.wait_task.result())
        finally:
            self.phase_process = None

    async def guard_operation(
        self,
        operation: Awaitable[_Result],
        *,
        timeout_seconds: float,
    ) -> _Result:
        """Await readiness work while treating any required child exit as terminal."""
        operation_task: asyncio.Future[_Result] = asyncio.ensure_future(operation)
        waiters: dict[asyncio.Future[Any], ManagedProcess] = {
            service.wait_task: service for service in self.services
        }
        guarded_tasks: set[asyncio.Future[Any]] = {operation_task, *waiters}
        try:
            done, _ = await asyncio.wait(
                guarded_tasks,
                timeout=timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            exited_services = [waiters[task] for task in done if task in waiters]
            if exited_services:
                failed = exited_services[0]
                child_exit = self.status.process_exited(failed, failed.wait_task.result())
                self.status.update(
                    state="failed",
                    termination={
                        "reason": "required_child_exited",
                        "child": child_exit.label,
                        "exit_code": child_exit.exit_code,
                        "signal": child_exit.signal_name,
                    },
                )
                raise RequiredChildExitedError(child_exit)
            if operation_task not in done:
                raise TimeoutError("guarded operation exceeded its deadline")
            return operation_task.result()
        finally:
            if not operation_task.done():
                operation_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await operation_task

    async def close(self, reason: str = "supervisor_cleanup") -> None:
        """Terminate only process groups created by this supervisor."""
        if self.phase_process is not None:
            await self._terminate(self.phase_process, reason)
        for managed in reversed(self.services):
            await self._terminate(managed, reason)
        for managed in self.services:
            managed.log_handle.close()
        self.services.clear()

    async def _start(self, spec: ProcessSpec) -> ManagedProcess:
        spec.log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(spec.log_path.parent, 0o700)
        descriptor = os.open(
            spec.log_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        log_handle = os.fdopen(descriptor, "ab", buffering=0)
        try:
            process = await asyncio.create_subprocess_exec(
                *spec.command,
                cwd=spec.cwd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=log_handle,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                env=spec.environment,
            )
        except BaseException:
            log_handle.close()
            raise
        managed = ManagedProcess(
            spec=spec,
            process=process,
            log_handle=log_handle,
            wait_task=asyncio.create_task(process.wait()),
        )
        self.status.process_started(managed)
        return managed

    async def _terminate(self, managed: ManagedProcess, reason: str) -> None:
        if managed.process.returncode is not None:
            if self.status.payload["processes"][managed.spec.label]["state"] != "exited":
                self.status.process_exited(managed, managed.process.returncode)
            return
        self.status.process_termination_requested(managed, reason)
        try:
            os.killpg(managed.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            returncode = await asyncio.wait_for(
                asyncio.shield(managed.wait_task),
                timeout=self.stop_timeout_seconds,
            )
        except TimeoutError:
            try:
                os.killpg(managed.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            returncode = await managed.wait_task
        self.status.process_exited(managed, returncode)

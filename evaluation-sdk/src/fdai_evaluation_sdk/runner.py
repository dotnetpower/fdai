"""Generic bounded runner for independently installed evaluation adapters."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_evaluation_sdk.contracts import EvaluationResult, EvaluationStatus, EvaluationTask
from fdai_evaluation_sdk.protocols import EVALUATION_API_VERSION, EvaluationAdapter, EvaluationHost


class EvaluationRunError(RuntimeError):
    """Evaluation lifecycle stopped before a trustworthy result was submitted."""


@dataclass(frozen=True, slots=True)
class EvaluationRunSummary:
    """Bounded terminal counts for one external adapter run."""

    adapter_id: str
    session_id: str
    task_count: int
    completed_count: int
    held_count: int
    failed_count: int


class EvaluationRunner:
    """Drive an adapter through only the public EvaluationHost protocol."""

    def __init__(self, *, adapter: EvaluationAdapter, host: EvaluationHost) -> None:
        if not isinstance(adapter, EvaluationAdapter):
            raise TypeError("adapter MUST implement EvaluationAdapter")
        if not isinstance(host, EvaluationHost):
            raise TypeError("host MUST implement EvaluationHost")
        if host.api_version != EVALUATION_API_VERSION:
            raise EvaluationRunError(
                f"evaluation host API {host.api_version!r} is incompatible with "
                f"SDK API {EVALUATION_API_VERSION!r}"
            )
        self._adapter = adapter
        self._host = host

    async def run(self) -> EvaluationRunSummary:
        """Open one bounded session and submit each correlated terminal result once."""

        session = None
        request = None
        seen: set[tuple[str, str]] = set()
        counts = {status: 0 for status in EvaluationStatus}
        primary_error: BaseException | None = None
        try:
            request = await self._adapter.start()
            session = await self._host.open(request)
            while True:
                task = await self._adapter.next_task()
                if task is None:
                    break
                _validate_task(task, session_id=request.session_id, seen=seen)
                if len(seen) >= request.task_count_limit:
                    raise EvaluationRunError(
                        f"evaluation task limit exceeded ({request.task_count_limit})"
                    )
                identity = (task.task_id, task.phase)
                seen.add(identity)
                result = await session.execute(task)
                _validate_result(result, task)
                await self._adapter.submit(result)
                counts[result.status] += 1
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            cleanup_errors: list[BaseException] = []
            if session is not None:
                try:
                    await session.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                await self._adapter.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
            if cleanup_errors:
                if primary_error is None:
                    raise cleanup_errors[0]
                names = ", ".join(type(error).__name__ for error in cleanup_errors)
                primary_error.add_note(f"evaluation cleanup also failed ({names})")

        if request is None:
            raise EvaluationRunError("adapter did not create an evaluation request")
        return EvaluationRunSummary(
            adapter_id=self._adapter.adapter_id,
            session_id=request.session_id,
            task_count=len(seen),
            completed_count=counts[EvaluationStatus.COMPLETED],
            held_count=counts[EvaluationStatus.HELD],
            failed_count=counts[EvaluationStatus.FAILED],
        )


def _validate_task(
    task: object,
    *,
    session_id: str,
    seen: set[tuple[str, str]],
) -> None:
    if not isinstance(task, EvaluationTask):
        raise EvaluationRunError("adapter returned an invalid evaluation task")
    if task.session_id != session_id:
        raise EvaluationRunError("adapter task belongs to another evaluation session")
    if (task.task_id, task.phase) in seen:
        raise EvaluationRunError("adapter returned a duplicate evaluation task identity")


def _validate_result(result: object, task: EvaluationTask) -> None:
    if not isinstance(result, EvaluationResult):
        raise EvaluationRunError("host returned an invalid evaluation result")
    if (result.session_id, result.task_id, result.phase) != (
        task.session_id,
        task.task_id,
        task.phase,
    ):
        raise EvaluationRunError("host result identity does not match the evaluation task")


__all__ = ["EvaluationRunError", "EvaluationRunSummary", "EvaluationRunner"]

"""Bounded Command Deck adapter for explicit KQL reads."""

from __future__ import annotations

import hashlib
import json
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.delivery.read_api.routes.chat_system_health import ChatToolResolver
from fdai.shared.providers.observation import LogQueryProvider, ObservationError

_MAX_CHAT_ROWS = 100
_MAX_RENDERED_ROWS = 20
_MAX_RENDERED_COLUMNS = 8
_MAX_CELL_CHARS = 160


@dataclass(frozen=True, slots=True)
class LogQueryChatTools:
    """Resolve explicit ``query_log`` commands through a real log provider."""

    provider: LogQueryProvider
    fallback: ChatToolResolver | None = None

    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        head = prompt.lstrip().split(maxsplit=1)
        if not head or head[0] != "query_log":
            return await self._fallback(prompt, principal_id=principal_id)

        try:
            arguments = _parse_arguments(head[1] if len(head) == 2 else "")
        except ValueError as exc:
            return _error_evidence("invalid_log_query_arguments", str(exc))

        query = arguments["query"]
        window = arguments["window"]
        max_rows = arguments["max_rows"]
        try:
            result = await self.provider.query_log(
                query=query,
                window=window,
                max_rows=max_rows,
            )
        except ObservationError as exc:
            return _error_evidence("log_query_unavailable", str(exc), status="unavailable")

        rows = [_bounded_row(row) for row in result.rows]
        return {
            "tool": "query_log",
            "authority": "server_log_query",
            "status": "ok",
            "result": {
                "status": "matched" if rows else "empty",
                "source": "azure_monitor_logs",
                "query_digest": _query_digest(query),
                "window": window,
                "rows": rows,
                "row_count": len(rows),
                "truncated": result.truncated,
                "returned_records": result.scanned_records,
            },
        }

    async def _fallback(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        if self.fallback is None:
            return None
        return await self.fallback.resolve(prompt, principal_id=principal_id)


def render_log_query_answer(
    evidence: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    """Render KQL rows without allowing row text to steer answer generation."""

    if evidence.get("tool") != "query_log":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = _is_korean(locale)
    status = result.get("status")
    if status in {"invalid", "unavailable"}:
        error = result.get("error")
        message = error.get("message") if isinstance(error, Mapping) else None
        detail = str(message) if isinstance(message, str) and message else "unknown error"
        if korean:
            return f"KQL 질의를 실행하거나 검증하지 못했습니다. 상태: {detail}"
        return f"The KQL query was not executed or verified. Status: {detail}"

    rows = result.get("rows")
    if not isinstance(rows, list):
        return None
    window = str(result.get("window") or "unknown")
    truncated = result.get("truncated") is True
    if not rows:
        if korean:
            return (
                f"Azure Monitor Logs에서 {window} 범위의 bounded KQL을 실행했으며 "
                "일치하는 행은 0건입니다. 근거: azure_monitor_logs"
            )
        return (
            f"The bounded KQL query ran against Azure Monitor Logs for {window} and "
            "returned 0 rows. Evidence: azure_monitor_logs"
        )

    rendered = _render_rows(rows)
    shown = min(len(rows), _MAX_RENDERED_ROWS)
    if korean:
        prefix = (
            f"Azure Monitor Logs에서 {window} 범위의 bounded KQL을 실행해 "
            f"{len(rows)}개 행을 반환했고, 아래에 {shown}개를 표시합니다."
        )
        suffix = " 결과가 잘렸습니다." if truncated else ""
        return f"{prefix}{suffix}\n\n{rendered}\n\n근거: azure_monitor_logs"
    prefix = (
        f"The bounded KQL query ran against Azure Monitor Logs for {window}, returned "
        f"{len(rows)} rows, and shows {shown} below."
    )
    suffix = " The result was truncated." if truncated else ""
    return f"{prefix}{suffix}\n\n{rendered}\n\nEvidence: azure_monitor_logs"


def log_query_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    digest = result.get("query_digest")
    window = result.get("window")
    if not isinstance(digest, str) or not isinstance(window, str):
        return ()
    return (f"azure-monitor-logs:kql:{digest}@{window}",)


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        raise ValueError(f"query_log arguments are malformed: {exc}") from exc
    values: dict[str, str] = {}
    for token in tokens:
        key, separator, value = token.partition("=")
        if not separator or key not in {"query", "window", "max_rows"}:
            raise ValueError(
                "query_log requires query=<KQL> window=<ISO duration> and optional max_rows=<N>"
            )
        if key in values:
            raise ValueError(f"query_log argument {key!r} was supplied more than once")
        values[key] = value
    query = values.get("query", "").strip()
    window = values.get("window", "").strip()
    if not query or not window:
        raise ValueError("query_log requires non-empty query and window arguments")
    try:
        max_rows = int(values.get("max_rows", "100"))
    except ValueError as exc:
        raise ValueError("query_log max_rows MUST be an integer") from exc
    if max_rows < 1 or max_rows > _MAX_CHAT_ROWS:
        raise ValueError(f"query_log max_rows MUST be between 1 and {_MAX_CHAT_ROWS}")
    return {"query": query, "window": window, "max_rows": max_rows}


def _bounded_row(row: Mapping[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for index, (key, value) in enumerate(row.items()):
        if index >= _MAX_RENDERED_COLUMNS:
            break
        bounded[str(key)[:80]] = _bounded_value(value)
    return bounded


def _bounded_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_CELL_CHARS]
    if isinstance(value, (Mapping, list, tuple)):
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        return serialized[:_MAX_CELL_CHARS]
    return str(value)[:_MAX_CELL_CHARS]


def _render_rows(rows: list[Any]) -> str:
    mappings = [row for row in rows[:_MAX_RENDERED_ROWS] if isinstance(row, Mapping)]
    columns = tuple(dict.fromkeys(str(key) for row in mappings for key in row))[
        :_MAX_RENDERED_COLUMNS
    ]
    if not columns:
        return "(rows contain no displayable columns)"
    header = "| " + " | ".join(_markdown_cell(column) for column in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_markdown_cell(row.get(column)) for column in columns) + " |"
        for row in mappings
    ]
    return "\n".join((header, divider, *body))


def _markdown_cell(value: Any) -> str:
    text = "null" if value is None else str(value)
    return text.replace("\n", " ").replace("\r", " ").replace("|", "\\|")


def _query_digest(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()[:16]


def _error_evidence(code: str, message: str, *, status: str = "invalid") -> dict[str, Any]:
    return {
        "tool": "query_log",
        "authority": "server_log_query",
        "status": "error" if status == "invalid" else "abstain",
        "result": {
            "status": status,
            "error": {"code": code, "message": message[:300]},
        },
    }


def _is_korean(locale: str | None) -> bool:
    return bool(locale and locale.lower().split("-", 1)[0].split("_", 1)[0] == "ko")


__all__ = [
    "LogQueryChatTools",
    "log_query_evidence_refs",
    "render_log_query_answer",
]

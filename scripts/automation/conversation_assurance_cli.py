"""Explicit CLI and idle supervisor for Pantheon conversation diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

_ROOT = Path(__file__).resolve().parents[2]
for _source in ("services/core-control-plane/src", "packages/service-contracts/src"):
    sys.path.insert(0, str(_ROOT / _source))

from fdai.agents import PANTHEON_SPECS  # noqa: E402
from fdai.core.conversation_assurance import (  # noqa: E402
    CampaignHoldError,
    ConversationTurnTraceReceipt,
    PantheonCampaignController,
    PantheonCensusCase,
    PantheonDiagnosticCase,
    PantheonRubric,
    PantheonSemanticReview,
    PantheonTurnDiagnostic,
    build_pantheon_census,
    evaluate_pantheon_turn,
    open_private_lock,
    private_marker_exists,
    read_private_text,
    remove_private_marker,
    required_observed_rubrics,
    touch_private_marker,
)
from fdai.core.conversation_assurance.local_supervisor import (  # noqa: E402
    request as request_supervisor,
)
from fdai.core.conversation_assurance.local_supervisor import (  # noqa: E402
    serve as serve_supervisor,
)

_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_TOKEN_BYTES = 16 * 1024
_STATE_ROOT = Path(".fdai/conversation-assurance")


class OperatorHttpEvaluator:
    """Measure one case through an authenticated Operator API stream exactly once."""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
    ) -> None:
        if not (
            base_url.startswith("https://")
            or base_url.startswith("http://127.0.0.1:")
            or base_url.startswith("http://localhost:")
        ):
            raise ValueError("Operator URL MUST use HTTPS or loopback HTTP")
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token

    async def evaluate(
        self,
        case: PantheonCensusCase,
        *,
        campaign_id: str,
    ) -> PantheonTurnDiagnostic:
        terminal = await asyncio.to_thread(self._request, case, campaign_id)
        trace_raw = terminal.get("pantheon_trace")
        observed_raw = terminal.get("pantheon_observations")
        reviews_raw = terminal.get("pantheon_semantic_reviews")
        if not isinstance(trace_raw, Mapping) or not isinstance(observed_raw, Mapping):
            raise CampaignHoldError("measurement_contract_unavailable")
        try:
            trace = ConversationTurnTraceReceipt.from_mapping(trace_raw)
            if trace.campaign_id != campaign_id:
                raise ValueError("campaign identity mismatch")
            observed = tuple(
                (rubric, _boolean(observed_raw.get(rubric.value), rubric.value))
                for rubric in required_observed_rubrics()
            )
            reviews = _semantic_reviews(reviews_raw)
            diagnostic_case = PantheonDiagnosticCase(
                case_id=case.case_id,
                expected_primary_agent=case.expected_primary_agent,
                expected_routing_method=case.expected_routing_method,
                allowed_contributors=case.allowed_contributors,
                expected_handoff=case.expected_handoff,
                expected_handoff_owner=case.expected_handoff_owner,
                t2_expectation=case.t2_expectation,
            )
        except (TypeError, ValueError) as error:
            raise CampaignHoldError("measurement_contract_invalid") from error
        return evaluate_pantheon_turn(
            case=diagnostic_case,
            trace=trace,
            observed_results=observed,
            semantic_reviews=reviews,
        )

    def _request(self, case: PantheonCensusCase, campaign_id: str) -> dict[str, Any]:
        body = json.dumps(
            {
                "request_id": str(uuid4()),
                "session_id": f"pantheon-assurance:{campaign_id}",
                "prompt": case.question,
                "locale": case.locale,
                "purpose": f"conversation-assurance:{case.case_id}",
                "view_context": {},
                "history": [],
                "include_model_trace": True,
            },
            ensure_ascii=False,
        ).encode()
        request = urllib.request.Request(  # noqa: S310 - URL validated at construction
            f"{self._base_url}/chat/stream",
            data=body,
            headers={
                "Authorization": f"Bearer {self._bearer_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            reason = (
                "provider_unavailable"
                if error.code in {429, 503}
                else f"operator_http_{error.code}"
            )
            raise CampaignHoldError(reason) from error
        except TimeoutError as error:
            raise CampaignHoldError("operator_timeout") from error
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise CampaignHoldError("operator_response_too_large")
        return _terminal_payload(raw.decode("utf-8"))


def _terminal_payload(raw: str) -> dict[str, Any]:
    terminal: dict[str, Any] | None = None
    for frame in raw.strip().split("\n\n"):
        event = "message"
        data: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data.append(line.removeprefix("data:").strip())
        if event == "done" and data:
            decoded = json.loads("\n".join(data))
            if isinstance(decoded, Mapping):
                terminal = {str(key): value for key, value in decoded.items()}
    if terminal is None:
        raise CampaignHoldError("terminal_response_missing")
    return terminal


def _semantic_reviews(value: object) -> tuple[PantheonSemanticReview, ...]:
    if not isinstance(value, list):
        return ()
    reviews: list[PantheonSemanticReview] = []
    for raw in value[:3]:
        if not isinstance(raw, Mapping):
            continue
        results = raw.get("results")
        if not isinstance(results, Mapping):
            continue
        reviews.append(
            PantheonSemanticReview(
                reviewer_identity=str(raw.get("reviewer_identity", "")),
                model_family=str(raw.get("model_family", "")),
                confidence=float(raw.get("confidence", 0.0)),
                results=tuple(
                    (rubric, _boolean(results.get(rubric.value), rubric.value))
                    for rubric in tuple(PantheonRubric)[10:15]
                ),
            )
        )
    return tuple(reviews)


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} MUST be boolean")
    return value


def _state_root(project: Path) -> Path:
    return project / _STATE_ROOT


def _token_from_private_file() -> str:
    configured = os.environ.get("FDAI_CONVERSATION_ASSURANCE_TOKEN_FILE", "").strip()
    if not configured:
        raise CampaignHoldError("operator_token_file_unavailable")
    path = Path(configured).expanduser()
    try:
        raw = read_private_text(path, max_bytes=_MAX_TOKEN_BYTES)
    except FileNotFoundError as error:
        raise CampaignHoldError("operator_token_file_unavailable") from error
    except (OSError, UnicodeError, ValueError) as error:
        raise CampaignHoldError("operator_token_file_not_private") from error
    if len(raw.encode("utf-8")) > _MAX_TOKEN_BYTES:
        raise CampaignHoldError("operator_token_file_not_private")
    token = raw.strip()
    if not token:
        raise CampaignHoldError("operator_token_unavailable")
    return token


def _selected_cases(
    *,
    suite: str,
    agent: str | None,
    questions: int | None,
) -> tuple[PantheonCensusCase, ...]:
    cases = build_pantheon_census(PANTHEON_SPECS).cases
    selected = tuple(
        case
        for case in cases
        if (suite == "census" or case.suite == suite)
        and (agent is None or case.expected_primary_agent == agent)
    )
    if questions is not None:
        selected = selected[:questions]
    if not selected:
        raise ValueError("campaign selection produced no cases")
    return selected


async def _start(project: Path, request: Mapping[str, object]) -> dict[str, object]:
    suite = str(request.get("suite", "census"))
    agent = request.get("agent")
    questions = request.get("questions")
    selected = _selected_cases(
        suite=suite,
        agent=str(agent) if isinstance(agent, str) else None,
        questions=int(questions) if isinstance(questions, int) else None,
    )
    if bool(request.get("dry_run", False)):
        return {
            "state": "preview",
            "questions": len(selected),
            "census_digest": build_pantheon_census(PANTHEON_SPECS).content_digest,
        }
    base_url = os.environ.get("FDAI_CONVERSATION_ASSURANCE_OPERATOR_URL", "").strip()
    if not base_url:
        raise CampaignHoldError("operator_url_unavailable")
    evaluator = OperatorHttpEvaluator(
        base_url=base_url,
        bearer_token=_token_from_private_file(),
    )
    controller = PantheonCampaignController(
        state_root=_state_root(project),
        evaluator=evaluator,
    )
    stop_path = _state_root(project) / "STOP"
    runner_lock = open_private_lock(_state_root(project) / "runner.lock")
    if runner_lock is None:
        raise CampaignHoldError("campaign_runner_active")
    with runner_lock:
        remove_private_marker(stop_path)
        results = await controller.run_series(selected)
    return {
        "state": results[-1].state.value,
        "campaigns": len(results),
        "evaluated": sum(item.evaluated for item in results),
        "requested": len(selected),
        "reason": results[-1].reason,
    }


def _status(project: Path) -> dict[str, object]:
    from fdai.core.conversation_assurance import PrivateJsonlLedger

    campaigns = PrivateJsonlLedger(_state_root(project) / "campaigns.jsonl").read(limit=200)
    evaluations = PrivateJsonlLedger(_state_root(project) / "evaluations.jsonl").read(limit=10_000)
    completed = [item for item in campaigns if item.get("event") == "campaign_completed"]
    return {
        "state": "idle",
        "campaigns": len(completed),
        "evaluations": len(evaluations),
        "latest_campaign": completed[-1] if completed else None,
        "stop_requested": private_marker_exists(_state_root(project) / "STOP"),
    }


def _report(project: Path, *, top: int) -> dict[str, object]:
    from fdai.core.conversation_assurance import PrivateJsonlLedger

    if not 1 <= top <= 100:
        raise ValueError("report top MUST be in [1, 100]")
    status = _status(project)
    evaluations = PrivateJsonlLedger(_state_root(project) / "evaluations.jsonl").read(limit=top)
    return {**status, "latest_evaluations": list(reversed(evaluations))}


def _report_markdown(report: Mapping[str, object]) -> str:
    latest = report.get("latest_evaluations")
    rows = latest if isinstance(latest, list) else []
    lines = [
        "# Conversation Assurance Report",
        "",
        f"- Campaigns: {report.get('campaigns', 0)}",
        f"- Evaluations: {report.get('evaluations', 0)}",
        f"- Stop requested: {str(report.get('stop_requested', False)).lower()}",
        "",
        "| Case | Agent | Locale | Score | Verdict |",
        "|---|---|---|---:|---|",
    ]
    for value in rows:
        if not isinstance(value, Mapping):
            continue
        lines.append(
            "| "
            + " | ".join(
                (
                    str(value.get("case_id", "")),
                    str(value.get("agent", "")),
                    str(value.get("locale", "")),
                    str(value.get("score", "")),
                    str(value.get("verdict", "")),
                )
            )
            + " |"
        )
    if not rows:
        lines.append("| - | - | - | - | not measured |")
    return "\n".join(lines)


def _serve(project: Path) -> int:
    root = _state_root(project)
    return serve_supervisor(
        socket_path=root / "control.sock",
        lock_path=root / "supervisor.lock",
        dispatch=lambda request: _dispatch(project, request),
    )


def _dispatch(project: Path, request: Mapping[str, object]) -> Mapping[str, object]:
    operation = request.get("operation")
    if operation == "start":
        try:
            return asyncio.run(_start(project, request))
        except CampaignHoldError as error:
            return {"state": "held", "reason": str(error)}
    if operation == "status":
        return _status(project)
    if operation == "report":
        top = request.get("top", 20)
        return _report(project, top=top if isinstance(top, int) else 20)
    if operation == "stop":
        stop = _state_root(project) / "STOP"
        touch_private_marker(stop)
        return {"state": "stop_requested"}
    return {"state": "rejected", "reason": "unsupported_operation"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=_ROOT)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("supervisor")
    start = subparsers.add_parser("start")
    start.add_argument("--suite", choices=("census", "agent", "routing", "t2"), default="census")
    start.add_argument("--agent", choices=tuple(spec.name for spec in PANTHEON_SPECS))
    start.add_argument("--questions", type=int)
    start.add_argument("--dry-run", action="store_true")
    subparsers.add_parser("status")
    report = subparsers.add_parser("report")
    report.add_argument("--top", type=int, default=20)
    subparsers.add_parser("stop")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    project = arguments.project.resolve()
    if arguments.operation == "supervisor":
        return _serve(project)
    request = {
        "operation": arguments.operation,
        "suite": getattr(arguments, "suite", None),
        "agent": getattr(arguments, "agent", None),
        "questions": getattr(arguments, "questions", None),
        "dry_run": getattr(arguments, "dry_run", False),
        "top": getattr(arguments, "top", None),
    }
    if arguments.operation == "stop":
        stop = _state_root(project) / "STOP"
        touch_private_marker(stop)
    try:
        response = request_supervisor(
            socket_path=_state_root(project) / "control.sock",
            payload=request,
        )
        if response is None:
            if arguments.operation == "start":
                response = asyncio.run(_start(project, request))
            elif arguments.operation == "stop":
                response = {"state": "stop_requested"}
            elif arguments.operation == "report":
                response = _report(project, top=arguments.top)
            else:
                response = _status(project)
    except CampaignHoldError as error:
        response = {"state": "held", "reason": str(error)}
    if arguments.operation == "report":
        print(_report_markdown(response))
    else:
        print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


__all__ = ["OperatorHttpEvaluator", "main"]

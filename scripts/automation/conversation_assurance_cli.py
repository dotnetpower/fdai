"""Explicit CLI and idle supervisor for Pantheon conversation diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

_ROOT = Path(__file__).resolve().parents[2]
_OPERATOR_HTTP_TIMEOUT_SECONDS = 100
_LOCAL_AUTH_TIMEOUT_SECONDS = 5
sys.path.insert(0, str(_ROOT))
for _source in ("services/core-control-plane/src", "packages/service-contracts/src"):
    sys.path.insert(0, str(_ROOT / _source))

from fdai.agents import PANTHEON_SPECS  # noqa: E402
from fdai.core.conversation_assurance import (  # noqa: E402
    CampaignHoldError,
    ConversationTurnTraceReceipt,
    PantheonCampaignController,
    PantheonCensus,
    PantheonCensusCase,
    PantheonDiagnosticCase,
    PantheonTurnDiagnostic,
    PrivateJsonlLedger,
    build_pantheon_census,
    content_digest,
    evaluate_pantheon_turn,
    open_private_lock,
    parse_pantheon_corpus,
    plan_campaign_series,
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
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_text  # noqa: E402
from scripts.automation.conversation_assurance_qualification import (  # noqa: E402
    PantheonCaseMeasurement,
    qualify_pantheon_series,
)

_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_TOKEN_BYTES = 16 * 1024
_MAX_CORPUS_BYTES = 16 * 1024 * 1024
_MAX_COPILOT_REVIEW_BYTES = 4 * 1024 * 1024
_MAX_TRANSCRIPT_TEXT_CHARS = 16_000
_STATE_ROOT = Path(".fdai/conversation-assurance")
_ASSESSMENT_REASON = re.compile(r"^[a-z][A-Za-z0-9_.:-]{0,127}$")


from scripts.automation.conversation_assurance_operator import (  # noqa: E402
    _assessment_reasons,
    _boolean,
    _open_operator_request,
    _semantic_reviews,
    _terminal_payload,
)
from scripts.automation.conversation_assurance_reporting import (  # noqa: E402
    _compare_transcripts,
    _copilot_export,
    _copilot_import,
    _report,
    _report_markdown,
    _state_root,
    _status,
)


class OperatorHttpEvaluator:
    """Measure one case through an authenticated Operator API stream exactly once."""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        turn_ledger: PrivateJsonlLedger,
        transcript_ledger: PrivateJsonlLedger | None = None,
    ) -> None:
        if not (
            base_url.startswith("https://")
            or base_url.startswith("http://127.0.0.1:")
            or base_url.startswith("http://localhost:")
        ):
            raise ValueError("Operator URL MUST use HTTPS or loopback HTTP")
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._turn_ledger = turn_ledger
        self._transcript_ledger = transcript_ledger

    async def evaluate(
        self,
        case: PantheonCensusCase,
        *,
        campaign_id: str,
    ) -> PantheonTurnDiagnostic:
        terminal = await asyncio.to_thread(self._request, case, campaign_id)
        self._record_transcript(case, campaign_id=campaign_id, terminal=terminal)
        assessment_state = terminal.get("assessment_state")
        if assessment_state in {"deferred", "held", "unavailable"}:
            assessment_reasons = _assessment_reasons(terminal.get("assessment_reasons"))
            reason = ",".join(assessment_reasons) or "unspecified"
            raise CampaignHoldError(f"assessment_{assessment_state}:{reason}")
        if terminal.get("status") == "held":
            receipt = terminal.get("semantic_receipt")
            terminal_reason = receipt.get("reason_code") if isinstance(receipt, Mapping) else None
            if (
                not isinstance(terminal_reason, str)
                or _ASSESSMENT_REASON.fullmatch(terminal_reason) is None
            ):
                terminal_reason = "terminal_held"
            raise CampaignHoldError(terminal_reason)
        assessment_reasons = _assessment_reasons(terminal.get("assessment_reasons"))
        if assessment_state != "completed":
            raise CampaignHoldError("assessment_state_unavailable")
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
        diagnostic = evaluate_pantheon_turn(
            case=diagnostic_case,
            trace=trace,
            observed_results=observed,
            semantic_reviews=reviews,
        )
        self._turn_ledger.append(trace.to_dict())
        return diagnostic

    def _record_transcript(
        self,
        case: PantheonCensusCase,
        *,
        campaign_id: str,
        terminal: Mapping[str, object],
    ) -> None:
        """Retain safe private turn content without changing qualification evidence."""

        if self._transcript_ledger is None:
            return
        answer_raw = terminal.get("answer")
        answer = answer_raw if isinstance(answer_raw, str) else None
        question_sensitive = bool(scan_text(case.question))
        answer_sensitive = answer is not None and bool(scan_text(answer))
        question_retained = (
            len(case.question) <= _MAX_TRANSCRIPT_TEXT_CHARS and not question_sensitive
        )
        answer_retained = (
            answer is not None
            and len(answer) <= _MAX_TRANSCRIPT_TEXT_CHARS
            and not answer_sensitive
        )
        trace = terminal.get("pantheon_trace")
        diagnostic = terminal.get("pantheon_diagnostic")
        self._transcript_ledger.append(
            {
                "schema_version": "1.0.0",
                "campaign_id": campaign_id,
                "case_id": case.case_id,
                "suite": case.suite,
                "locale": case.locale,
                "question": case.question if question_retained else None,
                "question_digest": content_digest(case.question),
                "answer": answer if answer_retained else None,
                "answer_digest": content_digest(answer) if answer is not None else None,
                "content_omissions": [
                    label
                    for label, omitted in (
                        ("question_sensitive", question_sensitive),
                        ("question_oversized", len(case.question) > _MAX_TRANSCRIPT_TEXT_CHARS),
                        ("answer_sensitive", answer_sensitive),
                        (
                            "answer_oversized",
                            answer is not None and len(answer) > _MAX_TRANSCRIPT_TEXT_CHARS,
                        ),
                    )
                    if omitted
                ],
                "answer_generation": terminal.get("answer_generation"),
                "evaluator_models": terminal.get("pantheon_evaluator_models", []),
                "terminal_state": terminal.get("status"),
                "assessment_state": terminal.get("assessment_state", terminal.get("status")),
                "assessment_reasons": terminal.get("assessment_reasons", []),
                "score": diagnostic.get("score") if isinstance(diagnostic, Mapping) else None,
                "verdict": diagnostic.get("verdict") if isinstance(diagnostic, Mapping) else None,
                "source_revision": (
                    trace.get("source_revision") if isinstance(trace, Mapping) else None
                ),
            }
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
            with _open_operator_request(
                request,
                timeout=_OPERATOR_HTTP_TIMEOUT_SECONDS,
            ) as response:  # noqa: S310
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
        except (urllib.error.URLError, OSError) as error:
            raise CampaignHoldError("operator_transport_unavailable") from error
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise CampaignHoldError("operator_response_too_large")
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CampaignHoldError("operator_response_invalid") from error
        return _terminal_payload(decoded)


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


def _validate_jwt_time_window(token: str) -> None:
    parts = token.split(".")
    if len(parts) != 3:
        return
    try:
        payload_segment = parts[1]
        padding = "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_segment + padding))
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise CampaignHoldError("operator_token_invalid") from error
    if not isinstance(payload, Mapping):
        raise CampaignHoldError("operator_token_invalid")
    now = datetime.now(UTC).timestamp()
    expires_at = payload.get("exp")
    not_before = payload.get("nbf")
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        raise CampaignHoldError("operator_token_invalid")
    if expires_at <= now:
        raise CampaignHoldError("operator_token_expired")
    if not_before is not None and (
        not isinstance(not_before, (int, float)) or isinstance(not_before, bool) or not_before > now
    ):
        raise CampaignHoldError("operator_token_not_yet_valid")


def _local_operator_session_token(base_url: str) -> str | None:
    normalized = base_url.rstrip("/")
    if not (
        normalized.startswith("http://127.0.0.1:") or normalized.startswith("http://localhost:")
    ):
        return None
    request = urllib.request.Request(  # noqa: S310 - restricted to loopback above
        f"{normalized}/local-auth/me",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with _open_operator_request(request, timeout=_LOCAL_AUTH_TIMEOUT_SECONDS) as response:
            token = str(response.headers.get("X-FDAI-Local-Session", "")).strip()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise CampaignHoldError(f"operator_local_auth_http_{error.code}") from error
    except TimeoutError as error:
        raise CampaignHoldError("operator_local_auth_timeout") from error
    except (urllib.error.URLError, OSError) as error:
        raise CampaignHoldError("operator_local_auth_unavailable") from error
    if not token:
        raise CampaignHoldError("operator_local_auth_invalid")
    return token


def _operator_bearer_token(base_url: str) -> str:
    local_token = _local_operator_session_token(base_url)
    if local_token is not None:
        return local_token
    token = _token_from_private_file()
    _validate_jwt_time_window(token)
    return token


def _selected_cases(
    *,
    suite: str,
    agent: str | None,
    questions: int | None,
    census: PantheonCensus | None = None,
) -> tuple[PantheonCensusCase, ...]:
    cases = (census or build_pantheon_census(PANTHEON_SPECS)).cases
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


def _load_private_corpus(path: Path) -> PantheonCensus:
    try:
        raw = read_private_text(path.expanduser(), max_bytes=_MAX_CORPUS_BYTES)
        return parse_pantheon_corpus(raw, PANTHEON_SPECS)
    except FileNotFoundError as error:
        raise CampaignHoldError("conversation_corpus_unavailable") from error
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise CampaignHoldError("conversation_corpus_invalid") from error


async def _start(project: Path, request: Mapping[str, object]) -> dict[str, object]:
    suite = str(request.get("suite", "census"))
    agent = request.get("agent")
    questions = request.get("questions")
    corpus_path = request.get("corpus")
    census = (
        _load_private_corpus(Path(corpus_path))
        if isinstance(corpus_path, str) and corpus_path.strip()
        else build_pantheon_census(PANTHEON_SPECS)
    )
    selected = _selected_cases(
        suite=suite,
        agent=str(agent) if isinstance(agent, str) else None,
        questions=int(questions) if isinstance(questions, int) else None,
        census=census,
    )
    plan = plan_campaign_series(selected)
    if bool(request.get("dry_run", False)):
        return {
            "state": "preview",
            "questions": plan.question_count,
            "campaigns": plan.child_count,
            "census_digest": census.content_digest,
        }
    base_url = os.environ.get("FDAI_CONVERSATION_ASSURANCE_OPERATOR_URL", "").strip()
    if not base_url:
        raise CampaignHoldError("operator_url_unavailable")
    evaluator = OperatorHttpEvaluator(
        base_url=base_url,
        bearer_token=_operator_bearer_token(base_url),
        turn_ledger=PrivateJsonlLedger(_state_root(project) / "turns.jsonl"),
        transcript_ledger=PrivateJsonlLedger(_state_root(project) / "transcripts.jsonl"),
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
    qualification: dict[str, object] | None = None
    census = build_pantheon_census(PANTHEON_SPECS)
    if (
        len(selected) == len(census.cases)
        and {case.case_id for case in selected} == {case.case_id for case in census.cases}
        and all(
            result.state.value == "completed" and result.evaluated == result.requested
            for result in results
        )
    ):
        parent_series_id = _parent_series_id(project, tuple(item.campaign_id for item in results))
        qualification = _record_qualification(project, parent_series_id, census)
    return {
        "state": results[-1].state.value,
        "campaigns": len(results),
        "evaluated": sum(item.evaluated for item in results),
        "requested": len(selected),
        "reason": results[-1].reason,
        "qualification": qualification,
    }


def _record_qualification(
    project: Path,
    parent_series_id: str,
    census: PantheonCensus,
) -> dict[str, object]:
    root = _state_root(project)
    campaigns = PrivateJsonlLedger(root / "campaigns.jsonl")
    try:
        campaign_rows = campaigns.read(limit=10_000)
        child_ids = {
            str(row.get("campaign_id"))
            for row in campaign_rows
            if row.get("event") == "campaign_started"
            and row.get("parent_series_id") == parent_series_id
        }
        completed_children = [
            row
            for row in campaign_rows
            if row.get("event") == "campaign_completed"
            and row.get("parent_series_id") == parent_series_id
            and row.get("state") == "completed"
            and row.get("evaluated") == row.get("requested")
        ]
        completed_child_ids = {str(row.get("campaign_id")) for row in completed_children}
        if (
            not child_ids
            or len(completed_children) != len(completed_child_ids)
            or completed_child_ids != child_ids
            or any(
                not isinstance(row.get("requested"), int)
                or isinstance(row.get("requested"), bool)
                or not 1 <= row["requested"] <= 20
                for row in completed_children
            )
            or sum(int(row["requested"]) for row in completed_children) != len(census.cases)
        ):
            raise CampaignHoldError("qualification_campaign_incomplete")
        turns = PrivateJsonlLedger(root / "turns.jsonl").read(limit=10_000)
        evaluations = PrivateJsonlLedger(root / "evaluations.jsonl").read(limit=10_000)
        turn_by_digest: dict[str, ConversationTurnTraceReceipt] = {}
        for row in turns:
            if row.get("campaign_id") not in child_ids:
                continue
            trace = ConversationTurnTraceReceipt.from_mapping(row)
            if trace.receipt_digest in turn_by_digest:
                raise CampaignHoldError("qualification_trace_duplicate")
            turn_by_digest[trace.receipt_digest] = trace
        diagnostic_by_digest: dict[str, tuple[str, PantheonTurnDiagnostic]] = {}
        for row in evaluations:
            if row.get("parent_series_id") != parent_series_id:
                continue
            evaluation_campaign_id = str(row.get("campaign_id"))
            if evaluation_campaign_id not in child_ids:
                raise CampaignHoldError("qualification_evaluation_campaign_mismatch")
            diagnostic = PantheonTurnDiagnostic.from_mapping(row)
            if diagnostic.trace_receipt_digest in diagnostic_by_digest:
                raise CampaignHoldError("qualification_diagnostic_duplicate")
            diagnostic_by_digest[diagnostic.trace_receipt_digest] = (
                evaluation_campaign_id,
                diagnostic,
            )
        if set(turn_by_digest) != set(diagnostic_by_digest):
            raise CampaignHoldError("qualification_measurement_pair_incomplete")
        measurements = tuple(
            PantheonCaseMeasurement(
                diagnostic=diagnostic_by_digest[digest][1],
                trace=trace,
            )
            for digest, trace in turn_by_digest.items()
            if diagnostic_by_digest[digest][0] == trace.campaign_id
        )
        if len(measurements) != len(turn_by_digest):
            raise CampaignHoldError("qualification_measurement_campaign_mismatch")
        evidence = qualify_pantheon_series(census, measurements)
    except CampaignHoldError as error:
        _append_qualification_hold(campaigns, parent_series_id, str(error))
        raise
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as error:
        reason = "qualification_evidence_invalid"
        _append_qualification_hold(campaigns, parent_series_id, reason)
        raise CampaignHoldError(reason) from error
    payload = {
        "event": "qualification_evidence",
        "parent_series_id": parent_series_id,
        **evidence.to_dict(),
    }
    prior = campaigns.read(limit=10_000)
    if not any(
        row.get("event") == "qualification_evidence"
        and row.get("parent_series_id") == parent_series_id
        and row.get("evidence_digest") == evidence.evidence_digest
        for row in prior
    ):
        campaigns.append(payload)
    return payload


def _parent_series_id(project: Path, campaign_ids: tuple[str, ...]) -> str:
    campaigns = PrivateJsonlLedger(_state_root(project) / "campaigns.jsonl").read(limit=10_000)
    expected = set(campaign_ids)
    parent_ids = {
        str(row.get("parent_series_id"))
        for row in campaigns
        if row.get("event") == "campaign_started"
        and row.get("campaign_id") in expected
        and row.get("parent_series_id")
    }
    matched = {
        str(row.get("campaign_id"))
        for row in campaigns
        if row.get("event") == "campaign_started" and row.get("campaign_id") in expected
    }
    if matched != expected or len(parent_ids) != 1:
        raise CampaignHoldError("qualification_series_identity_unavailable")
    return next(iter(parent_ids))


def _append_qualification_hold(
    campaigns: PrivateJsonlLedger,
    parent_series_id: str,
    reason: str,
) -> None:
    payload = {
        "schema_version": "1.0.0",
        "event": "qualification_held",
        "parent_series_id": parent_series_id,
        "state": "held",
        "reason": reason[:128],
        "qualification_authority": False,
        "execution_authority": False,
    }
    prior = campaigns.read(limit=10_000)
    if not any(
        row.get("event") == "qualification_held"
        and row.get("parent_series_id") == parent_series_id
        and row.get("reason") == payload["reason"]
        for row in prior
    ):
        campaigns.append(payload)


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
    start.add_argument("--corpus", type=Path)
    start.add_argument("--dry-run", action="store_true")
    subparsers.add_parser("status")
    report = subparsers.add_parser("report")
    report.add_argument("--top", type=int, default=20)
    compare = subparsers.add_parser("compare")
    compare.add_argument("--baseline-case", required=True)
    compare.add_argument("--candidate-case", required=True)
    subparsers.add_parser("stop")
    copilot_export = subparsers.add_parser("copilot-export")
    copilot_export.add_argument("--input", type=Path, required=True)
    copilot_export.add_argument("--output", type=Path, required=True)
    copilot_import = subparsers.add_parser("copilot-import")
    copilot_import.add_argument("--packet", type=Path, required=True)
    copilot_import.add_argument("--result", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    project = arguments.project.resolve()
    if arguments.operation == "supervisor":
        return _serve(project)
    if arguments.operation in {"copilot-export", "copilot-import"}:
        try:
            copilot_response = (
                _copilot_export(
                    project,
                    source=arguments.input.resolve(),
                    output=arguments.output.resolve(),
                )
                if arguments.operation == "copilot-export"
                else _copilot_import(
                    project,
                    packet_path=arguments.packet.resolve(),
                    result_path=arguments.result.resolve(),
                )
            )
        except CampaignHoldError as error:
            copilot_response = {"state": "held", "reason": str(error)}
        print(json.dumps(copilot_response, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if arguments.operation == "compare":
        try:
            comparison = _compare_transcripts(
                project,
                baseline_case=arguments.baseline_case,
                candidate_case=arguments.candidate_case,
            )
        except CampaignHoldError as error:
            comparison = {"state": "held", "reason": str(error)}
        print(json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    request = {
        "operation": arguments.operation,
        "suite": getattr(arguments, "suite", None),
        "agent": getattr(arguments, "agent", None),
        "questions": getattr(arguments, "questions", None),
        "corpus": (
            str(arguments.corpus.resolve())
            if getattr(arguments, "corpus", None) is not None
            else None
        ),
        "dry_run": getattr(arguments, "dry_run", False),
        "top": getattr(arguments, "top", None),
    }
    if arguments.operation == "stop":
        stop = _state_root(project) / "STOP"
        touch_private_marker(stop)
    response: Mapping[str, object] | None
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

"""Explicit CLI and idle supervisor for Pantheon conversation diagnostics."""

from __future__ import annotations

import argparse
import asyncio
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
sys.path.insert(0, str(_ROOT))
for _source in ("services/core-control-plane/src", "packages/service-contracts/src"):
    sys.path.insert(0, str(_ROOT / _source))

from fdai.agents import PANTHEON_SPECS  # noqa: E402
from fdai.core.conversation_assurance import (  # noqa: E402
    COPILOT_RUBRIC_NAMES,
    CampaignHoldError,
    ConversationTurnTraceReceipt,
    PantheonCampaignController,
    PantheonCensus,
    PantheonCensusCase,
    PantheonDiagnosticCase,
    PantheonRubric,
    PantheonSemanticReview,
    PantheonTurnDiagnostic,
    PrivateJsonlLedger,
    build_copilot_review_packet,
    build_pantheon_census,
    evaluate_pantheon_turn,
    import_copilot_review,
    open_private_lock,
    parse_pantheon_corpus,
    plan_campaign_series,
    private_marker_exists,
    read_private_text,
    remove_private_marker,
    required_observed_rubrics,
    touch_private_marker,
    validate_copilot_review_packet,
    write_copilot_review_packet,
)
from fdai.core.conversation_assurance.local_supervisor import (  # noqa: E402
    request as request_supervisor,
)
from fdai.core.conversation_assurance.local_supervisor import (  # noqa: E402
    serve as serve_supervisor,
)
from scripts.automation.conversation_assurance_qualification import (  # noqa: E402
    PantheonCaseMeasurement,
    qualify_pantheon_series,
)

_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_TOKEN_BYTES = 16 * 1024
_MAX_CORPUS_BYTES = 16 * 1024 * 1024
_MAX_COPILOT_REVIEW_BYTES = 4 * 1024 * 1024
_STATE_ROOT = Path(".fdai/conversation-assurance")
_ASSESSMENT_REASON = re.compile(r"^[a-z][A-Za-z0-9_.:-]{0,127}$")


class OperatorHttpEvaluator:
    """Measure one case through an authenticated Operator API stream exactly once."""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        turn_ledger: PrivateJsonlLedger,
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

    async def evaluate(
        self,
        case: PantheonCensusCase,
        *,
        campaign_id: str,
    ) -> PantheonTurnDiagnostic:
        terminal = await asyncio.to_thread(self._request, case, campaign_id)
        if terminal.get("status") == "held":
            receipt = terminal.get("semantic_receipt")
            reason = receipt.get("reason_code") if isinstance(receipt, Mapping) else None
            if not isinstance(reason, str) or _ASSESSMENT_REASON.fullmatch(reason) is None:
                reason = "terminal_held"
            raise CampaignHoldError(reason)
        assessment_state = terminal.get("assessment_state")
        assessment_reasons = _assessment_reasons(terminal.get("assessment_reasons"))
        if assessment_state == "deferred":
            reason = ",".join(assessment_reasons) or "unspecified"
            raise CampaignHoldError(f"assessment_deferred:{reason}")
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


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _open_operator_request(request: urllib.request.Request, *, timeout: int) -> Any:
    return urllib.request.build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


def _terminal_payload(raw: str) -> dict[str, Any]:
    terminal: dict[str, Any] | None = None
    terminal_seen = False
    for frame in re.split(r"\r?\n\r?\n", raw.strip()):
        event = "message"
        data: list[str] = []
        for line in frame.splitlines():
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data.append(line.removeprefix("data:").strip())
        if not data:
            continue
        if terminal_seen or event == "error":
            raise CampaignHoldError("terminal_response_invalid")
        if event != "done":
            continue
        try:
            decoded = json.loads("\n".join(data))
        except json.JSONDecodeError as error:
            raise CampaignHoldError("terminal_response_invalid") from error
        if not isinstance(decoded, Mapping):
            raise CampaignHoldError("terminal_response_invalid")
        terminal = {str(key): value for key, value in decoded.items()}
        terminal_seen = True
    if terminal is None:
        raise CampaignHoldError("terminal_response_missing")
    return terminal


def _assessment_reasons(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 16:
        raise CampaignHoldError("assessment_reasons_invalid")
    reasons = tuple(value)
    if any(
        not isinstance(reason, str) or _ASSESSMENT_REASON.fullmatch(reason) is None
        for reason in reasons
    ):
        raise CampaignHoldError("assessment_reasons_invalid")
    return reasons


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
        bearer_token=_token_from_private_file(),
        turn_ledger=PrivateJsonlLedger(_state_root(project) / "turns.jsonl"),
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


def _status(project: Path) -> dict[str, object]:
    campaigns = PrivateJsonlLedger(_state_root(project) / "campaigns.jsonl").read(limit=10_000)
    evaluations = PrivateJsonlLedger(_state_root(project) / "evaluations.jsonl").read(limit=10_000)
    copilot_reviews = PrivateJsonlLedger(_state_root(project) / "copilot-reviews.jsonl").read(
        limit=10_000
    )
    completed = [item for item in campaigns if item.get("event") == "campaign_completed"]
    qualifications = [
        item
        for item in campaigns
        if item.get("event") in {"qualification_evidence", "qualification_held"}
    ]
    return {
        "state": "idle",
        "campaigns": len(completed),
        "evaluations": len(evaluations),
        "copilot_reviews": len(copilot_reviews),
        "latest_copilot_review": copilot_reviews[-1] if copilot_reviews else None,
        "latest_campaign": completed[-1] if completed else None,
        "latest_qualification": qualifications[-1] if qualifications else None,
        "stop_requested": private_marker_exists(_state_root(project) / "STOP"),
    }


def _report(project: Path, *, top: int) -> dict[str, object]:
    if not 1 <= top <= 100:
        raise ValueError("report top MUST be in [1, 100]")
    status = _status(project)
    evaluations = PrivateJsonlLedger(_state_root(project) / "evaluations.jsonl").read(limit=top)
    return {**status, "latest_evaluations": list(reversed(evaluations))}


def _report_markdown(report: Mapping[str, object]) -> str:
    latest = report.get("latest_evaluations")
    rows = latest if isinstance(latest, list) else []
    qualification = report.get("latest_qualification")
    lines = [
        "# Conversation Assurance Report",
        "",
        f"- Campaigns: {report.get('campaigns', 0)}",
        f"- Evaluations: {report.get('evaluations', 0)}",
        f"- Stop requested: {str(report.get('stop_requested', False)).lower()}",
    ]
    if isinstance(qualification, Mapping):
        if qualification.get("event") == "qualification_held":
            lines.append(f"- Qualification: held ({qualification.get('reason', '')})")
            qualification = None
    if isinstance(qualification, Mapping):
        metrics = qualification.get("metrics")
        metric_values = metrics if isinstance(metrics, Mapping) else {}
        lines.extend(
            (
                f"- Source revision: {qualification.get('source_revision', '')}",
                f"- Qualified: {str(qualification.get('qualified', False)).lower()}",
                f"- Explicit target accuracy: {metric_values.get('explicit_target_accuracy', '')}",
                f"- Owner routing F1: {metric_values.get('owner_routing_f1', '')}",
                f"- Missed T2 rate: {metric_values.get('missed_t2_rate', '')}",
                f"- Unnecessary T2 rate: {metric_values.get('unnecessary_t2_rate', '')}",
                f"- Minimum score: {metric_values.get('minimum_score', '')}",
                f"- Hard-zero count: {metric_values.get('hard_zero_count', '')}",
            )
        )
    fixed_questions = {
        case.case_id: case.question for case in build_pantheon_census(PANTHEON_SPECS).cases
    }
    lines.extend(
        (
            "",
            "| Case | Question | Answer | Agent | Locale | Score | Verdict |",
            "|---|---|---|---|---|---:|---|",
        )
    )
    for value in rows:
        if not isinstance(value, Mapping):
            continue
        lines.append(
            "| "
            + " | ".join(
                (
                    str(value.get("case_id", "")),
                    fixed_questions.get(str(value.get("case_id", "")), "not retained"),
                    "not retained (content-free ledger)",
                    str(value.get("agent", "")),
                    str(value.get("locale", "")),
                    str(value.get("score", "")),
                    str(value.get("verdict", "")),
                )
            )
            + " |"
        )
    if not rows:
        lines.append("| - | - | - | - | - | - | not measured |")
    return "\n".join(lines)


def _serve(project: Path) -> int:
    root = _state_root(project)
    return serve_supervisor(
        socket_path=root / "control.sock",
        lock_path=root / "supervisor.lock",
        dispatch=lambda request: _dispatch(project, request),
    )


def _private_json(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(read_private_text(path, max_bytes=_MAX_COPILOT_REVIEW_BYTES))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise CampaignHoldError("copilot_review_file_invalid") from error
    if not isinstance(raw, Mapping):
        raise CampaignHoldError("copilot_review_file_invalid")
    return {str(key): value for key, value in raw.items()}


def _copilot_export(project: Path, *, source: Path, output: Path) -> dict[str, object]:
    raw = _private_json(source)
    cases = raw.get("cases")
    if not isinstance(cases, list):
        raise CampaignHoldError("copilot_review_cases_invalid")
    try:
        packet = build_copilot_review_packet(
            cases,
            created_at=datetime.now(UTC).isoformat(),
        )
        write_copilot_review_packet(output, packet)
    except (OSError, ValueError) as error:
        raise CampaignHoldError("copilot_review_export_failed") from error
    return {
        "state": "exported",
        "packet_id": packet["packet_id"],
        "packet_digest": packet["packet_digest"],
        "cases": len(cases),
        "rubric_count": len(COPILOT_RUBRIC_NAMES),
        "output": str(output),
        "reviewer_kind": packet["reviewer_kind"],
        "qualification_authority": False,
        "execution_authority": False,
    }


def _copilot_import(project: Path, *, packet_path: Path, result_path: Path) -> dict[str, object]:
    try:
        packet = validate_copilot_review_packet(_private_json(packet_path))
        result = import_copilot_review(
            packet=packet,
            result=_private_json(result_path),
            ledger=PrivateJsonlLedger(_state_root(project) / "copilot-reviews.jsonl"),
        )
    except (OSError, ValueError) as error:
        raise CampaignHoldError("copilot_review_import_failed") from error
    reviews = result.get("reviews")
    if not isinstance(reviews, list):
        raise CampaignHoldError("copilot_review_import_failed")
    return {
        "state": "duplicate" if result["duplicate"] else "imported",
        "review_id": result["review_id"],
        "packet_digest": result["packet_digest"],
        "reviews": len(reviews),
        "reviewer_kind": result["reviewer_kind"],
        "qualification_authority": False,
        "execution_authority": False,
    }


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

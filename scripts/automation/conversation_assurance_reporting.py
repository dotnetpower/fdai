"""Private reports and Copilot packets for conversation assurance."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from fdai.agents import PANTHEON_SPECS  # noqa: E402
from fdai.core.conversation_assurance import (  # noqa: E402
    COPILOT_RUBRIC_NAMES,
    CampaignHoldError,
    PrivateJsonlLedger,
    build_copilot_review_packet,
    build_pantheon_census,
    import_copilot_review,
    private_marker_exists,
    read_private_text,
    validate_copilot_review_packet,
    write_copilot_review_packet,
)

_MAX_COPILOT_REVIEW_BYTES = 4 * 1024 * 1024
_STATE_ROOT = Path(".fdai/conversation-assurance")


def _state_root(project: Path) -> Path:
    return project / _STATE_ROOT


def _status(project: Path) -> dict[str, object]:
    campaigns = PrivateJsonlLedger(_state_root(project) / "campaigns.jsonl").read(limit=10_000)
    evaluations = PrivateJsonlLedger(_state_root(project) / "evaluations.jsonl").read(limit=10_000)
    copilot_reviews = PrivateJsonlLedger(_state_root(project) / "copilot-reviews.jsonl").read(
        limit=10_000
    )
    transcripts = PrivateJsonlLedger(_state_root(project) / "transcripts.jsonl").read(limit=10_000)
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
        "transcripts": len(transcripts),
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
    transcripts = PrivateJsonlLedger(_state_root(project) / "transcripts.jsonl").read(limit=top)
    return {
        **status,
        "latest_evaluations": list(reversed(evaluations)),
        "latest_transcripts": list(reversed(transcripts)),
    }


def _report_markdown(report: Mapping[str, object]) -> str:
    transcript_values = report.get("latest_transcripts")
    transcript_rows = transcript_values if isinstance(transcript_values, list) else []
    latest = report.get("latest_evaluations")
    rows = latest if isinstance(latest, list) else []
    qualification = report.get("latest_qualification")
    lines = [
        "# Conversation Assurance Report",
        "",
        f"- Campaigns: {report.get('campaigns', 0)}",
        f"- Evaluations: {report.get('evaluations', 0)}",
        f"- Transcripts: {report.get('transcripts', 0)}",
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
    if transcript_rows:
        lines.extend(
            (
                "",
                "| Case | Question | Answer | Generation | Evaluators | Score | Verdict | "
                "Problems | Revision |",
                "|---|---|---|---|---|---:|---|---|---|",
            )
        )
        for value in transcript_rows:
            if not isinstance(value, Mapping):
                continue
            generation = value.get("answer_generation")
            generation_values = generation if isinstance(generation, Mapping) else {}
            evaluator_values = value.get("evaluator_models")
            evaluators = evaluator_values if isinstance(evaluator_values, list) else []
            lines.append(
                "| "
                + " | ".join(
                    _markdown_cell(item)
                    for item in (
                        value.get("case_id", ""),
                        value.get("question") or "omitted",
                        value.get("answer") or "no answer retained",
                        generation_values.get("model_identity")
                        or generation_values.get("mode", "unavailable"),
                        ", ".join(
                            str(item.get("model_identity", ""))
                            for item in evaluators
                            if isinstance(item, Mapping)
                        )
                        or "none",
                        value.get("score", ""),
                        value.get("verdict", ""),
                        ", ".join(str(item) for item in value.get("assessment_reasons", []))
                        or "none",
                        value.get("source_revision", ""),
                    )
                )
                + " |"
            )
        return "\n".join(lines)
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


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _compare_transcripts(
    project: Path,
    *,
    baseline_case: str,
    candidate_case: str,
) -> dict[str, object]:
    rows = PrivateJsonlLedger(_state_root(project) / "transcripts.jsonl").read(limit=10_000)
    baseline = next(
        (row for row in reversed(rows) if row.get("case_id") == baseline_case),
        None,
    )
    candidate = next(
        (row for row in reversed(rows) if row.get("case_id") == candidate_case),
        None,
    )
    if baseline is None or candidate is None:
        raise CampaignHoldError("comparison_transcript_unavailable")
    baseline_score = baseline.get("score")
    candidate_score = candidate.get("score")
    if (
        not isinstance(baseline_score, int)
        or isinstance(baseline_score, bool)
        or not isinstance(candidate_score, int)
        or isinstance(candidate_score, bool)
    ):
        outcome = "unscorable"
        score_delta: int | None = None
    else:
        score_delta = candidate_score - baseline_score
        outcome = "improved" if score_delta > 0 else "regressed" if score_delta < 0 else "unchanged"
    return {
        "outcome": outcome,
        "score_delta": score_delta,
        "baseline": baseline,
        "candidate": candidate,
        "qualification_authority": False,
        "execution_authority": False,
    }


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

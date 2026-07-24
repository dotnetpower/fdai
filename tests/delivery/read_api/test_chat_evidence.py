"""Operational evidence retrieval for cross-screen Command Deck questions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.chat_evidence import (
    OperationalEvidenceResolver,
    _is_memory_incident_text,
    needs_operational_evidence,
)
from fdai.delivery.read_api.routes.chat_verification import verify_answer


@dataclass(frozen=True, slots=True)
class OperationalWeaknessCase:
    prompt: str
    expects_operational: bool
    korean: bool = False
    view_context: dict[str, Any] | None = None


OPERATIONAL_WEAKNESS_CASES = (
    OperationalWeaknessCase("what caused the recent memory issue?", True),
    OperationalWeaknessCase("latest host memory incident cause", True),
    OperationalWeaknessCase("root cause of the last OOM incident", True),
    OperationalWeaknessCase("recent memory failure", True),
    OperationalWeaknessCase("why did the recent memory outage happen?", True),
    OperationalWeaknessCase("latest available memory problem cause", True),
    OperationalWeaknessCase("최근 메모리 이슈 원인이 뭐야?", True, korean=True),
    OperationalWeaknessCase("직전 메모리 장애 근본 원인", True, korean=True),
    OperationalWeaknessCase("최근 OOM 인시던트 왜 발생했어?", True, korean=True),
    OperationalWeaknessCase("최신 host memory 실패 원인", True, korean=True),
    OperationalWeaknessCase("last memory pressure incident", True),
    OperationalWeaknessCase("recent incident caused by memory leak", True),
    OperationalWeaknessCase("why is this screen showing attention?", False),
    OperationalWeaknessCase("이 화면의 수치는 왜 이래?", False, korean=True),
    OperationalWeaknessCase("what is Issue?", False, view_context={"routeId": "ontology"}),
    OperationalWeaknessCase(
        "Agent와 연결된 Issue는 뭐야?",
        False,
        korean=True,
        view_context={"routeId": "ontology"},
    ),
    OperationalWeaknessCase("db 에는 어떤 데이터가 있어?", False, korean=True),
    OperationalWeaknessCase("overall system health", False),
    OperationalWeaknessCase("restart the database", False),
    OperationalWeaknessCase("show Azure resources", False),
)

OPERATIONAL_RUBRIC_NAMES = (
    "intent-classification",
    "resolver-selection",
    "authority-selection",
    "matched-state",
    "selected-correlation",
    "selected-title",
    "grounded-hypothesis",
    "grounded-cause",
    "citation-present",
    "ungrounded-excluded",
    "audit-evidence-bounded",
    "candidate-count",
    "verification-authority",
    "verification-reason",
    "terminal-trust",
    "locale-aligned",
    "canonical-cause-present",
    "incident-reference",
    "telemetry-reference",
    "no-unsupported-guess",
)


def _seed_memory_incident(
    model: InMemoryConsoleReadModel, correlation: str = "corr-memory"
) -> None:
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": correlation,
            "recorded_at": "2026-07-15T00:00:00+00:00",
            "summary": "Host memory pressure triggered an incident",
            "detail": "Available memory fell below the configured threshold.",
            "metric": "available_memory_bytes",
        },
        action_kind="incident.open",
    )
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": correlation,
            "recorded_at": "2026-07-15T00:01:00+00:00",
            "rca_outcome": "grounded",
            "rca_tier": "t0",
            "rca_cause": "A workload memory leak exhausted available host memory.",
            "rca_confidence": 0.96,
            "rca_reason": "The allocation increase preceded the pressure signal.",
            "rca_citations": [{"kind": "telemetry", "ref": "metric:available_memory_bytes"}],
        },
        action_kind="rca.hypothesis",
    )


def test_detects_cross_screen_operational_question_but_not_current_screen_cause() -> None:
    assert needs_operational_evidence("what caused the recent memory issue?") is True
    korean_recent = "최근 메모리 이슈 원인이 뭐야?"
    korean_screen = "이 화면의 이 수치는 왜 이래?"
    assert needs_operational_evidence(korean_recent) is True
    assert needs_operational_evidence("why is this screen showing attention?") is False
    assert needs_operational_evidence(korean_screen) is False


@pytest.mark.parametrize(
    "prompt",
    (
        "vscode 최신버전은?",
        "VS Code latest version?",
        "Python 최신버전은?",
        "latest Kubernetes release?",
    ),
)
def test_public_software_freshness_does_not_trigger_incident_lookup(prompt: str) -> None:
    assert needs_operational_evidence(prompt) is False


@pytest.mark.parametrize(
    "prompt",
    (
        "latest memory incident",
        "recent deployment failure",
        "최신 메모리 인시던트 원인은?",
        "최근 배포 실패를 보여줘",
    ),
)
def test_operational_recency_with_incident_context_still_resolves(prompt: str) -> None:
    assert needs_operational_evidence(prompt) is True


def test_ontology_issue_terms_alone_do_not_trigger_incident_lookup() -> None:
    ontology = {"routeId": "ontology"}
    assert needs_operational_evidence("what is Issue?", ontology) is False
    assert needs_operational_evidence("Agent와 연결된 Issue는 뭐야?", ontology) is False
    assert needs_operational_evidence("이슈는 뭐야?", ontology) is False
    assert needs_operational_evidence("recent memory issue cause", ontology) is True
    assert needs_operational_evidence("what issue happened?") is True


def test_memory_signal_tokens_do_not_match_headroom() -> None:
    assert _is_memory_incident_text("capacity has ample headroom") is False
    assert _is_memory_incident_text("the process was OOM killed") is True


async def test_resolves_recent_memory_incident_with_grounded_rca() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model)

    evidence = await OperationalEvidenceResolver(model).resolve("최근 메모리 이슈 원인이 뭐야?")

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert evidence["selected_incident"]["correlation_id"] == "corr-memory"
    assert evidence["grounded_hypotheses"][0]["cause"].startswith("A workload memory leak")
    assert evidence["grounded_hypotheses"][0]["citations"] == [
        {"kind": "telemetry", "ref": "metric:available_memory_bytes"}
    ]


async def test_excludes_ungrounded_rca_from_cause_evidence() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model)
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": "corr-memory",
            "recorded_at": "2026-07-15T00:02:00+00:00",
            "rca_outcome": "abstained",
            "rca_tier": "t2",
            "rca_cause": "Unsupported guess must not be presented.",
            "rca_reason": "No citations.",
            "rca_citations": [],
        },
        action_kind="rca.hypothesis",
    )

    evidence = await OperationalEvidenceResolver(model).resolve("recent memory issue cause")

    assert evidence is not None
    causes = [item["cause"] for item in evidence["grounded_hypotheses"]]
    assert "Unsupported guess must not be presented." not in causes
    assert evidence["ungrounded_hypothesis_count"] == 1


async def test_returns_none_when_topic_does_not_match_recent_incidents() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model)

    evidence = await OperationalEvidenceResolver(model).resolve("recent network issue cause")

    assert evidence is not None
    assert evidence["status"] == "none"
    assert evidence["searched_recent_incidents"] == 1


async def test_incident_memory_index_is_not_a_host_memory_issue() -> None:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "evt-recall",
            "correlation_id": "corr-recall",
            "recorded_at": "2026-07-15T00:00:00+00:00",
            "summary": "Recalled a resolved incident",
            "detail": "Searched incident_memory with cosine similarity.",
        },
        action_kind="similarity.recall",
    )

    evidence = await OperationalEvidenceResolver(model).resolve("recent memory issue cause")

    assert evidence is not None
    assert evidence["status"] == "none"


async def test_returns_ambiguous_candidates_without_recency_tiebreak() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model, "corr-memory-a")
    _seed_memory_incident(model, "corr-memory-b")

    evidence = await OperationalEvidenceResolver(model).resolve("memory issue cause")

    assert evidence is not None
    assert evidence["status"] == "ambiguous"
    assert len(evidence["candidates"]) == 2


async def test_summary_request_returns_all_matching_incidents_without_selection() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model, "corr-memory-a")
    _seed_memory_incident(model, "corr-memory-b")

    evidence = await OperationalEvidenceResolver(model).resolve("인시던트를 요약해줘")

    assert evidence is not None
    assert evidence["status"] == "summary"
    assert {item["correlation_id"] for item in evidence["incidents"]} == {
        "corr-memory-a",
        "corr-memory-b",
    }
    assert evidence["searched_recent_incidents"] == 2

    english_evidence = await OperationalEvidenceResolver(model).resolve(
        "please summarize all the incidents"
    )

    assert english_evidence is not None
    assert english_evidence["status"] == "summary"
    assert len(english_evidence["incidents"]) == 2


async def test_exact_incident_binding_wins_over_equal_topic_matches() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model, "corr-memory-a")
    _seed_memory_incident(model, "corr-memory-b")

    evidence = await OperationalEvidenceResolver(model).resolve(
        "what is happening?",
        conversation_context={
            "kind": "incident",
            "incident_id": "INC-corr-memory-b",
            "correlation_id": "corr-memory-b",
            "selected_agent": "Var",
        },
    )

    assert evidence is not None
    assert evidence["status"] == "matched"
    assert evidence["selected_incident"]["correlation_id"] == "corr-memory-b"
    assert evidence["candidate_count"] == 1
    assert evidence["selected_agent_context"] == "Var"
    assert evidence["selected_incident"]["involved_agents"] == ["Forseti"]
    assert evidence["audit_evidence"][0]["agent"] == "Forseti"


async def test_stale_incident_binding_never_falls_back_to_fuzzy_match() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model, "corr-memory-a")

    evidence = await OperationalEvidenceResolver(model).resolve(
        "memory issue cause",
        conversation_context={
            "kind": "incident",
            "incident_id": "INC-missing",
            "correlation_id": "corr-missing",
        },
    )

    assert evidence is not None
    assert evidence["status"] == "none"
    assert "selected_incident" not in evidence


class _FailingReadModel(InMemoryConsoleReadModel):
    async def list_incidents(self, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("database unavailable")


async def test_lookup_error_fails_closed_without_exception() -> None:
    evidence = await OperationalEvidenceResolver(_FailingReadModel()).resolve(
        "recent memory issue cause"
    )

    assert evidence == {
        "authority": "server_read_model",
        "status": "unavailable",
        "reason": "operational evidence lookup failed",
    }


async def test_twenty_operational_weaknesses_pass_twenty_answer_rubrics() -> None:
    model = InMemoryConsoleReadModel()
    _seed_memory_incident(model)
    model.record_audit_entry(
        {
            "event_id": "evt-memory",
            "correlation_id": "corr-memory",
            "recorded_at": "2026-07-15T00:02:00+00:00",
            "rca_outcome": "abstained",
            "rca_tier": "t2",
            "rca_cause": "Unsupported guess must not be presented.",
            "rca_reason": "No citations.",
            "rca_citations": [],
        },
        action_kind="rca.hypothesis",
    )
    resolver = OperationalEvidenceResolver(model)
    failures: list[str] = []
    passed = 0
    total = len(OPERATIONAL_WEAKNESS_CASES) * len(OPERATIONAL_RUBRIC_NAMES)

    for case_number, case in enumerate(OPERATIONAL_WEAKNESS_CASES, 1):
        selected = needs_operational_evidence(case.prompt, case.view_context)
        evidence = await resolver.resolve(case.prompt) if selected else None
        verification = (
            verify_answer(
                "Unsupported guess must not be presented.",
                {"_operational_evidence": evidence},
                locale="ko" if case.korean else "en",
            )
            if evidence is not None
            else None
        )
        results = _score_operational_answer(
            case,
            selected=selected,
            evidence=evidence,
            verification=verification,
        )
        assert len(results) == len(OPERATIONAL_RUBRIC_NAMES)
        for rubric, result in zip(OPERATIONAL_RUBRIC_NAMES, results, strict=True):
            if result:
                passed += 1
            else:
                failures.append(f"Q{case_number:02d} {rubric}: {case.prompt}")

    assert not failures, f"operational rubric score {passed}/{total}\n" + "\n".join(failures)


def _score_operational_answer(
    case: OperationalWeaknessCase,
    *,
    selected: bool,
    evidence: Any,
    verification: Any,
) -> tuple[bool, ...]:
    applicable = case.expects_operational
    safe_evidence = evidence if isinstance(evidence, dict) else {}
    selected_incident = safe_evidence.get("selected_incident")
    incident = selected_incident if isinstance(selected_incident, dict) else {}
    raw_hypotheses = safe_evidence.get("grounded_hypotheses")
    hypotheses = raw_hypotheses if isinstance(raw_hypotheses, list) else []
    hypothesis = hypotheses[0] if hypotheses and isinstance(hypotheses[0], dict) else {}
    raw_citations = hypothesis.get("citations")
    citations = raw_citations if isinstance(raw_citations, list) else []
    audit = safe_evidence.get("audit_evidence")
    answer = verification.answer if verification is not None else ""
    refs = verification.evidence_refs if verification is not None else ()
    korean_rendered = "검증된 원인" in answer
    return (
        selected == applicable,
        (evidence is not None) == applicable,
        (safe_evidence.get("authority") == "server_read_model") == applicable,
        (safe_evidence.get("status") == "matched") == applicable,
        (incident.get("correlation_id") == "corr-memory") == applicable,
        ("memory" in str(incident.get("title", "")).casefold()) == applicable,
        bool(hypotheses) == applicable,
        ("memory leak" in str(hypothesis.get("cause", "")).casefold()) == applicable,
        bool(citations) == applicable,
        "Unsupported guess" not in str(hypotheses),
        (isinstance(audit, list) and 0 < len(audit) <= 20) == applicable,
        (safe_evidence.get("candidate_count") == 1) == applicable,
        (verification is not None and verification.authority == "server_read_model") == applicable,
        (verification is not None and verification.reason_code == "grounded_rca") == applicable,
        (verification is not None and verification.status in {"verified", "corrected"})
        == applicable,
        not applicable or korean_rendered == case.korean,
        ("memory leak" in answer.casefold()) == applicable,
        ("incident:corr-memory" in refs) == applicable,
        ("telemetry:metric:available_memory_bytes" in refs) == applicable,
        "Unsupported guess" not in answer,
    )

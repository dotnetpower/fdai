"""Operational evidence retrieval for cross-screen Command Deck questions."""

from __future__ import annotations

from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.chat_evidence import (
    OperationalEvidenceResolver,
    _is_memory_incident_text,
    needs_operational_evidence,
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
    korean_recent = "\ucd5c\uadfc \uba54\ubaa8\ub9ac \uc774\uc288 \uc6d0\uc778\uc774 \ubb50\uc57c?"
    korean_screen = "\uc774 \ud654\uba74\uc758 \uc774 \uc218\uce58\ub294 \uc65c \uc774\ub798?"
    assert needs_operational_evidence(korean_recent) is True
    assert needs_operational_evidence("why is this screen showing attention?") is False
    assert needs_operational_evidence(korean_screen) is False


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

    evidence = await OperationalEvidenceResolver(model).resolve(
        "\ucd5c\uadfc \uba54\ubaa8\ub9ac \uc774\uc288 \uc6d0\uc778\uc774 \ubb50\uc57c?"
    )

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

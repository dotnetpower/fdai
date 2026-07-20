"""Server-owned operational evidence retrieval for Command Deck chat.

The browser snapshot explains the current screen. Cross-screen operational
questions need a different authority: the read model that projects the audit
ledger. This module detects those questions, searches a bounded recent
incident set, and returns compact incident, audit, and grounded-RCA evidence.
It never mutates state and never asks a model to choose what data to fetch.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from fdai.delivery.read_api.read_model import AuditItem, ConsoleReadModel, IncidentSummary
from fdai.delivery.read_api.routes.rca_projection import project_rca

_LOG = logging.getLogger(__name__)

_OPERATIONAL_INTENT: Final = re.compile(
    r"\b(recent|latest|last|incident|issue|outage|failure|problem|root cause|cause|why did)\b"
    "|\ucd5c\uadfc|\ucd5c\uc2e0|\uc9c1\uc804|\uc778\uc2dc\ub358\ud2b8|\uc774\uc288|\uc7a5\uc560"
    "|\uc2e4\ud328|\ubb38\uc81c|\uc6d0\uc778|\uadfc\ubcf8 \uc6d0\uc778",
    re.IGNORECASE,
)
_EXPLICIT_OPERATIONAL_CONTEXT: Final = re.compile(
    r"\b(recent|latest|last|incident|outage|failure|root cause|cause|why did)\b"
    "|\ucd5c\uadfc|\ucd5c\uc2e0|\uc9c1\uc804|\uc778\uc2dc\ub358\ud2b8|\uc7a5\uc560"
    "|\uc2e4\ud328|\uc6d0\uc778|\uadfc\ubcf8 \uc6d0\uc778",
    re.IGNORECASE,
)
_CURRENT_SCREEN_ONLY: Final = re.compile(
    r"\b(this screen|this page|this tile|selected|on screen|shown here)\b"
    "|\uc774 \ud654\uba74|\uc774 \ud398\uc774\uc9c0|\uc774 \ud0c0\uc77c|\uc120\ud0dd\ud55c"
    "|\ud654\uba74\uc5d0",
    re.IGNORECASE,
)
_RECENCY_INTENT: Final = re.compile(
    r"\b(recent|latest|last|newest)\b|\ucd5c\uadfc|\ucd5c\uc2e0|\uc9c1\uc804",
    re.IGNORECASE,
)
_WORD: Final = re.compile(r"[a-z][a-z0-9_-]{2,}", re.IGNORECASE)
_STOP_WORDS: Final = frozenset(
    {
        "about",
        "cause",
        "caused",
        "could",
        "failure",
        "incident",
        "issue",
        "latest",
        "last",
        "problem",
        "recent",
        "root",
        "tell",
        "that",
        "what",
        "when",
        "where",
        "which",
        "why",
    }
)
_TOPIC_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "memory": (
        "memory",
        "oom",
        "out of memory",
        "host_memory",
        "member_hotspot",
        "gpu_vram",
        "\uba54\ubaa8\ub9ac",
    ),
    "cpu": ("cpu", "processor", "compute", "\uc2dc\ud53c\uc720"),
    "latency": ("latency", "slow", "timeout", "\uc9c0\uc5f0", "\ub290\ub9bc"),
    "network": ("network", "dns", "connection", "nsg", "\ub124\ud2b8\uc6cc\ud06c"),
    "database": ("database", "postgres", "sql", "db", "\ub370\uc774\ud130\ubca0\uc774\uc2a4"),
    "storage": ("storage", "disk", "volume", "\uc2a4\ud1a0\ub9ac\uc9c0", "\ub514\uc2a4\ud06c"),
    "deployment": ("deployment", "release", "rollout", "\ubc30\ud3ec"),
    "quota": ("quota", "throttle", "rate limit", "tpm", "\ud560\ub2f9\ub7c9"),
    "cost": ("cost", "spend", "billing", "\ube44\uc6a9"),
}
_AUDIT_FIELDS: Final = (
    "summary",
    "detail",
    "reason",
    "outcome",
    "decision",
    "gate_decision",
    "status",
    "resource",
    "metric",
    "signal",
    "rca_cause",
    "rca_reason",
)


def needs_operational_evidence(
    prompt: str,
    view_context: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether a turn explicitly asks for operational evidence beyond the screen.

    ``Issue`` and ``problem`` alone are domain nouns on the ontology screen.
    That route requires recency, incident, outage, failure, or cause language
    before it leaves the current-screen authority.
    """

    operational = bool(
        _OPERATIONAL_INTENT.search(prompt) and not _CURRENT_SCREEN_ONLY.search(prompt)
    )
    if not operational:
        return False
    route = str((view_context or {}).get("routeId") or "").lower()
    return route != "ontology" or bool(_EXPLICIT_OPERATIONAL_CONTEXT.search(prompt))


def _topic_terms(prompt: str) -> tuple[str, ...]:
    lower = prompt.lower()
    terms = {
        canonical
        for canonical, aliases in _TOPIC_ALIASES.items()
        if any(alias in lower for alias in aliases)
    }
    terms.update(
        token.lower() for token in _WORD.findall(prompt) if token.lower() not in _STOP_WORDS
    )
    return tuple(sorted(terms))


def _compact_audit(item: AuditItem) -> dict[str, Any]:
    fields = {
        key: value
        for key in _AUDIT_FIELDS
        if (value := item.entry.get(key)) is not None and isinstance(value, (str, int, float, bool))
    }
    return {
        "seq": item.seq,
        "recorded_at": item.recorded_at,
        "actor": item.actor,
        "action_kind": item.action_kind,
        "mode": item.mode,
        "fields": fields,
    }


def _incident_dict(incident: IncidentSummary) -> dict[str, Any]:
    return {
        "correlation_id": incident.correlation_id,
        "incident_id": incident.incident_id,
        "title": incident.title,
        "severity": incident.severity,
        "status": incident.status,
        "disposition": incident.disposition,
        "verdict": incident.verdict,
        "vertical": incident.vertical,
        "opened_at": incident.opened_at,
        "last_updated_at": incident.last_updated_at,
    }


def _search_text(incident: IncidentSummary, audit: Sequence[AuditItem]) -> str:
    parts = [incident.title, incident.vertical, incident.disposition]
    for item in audit:
        parts.append(item.action_kind)
        parts.extend(str(item.entry.get(key, "")) for key in _AUDIT_FIELDS)
    return " ".join(parts).lower()


def _score(terms: Sequence[str], text: str) -> int:
    score = sum(1 for term in terms if term != "memory" and term in text)
    if "memory" in terms and _is_memory_incident_text(text):
        score += 1
    return score


def _is_memory_incident_text(text: str) -> bool:
    text = text.lower()
    phrases = (
        "memory issue",
        "memory leak",
        "memory pressure",
        "available memory",
        "available_memory",
        "host memory",
        "host_memory",
        "out of memory",
        "working set",
        "\uba54\ubaa8\ub9ac \uc774\uc288",
        "\uba54\ubaa8\ub9ac \ub204\uc218",
        "\uba54\ubaa8\ub9ac \uc555\ub825",
    )
    return any(phrase in text for phrase in phrases) or bool(
        re.search(r"\b(?:oom|rss|heap)\b", text)
    )


@dataclass(frozen=True, slots=True)
class OperationalEvidenceResolver:
    """Resolve bounded recent incident evidence from a ConsoleReadModel."""

    read_model: ConsoleReadModel
    incident_limit: int = 12
    audit_limit: int = 100

    async def resolve(self, prompt: str) -> Mapping[str, Any] | None:
        if not needs_operational_evidence(prompt):
            return None
        terms = _topic_terms(prompt)
        try:
            page = await self.read_model.list_incidents(
                status="all", limit=self.incident_limit, cursor=None
            )
            audits = await asyncio.gather(
                *(
                    self.read_model.list_audit(
                        correlation_id=incident.correlation_id,
                        limit=self.audit_limit,
                    )
                    for incident in page.items
                )
            )
        except Exception as exc:  # noqa: BLE001 - fail closed into typed unavailable state
            _LOG.warning("chat operational evidence unavailable: %s", type(exc).__name__)
            return {
                "authority": "server_read_model",
                "status": "unavailable",
                "reason": "operational evidence lookup failed",
            }

        candidates: list[tuple[int, int, IncidentSummary, Sequence[AuditItem]]] = []
        for index, (incident, audit_page) in enumerate(zip(page.items, audits, strict=True)):
            score = _score(terms, _search_text(incident, audit_page.items))
            if not terms or score > 0:
                candidates.append((score, index, incident, audit_page.items))

        if not candidates:
            return {
                "authority": "server_read_model",
                "status": "none",
                "topic_terms": list(terms),
                "searched_recent_incidents": len(page.items),
                "reason": "no recent incident matched the requested topic",
            }

        candidates.sort(key=lambda item: (-item[0], item[1]))
        recent_requested = bool(_RECENCY_INTENT.search(prompt))
        top_score = candidates[0][0]
        top = [candidate for candidate in candidates if candidate[0] == top_score]
        if len(top) > 1 and not recent_requested:
            return {
                "authority": "server_read_model",
                "status": "ambiguous",
                "topic_terms": list(terms),
                "candidates": [_incident_dict(item[2]) for item in top[:5]],
                "reason": "multiple incidents matched; ask the operator to choose one",
            }

        _, _, selected, selected_audit = top[0]
        rca = project_rca(selected_audit, correlation_id=selected.correlation_id)
        grounded = [
            hypothesis.to_dict()
            for hypothesis in rca.hypotheses
            if hypothesis.grounded and hypothesis.cause and hypothesis.citations
        ]
        return {
            "authority": "server_read_model",
            "status": "matched",
            "topic_terms": list(terms),
            "selected_incident": _incident_dict(selected),
            "grounded_hypotheses": grounded,
            "ungrounded_hypothesis_count": len(rca.hypotheses) - len(grounded),
            "response_plan": rca.response.to_dict() if rca.response else None,
            "audit_evidence": [_compact_audit(item) for item in selected_audit[:20]],
            "candidate_count": len(candidates),
        }


__all__ = ["OperationalEvidenceResolver", "needs_operational_evidence"]

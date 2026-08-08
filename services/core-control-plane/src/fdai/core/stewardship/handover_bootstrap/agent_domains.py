"""Deterministic agent-domain catalog - the grounding source for extraction.

Maps each of the 15 pantheon agents to the operational domain a document
might describe ("who owned X"). The extractor matches document text against
these keyword sets to route a responsibility to an agent **deterministically**,
before any model is consulted. The keywords mirror the domain questions in the
``agent-handover`` skill table so the two never drift in intent.

Pure data + a pure match helper; no I/O. ``core/`` MUST NOT import ``agents/``
(module boundary), so the agent names come from
:data:`fdai.core.stewardship.names.AGENT_NAMES`, pinned by the pantheon parity
test.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.stewardship.names import AGENT_NAME_SET


@dataclass(frozen=True, slots=True)
class AgentDomain:
    """One agent's operational domain as a matchable keyword set.

    ``keywords`` are lowercase; ``question`` is the human "who owned ..." prompt
    (English, from the handover skill). ``specificity`` weights how uniquely a
    keyword hit implies this agent (1.0 = highly specific, lower = generic) and
    feeds the extractor's confidence.
    """

    agent_name: str
    question: str
    keywords: tuple[str, ...]
    specificity: float = 1.0


# Order mirrors the handover skill table. Keywords are deliberately domain
# nouns/verbs an ops doc would use, not agent names (a document rarely mentions
# "Njord"; it mentions "cost" / "FinOps").
_DOMAINS: tuple[AgentDomain, ...] = (
    AgentDomain(
        "Odin",
        "cross-team prioritization / final tie-break on conflicting changes",
        (
            "prioritization",
            "arbitration",
            "tie-break",
            "tie breaker",
            "escalation lead",
            "steering",
        ),
    ),
    AgentDomain(
        "Thor",
        "executing approved changes (ran the runbooks)",
        (
            "deployment",
            "release",
            "execute change",
            "run the runbook",
            "operator",
            "rollout",
        ),
        specificity=0.8,
    ),
    AgentDomain(
        "Forseti",
        "deciding whether a change is safe / allowed (change-approval owner)",
        (
            "change approval",
            "change advisory",
            "cab",
            "gatekeeper",
            "approve change",
            "safety review",
        ),
    ),
    AgentDomain(
        "Huginn",
        "event / alert intake and triage",
        ("alert intake", "event triage", "on-call intake", "first responder", "incident intake"),
    ),
    AgentDomain(
        "Heimdall",
        "monitoring, anomaly / drift watching, on-call observation",
        ("monitoring", "observability", "anomaly", "drift", "dashboards", "on-call watch"),
    ),
    AgentDomain(
        "Vidar",
        "rollback / DR / failover ownership",
        ("rollback", "disaster recovery", "failover", "dr drill", "backup restore", "recovery"),
    ),
    AgentDomain(
        "Var",
        "approving high-risk operations (the approver on call)",
        ("approver", "sign-off", "high-risk approval", "authorize", "dual control"),
    ),
    AgentDomain(
        "Bragi",
        "explaining ops status to stakeholders",
        ("status report", "stakeholder comms", "communications", "briefing", "narrative"),
    ),
    AgentDomain(
        "Saga",
        "audit / compliance / record-keeping owner",
        ("audit", "compliance", "record keeping", "evidence", "attestation", "record-keeping"),
    ),
    AgentDomain(
        "Mimir",
        "rule / policy / standards ownership",
        ("policy", "standards", "rule owner", "governance rules", "control catalog"),
    ),
    AgentDomain(
        "Muninn",
        "runbook / knowledge-base / institutional memory owner",
        ("runbook owner", "knowledge base", "documentation owner", "wiki", "institutional memory"),
    ),
    AgentDomain(
        "Norns",
        "continuous-improvement / postmortem-to-rule owner",
        ("postmortem", "retrospective", "continuous improvement", "lessons learned", "rca owner"),
    ),
    AgentDomain(
        "Njord",
        "cost / FinOps owner",
        ("cost", "finops", "budget", "spend", "cost governance", "billing"),
    ),
    AgentDomain(
        "Freyr",
        "capacity / sizing / performance owner",
        ("capacity", "sizing", "performance", "scaling", "right-sizing", "load"),
    ),
    AgentDomain(
        "Loki",
        "chaos / resilience testing owner",
        ("chaos", "resilience testing", "fault injection", "game day", "chaos engineering"),
    ),
)

AGENT_DOMAINS: dict[str, AgentDomain] = {d.agent_name: d for d in _DOMAINS}


def _validate_catalog() -> None:
    """Fail-fast at import if the catalog drifts from the 15-agent set."""
    names = frozenset(AGENT_DOMAINS)
    if names != AGENT_NAME_SET:
        missing = sorted(AGENT_NAME_SET - names)
        extra = sorted(names - AGENT_NAME_SET)
        raise ValueError(
            "handover agent-domain catalog MUST cover exactly the 15 pantheon "
            f"agents (missing={missing}, extra={extra})"
        )


_validate_catalog()


def match_agents(text_lower: str) -> tuple[tuple[str, float, str], ...]:
    """Return ``(agent_name, specificity, matched_keyword)`` for every domain hit.

    ``text_lower`` MUST already be lowercased. A domain matches when any of its
    keywords is a substring; the longest matched keyword per agent is returned
    (a longer phrase is a stronger signal). Deterministic and order-stable.
    """
    hits: list[tuple[str, float, str]] = []
    for domain in _DOMAINS:
        best: str | None = None
        for keyword in domain.keywords:
            if keyword in text_lower and (best is None or len(keyword) > len(best)):
                best = keyword
        if best is not None:
            hits.append((domain.agent_name, domain.specificity, best))
    return tuple(hits)


__all__ = ["AGENT_DOMAINS", "AgentDomain", "match_agents"]

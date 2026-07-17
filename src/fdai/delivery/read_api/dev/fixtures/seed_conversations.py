"""Synthetic agent-to-agent conversations keyed by audit seed row."""

from __future__ import annotations

CONVERSATIONS: dict[int, tuple[dict[str, str], ...]] = {
    10: (
        {
            "from": "Muninn",
            "to": "Norns",
            "text": "Nearest resolved match is inc-2041 at 0.91 cosine, over the "
            "0.85 reuse threshold. Can you adapt its learned action?",
        },
        {
            "from": "Norns",
            "to": "Muninn",
            "text": "Received. Adapting inc-2041's remediation to the current "
            "resource and re-validating against policy before I open a PR.",
        },
    ),
    12: (
        {
            "from": "Odin",
            "to": "Njord",
            "text": "Cost proposes scaling aks-prod down. What is the monthly "
            "delta if we instead scale up two nodes?",
        },
        {
            "from": "Njord",
            "to": "Odin",
            "text": "Scaling up two nodes is about +540 USD/month - within the "
            "cost-governance soft cap, so cost does not block it.",
        },
        {
            "from": "Odin",
            "to": "Vidar",
            "text": "Does scaling down risk the resilience SLO during the current "
            "change-freeze window?",
        },
        {
            "from": "Vidar",
            "to": "Odin",
            "text": "Yes. Scaling down breaches the 99.9% availability target "
            "inside the freeze window - I advise against it.",
        },
        {
            "from": "Odin",
            "to": "Forseti",
            "text": "Resilience wins this window. Proceed with scale-up; the cost "
            "delta is noted and within budget.",
        },
    ),
    13: (
        {
            "from": "Forseti",
            "to": "Muninn",
            "text": "Any prior incident matching this throttling-plus-latency "
            "signature on aks-prod?",
        },
        {
            "from": "Muninn",
            "to": "Forseti",
            "text": "Closest is inc-1998 at 0.72 - below the reuse threshold, so "
            "no confident precedent.",
        },
        {
            "from": "Forseti",
            "to": "Mimir",
            "text": "Which catalog rule grounds a throttling root cause here?",
        },
        {
            "from": "Mimir",
            "to": "Forseti",
            "text": "No single rule matches; two candidates conflict and neither "
            "cites strongly. Grounding is weak.",
        },
        {
            "from": "Forseti",
            "to": "Odin",
            "text": "Cross-check models disagree and grounding is weak. I am "
            "escalating this to human-in-the-loop rather than auto-resolve.",
        },
    ),
}

__all__ = ["CONVERSATIONS"]

"""Shared Freyr runtime constants."""

from __future__ import annotations

from datetime import timedelta

_MAX_TRACKED_RESOURCES = 512
_MAX_COST_EVIDENCE = 512
_COST_EVIDENCE_MAX_AGE = timedelta(hours=1)
_RESOURCE_PREFIX = "pantheon/freyr/capacity-resources/"
_ACCEPTED_PREFIX = "pantheon/freyr/accepted-samples/"
_COST_PREFIX = "pantheon/freyr/cost-evidence/"
_MAX_RETAINED_IDENTIFIER_CHARS = 128

__all__ = [
    "_ACCEPTED_PREFIX",
    "_COST_EVIDENCE_MAX_AGE",
    "_COST_PREFIX",
    "_MAX_COST_EVIDENCE",
    "_MAX_RETAINED_IDENTIFIER_CHARS",
    "_MAX_TRACKED_RESOURCES",
    "_RESOURCE_PREFIX",
]

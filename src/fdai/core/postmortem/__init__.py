"""Postmortem / PIR draft generator.

Design contract: ``docs/roadmap/sre-agent-scope.md § 3.6``.

Consumes an :class:`~fdai.shared.contracts.models.Incident` and a
timeline of audit rows to produce a structured markdown draft. The
generator is **LLM-optional**: if no :class:`PostmortemLlm` is bound,
the draft is a template rendering of the audit trail alone - no
fabrication, no missing sections marked "TODO"; each section is either
filled from the audit data or carries an explicit "no evidence
recorded" line.

Output is intentionally markdown so the PR-native delivery path
([action-ontology.md](../../../../docs/roadmap/action-ontology.md)
``pr_native`` execution) can commit the draft to
``rule-catalog/postmortems/<incident-id>.md`` for reviewer approval -
the same gate remediation PRs already flow through.
"""

from __future__ import annotations

from .draft import (
    AuditRow,
    PostmortemDraft,
    PostmortemGenerator,
    PostmortemLlm,
)

__all__ = [
    "AuditRow",
    "PostmortemDraft",
    "PostmortemGenerator",
    "PostmortemLlm",
]

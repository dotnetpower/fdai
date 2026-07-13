"""Postmortem draft synthesizer.

Deterministic template renderer + optional LLM narrative expander. The
template path is exhaustive on its own so the generator NEVER emits a
"TODO" placeholder - if a section has no evidence, it says so
explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.shared.contracts.models import Incident, IncidentState

#: Sentinel embedded in every deterministic "absence of evidence" section.
#: The LLM expander skips any section containing it so the no-fabrication
#: invariant (a section with no evidence stays an honest "no evidence"
#: statement) cannot be rewritten into invented narrative. Every
#: ``_render_*`` empty branch MUST include this substring.
_NO_EVIDENCE_SENTINEL = "no evidence recorded"


@dataclass(frozen=True, slots=True)
class AuditRow:
    """One audit-log entry - Postgres row shape trimmed to what the draft needs.

    The generator does NOT couple to the storage backend; a caller
    fetches rows via ``StateStore`` (or the projected in-memory audit)
    and hands the shortlist here.
    """

    kind: str
    at: datetime
    actor_oid: str | None
    body: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PostmortemDraft:
    """Structured markdown draft.

    ``content`` is the full markdown body ready to write to
    ``rule-catalog/postmortems/<incident-id>.md``. ``sections`` is the
    per-section payload the reviewer can edit without re-rendering.
    """

    incident_id: str
    content: str
    sections: Mapping[str, str]


class PostmortemLlm(Protocol):
    """Optional LLM narrative expander.

    When bound, the generator hands it the per-section template text
    plus the audit timeline and asks for a natural-language rewrite.
    The Protocol is intentionally narrow (one method) so a fork can
    plug any model without the core learning about vendor SDKs.
    Fail-closed: any exception is caught upstream and the generator
    falls back to the template output.
    """

    async def expand(
        self,
        *,
        section: str,
        template: str,
        audit_rows: Sequence[AuditRow],
    ) -> str:
        """Return the narrative expansion of ``template`` for ``section``."""
        ...


class PostmortemGenerator:
    """Deterministic template renderer + optional LLM expander."""

    def __init__(self, *, llm: PostmortemLlm | None = None) -> None:
        self._llm = llm

    async def generate(
        self,
        *,
        incident: Incident,
        audit_rows: Sequence[AuditRow],
    ) -> PostmortemDraft:
        """Return a full markdown draft for ``incident``.

        Sections rendered in order:

        - Summary
        - Timeline
        - Impact
        - Root cause
        - Contributing factors
        - Actions taken
        - Follow-ups
        """
        sections: dict[str, str] = {}
        sections["summary"] = _render_summary(incident)
        sections["timeline"] = _render_timeline(audit_rows)
        sections["impact"] = _render_impact(incident, audit_rows)
        sections["root_cause"] = _render_root_cause(audit_rows)
        sections["contributing_factors"] = _render_contributing(audit_rows)
        sections["actions_taken"] = _render_actions_taken(audit_rows)
        sections["follow_ups"] = _render_follow_ups(incident)

        if self._llm is not None:
            for name, template in list(sections.items()):
                # No-fabrication invariant (module docstring): a section with
                # no evidence MUST stay an honest "no evidence" statement, never
                # a narrative the model could invent. Skip LLM expansion for any
                # absence-of-evidence section so the model never gets the chance
                # to rewrite "no root cause recorded" into a fabricated cause.
                if _NO_EVIDENCE_SENTINEL in template:
                    continue
                try:
                    sections[name] = await self._llm.expand(
                        section=name, template=template, audit_rows=audit_rows
                    )
                except Exception:  # noqa: BLE001, S112 - fail-closed to template renderer
                    # Any LLM error preserves the deterministic template
                    # so the draft is still shippable without narrative.
                    continue

        content = _assemble(incident, sections)
        return PostmortemDraft(
            incident_id=str(incident.incident_id),
            content=content,
            sections=sections,
        )


# ---------------------------------------------------------------------------
# Section renderers - deterministic, no LLM
# ---------------------------------------------------------------------------


def _render_summary(incident: Incident) -> str:
    opened = _iso(incident.opened_at)
    resolved = _iso(incident.resolved_at) if incident.resolved_at else "not resolved yet"
    return (
        f"Incident `{incident.incident_id}` opened at {opened} at severity "
        f"`{incident.severity.value}`; current state `{incident.state.value}`; "
        f"resolved at {resolved}. Correlation keys: "
        f"{', '.join(incident.correlation_keys) or 'none recorded'}."
    )


def _render_timeline(rows: Sequence[AuditRow]) -> str:
    if not rows:
        return "no audit rows linked to this incident (no evidence recorded)."
    lines = []
    for row in rows:
        who = row.actor_oid or "system"
        lines.append(f"- **{_iso(row.at)}** `{row.kind}` (actor: `{who}`)")
    return "\n".join(lines)


def _render_impact(incident: Incident, rows: Sequence[AuditRow]) -> str:
    mitigated = _iso(incident.mitigated_at) if incident.mitigated_at else None
    resolved = _iso(incident.resolved_at) if incident.resolved_at else None
    duration_lines = []
    if mitigated:
        duration_lines.append(f"mitigated at {mitigated}")
    if resolved:
        duration_lines.append(f"resolved at {resolved}")
    if not duration_lines:
        duration_lines.append(
            "no mitigation / resolution timestamps recorded (no evidence recorded)."
        )
    breach_rows = [r for r in rows if r.kind == "slo.error_budget_burn"]
    if breach_rows:
        duration_lines.append(f"{len(breach_rows)} SLO burn-rate breach(es) recorded.")
    return " ".join(duration_lines)


def _render_root_cause(rows: Sequence[AuditRow]) -> str:
    causes = [str(r.body.get("root_cause")) for r in rows if r.body.get("root_cause")]
    if not causes:
        return "no root cause recorded on the audit trail (no evidence recorded)."
    return "; ".join(dict.fromkeys(causes))


def _render_contributing(rows: Sequence[AuditRow]) -> str:
    factors = [
        str(r.body.get("contributing_factor")) for r in rows if r.body.get("contributing_factor")
    ]
    if not factors:
        return "no contributing factors recorded (no evidence recorded)."
    return "; ".join(dict.fromkeys(factors))


def _render_actions_taken(rows: Sequence[AuditRow]) -> str:
    action_rows = [r for r in rows if r.kind.startswith("action.")]
    if not action_rows:
        return "no autonomous or operator actions linked to this incident (no evidence recorded)."
    lines = []
    for row in action_rows:
        name = row.body.get("action_type", row.kind)
        mode = row.body.get("mode", "unknown")
        lines.append(f"- `{name}` in `{mode}` mode at {_iso(row.at)}")
    return "\n".join(lines)


def _render_follow_ups(incident: Incident) -> str:
    if incident.state is IncidentState.CLOSED:
        ref = incident.postmortem_ref or "no follow-up items recorded (no evidence recorded)."
        return ref
    return "incident not yet closed - follow-up items pending."


def _assemble(incident: Incident, sections: Mapping[str, str]) -> str:
    return (
        f"# Postmortem: {incident.incident_id}\n\n"
        f"## Summary\n\n{sections['summary']}\n\n"
        f"## Timeline\n\n{sections['timeline']}\n\n"
        f"## Impact\n\n{sections['impact']}\n\n"
        f"## Root cause\n\n{sections['root_cause']}\n\n"
        f"## Contributing factors\n\n{sections['contributing_factors']}\n\n"
        f"## Actions taken\n\n{sections['actions_taken']}\n\n"
        f"## Follow-ups\n\n{sections['follow_ups']}\n"
    )


def _iso(dt: datetime) -> str:
    return dt.isoformat()


__all__ = ["AuditRow", "PostmortemDraft", "PostmortemGenerator", "PostmortemLlm"]

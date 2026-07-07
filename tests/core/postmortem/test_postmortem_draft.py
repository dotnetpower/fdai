"""Postmortem draft generator - template + optional LLM expander."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fdai.core.postmortem import (
    AuditRow,
    PostmortemDraft,
    PostmortemGenerator,
)
from fdai.shared.contracts.models import Incident, IncidentSeverity, IncidentState

T0 = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)


def _incident(**overrides) -> Incident:  # noqa: ANN003
    base = dict(
        schema_version="1.0.0",
        incident_id=UUID("00000000-0000-0000-0000-000000000001"),
        state=IncidentState.RESOLVED,
        severity=IncidentSeverity.SEV2,
        opened_at=T0,
        mitigated_at=T0 + timedelta(minutes=30),
        resolved_at=T0 + timedelta(hours=1),
        correlation_keys=("resource:vm-a", "deployment:api-v3"),
        member_event_ids=(UUID("00000000-0000-0000-0000-00000000000a"),),
    )
    base.update(overrides)
    return Incident(**base)


# ---------------------------------------------------------------------------
# Template-only path (no LLM)
# ---------------------------------------------------------------------------


async def test_template_draft_covers_every_section_without_todo_placeholders() -> None:
    incident = _incident()
    rows = [
        AuditRow(
            kind="action.remediate",
            at=T0 + timedelta(minutes=20),
            actor_oid="oid-oncall",
            body={"action_type": "remediate.enable-backup-protection", "mode": "enforce"},
        ),
    ]
    generator = PostmortemGenerator()
    draft = await generator.generate(incident=incident, audit_rows=rows)
    assert isinstance(draft, PostmortemDraft)
    # No "TODO" placeholders anywhere - the docstring contract.
    assert "TODO" not in draft.content
    # All seven sections rendered.
    for header in (
        "## Summary",
        "## Timeline",
        "## Impact",
        "## Root cause",
        "## Contributing factors",
        "## Actions taken",
        "## Follow-ups",
    ):
        assert header in draft.content
    # Action row surfaces in the actions-taken section.
    assert "remediate.enable-backup-protection" in draft.content


async def test_empty_audit_produces_explicit_no_evidence_lines() -> None:
    incident = _incident(state=IncidentState.OPEN, mitigated_at=None, resolved_at=None)
    generator = PostmortemGenerator()
    draft = await generator.generate(incident=incident, audit_rows=[])
    # Every section that has no evidence carries the explicit line,
    # not a placeholder.
    assert draft.sections["timeline"].startswith("no audit rows")
    assert "no evidence recorded" in draft.sections["impact"]
    assert draft.sections["root_cause"].startswith("no root cause")
    assert draft.sections["contributing_factors"].startswith("no contributing")


async def test_root_cause_and_contributing_factors_are_deduplicated() -> None:
    incident = _incident()
    rows = [
        AuditRow(
            kind="rca.finding",
            at=T0,
            actor_oid="oid-oncall",
            body={"root_cause": "expired cert", "contributing_factor": "no auto-renew"},
        ),
        AuditRow(
            kind="rca.finding",
            at=T0,
            actor_oid="oid-oncall",
            body={"root_cause": "expired cert"},  # duplicate
        ),
    ]
    generator = PostmortemGenerator()
    draft = await generator.generate(incident=incident, audit_rows=rows)
    assert draft.sections["root_cause"] == "expired cert"
    assert draft.sections["contributing_factors"] == "no auto-renew"


# ---------------------------------------------------------------------------
# LLM expander path - success + fail-closed on error
# ---------------------------------------------------------------------------


class _EchoingLlm:
    """Prefixes each section with 'LLM:' so we can assert the expander ran."""

    async def expand(self, *, section, template, audit_rows):  # noqa: ANN001, ANN201, ARG002
        return f"LLM:{section}:{template}"


class _RaisingLlm:
    async def expand(self, **_kwargs):  # noqa: ANN003, ANN201
        raise RuntimeError("model outage")


async def test_llm_narrative_expands_every_section_when_bound() -> None:
    incident = _incident()
    generator = PostmortemGenerator(llm=_EchoingLlm())
    draft = await generator.generate(incident=incident, audit_rows=[])
    for name, body in draft.sections.items():
        assert body.startswith(f"LLM:{name}:")


async def test_llm_failure_falls_back_to_template(caplog) -> None:  # noqa: ANN001
    incident = _incident()
    generator = PostmortemGenerator(llm=_RaisingLlm())
    draft = await generator.generate(incident=incident, audit_rows=[])
    # No exception surfaces; the deterministic template is preserved.
    assert not any(body.startswith("LLM:") for body in draft.sections.values())
    # And the draft is still valid markdown with every section.
    for header in ("## Summary", "## Timeline", "## Follow-ups"):
        assert header in draft.content


# ---------------------------------------------------------------------------
# Determinism - same input, same output
# ---------------------------------------------------------------------------


async def test_deterministic_output_for_identical_inputs() -> None:
    incident = _incident()
    rows = [
        AuditRow(kind="action.remediate", at=T0, actor_oid="oid-a", body={"action_type": "x"}),
    ]
    generator = PostmortemGenerator()
    a = (await generator.generate(incident=incident, audit_rows=rows)).content
    b = (await generator.generate(incident=incident, audit_rows=rows)).content
    assert a == b


# Ref to keep the pytest import used (fixtures already covered elsewhere).
_ = pytest

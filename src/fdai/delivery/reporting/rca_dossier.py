"""Dedicated long-form renderer for the Incident RCA Dossier."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

from fdai.core.reporting.models import RenderedReport, RenderedWidget
from fdai.delivery.reporting.rca_sections import (
    first_row as _first_row,
)
from fdai.delivery.reporting.rca_sections import (
    format_duration as _duration,
)
from fdai.delivery.reporting.rca_sections import (
    format_ratio as _ratio,
)
from fdai.delivery.reporting.rca_sections import (
    render_section_body as _section_body,
)
from fdai.delivery.reporting.rca_sections import (
    rows as _rows,
)
from fdai.delivery.reporting.rca_sections import (
    scalar as _scalar,
)
from fdai.delivery.reporting.rca_sections import (
    text as _text,
)
from fdai.delivery.reporting.rca_sections import (
    value as _value,
)

_SECTION_ORDER = (
    ("incident-profile", "Incident Profile and Impact"),
    ("event-chronology", "Incident Chronology"),
    ("root-cause-hypotheses", "Root-Cause Analysis"),
    ("causal-chain", "Causal Chain"),
    ("contributing-factors", "Contributing Factors"),
    ("alternative-hypotheses", "Alternative Hypotheses"),
    ("grounded-citations", "Evidence Register"),
    ("response-plan", "Response and Remediation"),
    ("recovery-validation", "Recovery Validation"),
    ("control-gaps", "Control-Gap Analysis"),
    ("recommendations", "Corrective and Preventive Actions"),
    ("limitations", "Limitations and Unknowns"),
    ("audit-chronology", "Audit Appendix"),
)


def render_rca_dossier(report: RenderedReport, *, source_sha: str) -> str:
    """Render one correlation-scoped report as an operational RCA document."""
    widgets = {widget.id: widget for widget in report.widgets}
    profile = _first_row(widgets.get("incident-profile"))
    hypothesis = _first_row(widgets.get("root-cause-hypotheses"))
    impact = _rows(widgets.get("impact-assessment"))
    response = _rows(widgets.get("response-plan"))
    recovery = _rows(widgets.get("recovery-validation"))
    correlation_id = report.variables.get("correlation_id") or _text(profile.get("correlation_id"))
    incident_title = _text(profile.get("title")) or "Incident root-cause analysis"
    severity = _text(profile.get("severity")) or "unavailable"
    status = _text(profile.get("status")) or "unavailable"
    duration = _duration(profile.get("duration_seconds"))
    confidence = _ratio(hypothesis.get("confidence"))
    record_count = _scalar(widgets.get("evidence-record-count"))
    evidence_count = len(_rows(widgets.get("grounded-citations")))
    sections = "".join(
        _render_section(index, section_id, title, widgets)
        for index, (section_id, title) in enumerate(_SECTION_ORDER, 1)
    )
    toc = "".join(
        f'<li><a href="#dossier-{escape(section_id)}">{escape(title)}</a></li>'
        for section_id, title in _SECTION_ORDER
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{escape(report.name)}</title></head>
<body class="rca-dossier">
  {_cover(report, source_sha, correlation_id, incident_title, severity, status)}
  <section class="dossier-overview">
    <p class="chapter-kicker">Executive brief</p>
    <h1>At a Glance</h1>
    <div class="dossier-kpis">
      {_metric("Severity", severity, "severity")}
      {_metric("Incident status", status, "status")}
      {_metric("Observed duration", duration, "time")}
      {_metric("RCA confidence", confidence, "confidence")}
      {_metric("Evidence citations", evidence_count, "evidence")}
      {_metric("Audit records", record_count, "records")}
    </div>
    <div class="executive-layout">
      <article class="executive-summary">
        <h2>Executive Summary</h2>
        {_executive_summary(incident_title, impact, hypothesis, response, recovery)}
      </article>
      <aside class="authority-note">
        <strong>Authority boundary</strong>
        <p>RCA explains the most likely cause. The risk gate and verifier remain authoritative
        over execution. Missing evidence is never inferred by this report.</p>
      </aside>
    </div>
    {_completeness_panel(widgets)}
  </section>

  <nav class="toc dossier-toc">
    <p class="chapter-kicker">Document map</p>
    <h1>Table of Contents</h1>
    <ol>{toc}</ol>
  </nav>

  <main>{sections}</main>
</body>
</html>"""


def _cover(
    report: RenderedReport,
    source_sha: str,
    correlation_id: str,
    incident_title: str,
    severity: str,
    status: str,
) -> str:
    return f"""<section class="cover dossier-cover">
  <div class="cover-band">
    <div class="cover-mark"><span>FDAI</span><small>Operational Intelligence</small></div>
    <p class="kicker">Post-Incident Root-Cause Analysis</p>
    <h1>{escape(incident_title)}</h1>
    <p class="subtitle">Evidence dossier · {escape(severity)} severity · {escape(status)}</p>
  </div>
  <div class="cover-document-number">RCA / {escape(correlation_id or "not-scoped")}</div>
  <dl class="cover-meta">
    <dt>Report id</dt><dd><code>{escape(report.id)} v{escape(report.version)}</code></dd>
    <dt>Correlation id</dt><dd><code>{escape(correlation_id or "not scoped")}</code></dd>
    <dt>Generated</dt><dd>{escape(report.generated_at.isoformat())}</dd>
    <dt>Evidence window</dt><dd>{escape(report.time_range[0].isoformat())}<br>
      to {escape(report.time_range[1].isoformat())}</dd>
    <dt>Source SHA-256</dt><dd><code>{source_sha}</code></dd>
  </dl>
  <p class="classification">INTERNAL OPERATIONAL RECORD</p>
  <p class="cover-note">Deterministic rendering of server-owned evidence. This document can be
    replayed from the identified report envelope and does not create new incident facts.</p>
</section>"""


def _executive_summary(
    incident_title: str,
    impact: Sequence[Mapping[str, Any]],
    hypothesis: Mapping[str, Any],
    response: Sequence[Mapping[str, Any]],
    recovery: Sequence[Mapping[str, Any]],
) -> str:
    cause = _text(hypothesis.get("cause"))
    impact_text = _impact_sentence(impact)
    response_text = _response_sentence(response)
    recovery_text = _recovery_sentence(recovery)
    cause_text = cause or "No grounded cause is available."
    paragraphs = [
        f"<p><strong>What happened.</strong> {escape(incident_title)}.</p>",
        f"<p><strong>Impact.</strong> {escape(impact_text)}</p>",
        f"<p><strong>Most likely cause.</strong> {escape(cause_text)}</p>",
        f"<p><strong>Response.</strong> {escape(response_text)}</p>",
        f"<p><strong>Recovery.</strong> {escape(recovery_text)}</p>",
    ]
    return "".join(paragraphs)


def _render_section(
    index: int,
    section_id: str,
    title: str,
    widgets: Mapping[str, RenderedWidget],
) -> str:
    widget = widgets.get(section_id)
    impact = widgets.get("impact-assessment") if section_id == "incident-profile" else None
    body = _section_body(section_id, widget, impact)
    return f"""<section class="dossier-section" id="dossier-{escape(section_id)}">
    <header class="dossier-section-head">
        <p class="chapter-kicker">Chapter {index:02d}</p>
        <h1>{escape(title)}</h1>
    </header>
  {body}
</section>"""


def _completeness_panel(widgets: Mapping[str, RenderedWidget]) -> str:
    tracked = [section_id for section_id, _ in _SECTION_ORDER if section_id != "audit-chronology"]
    available = sum(1 for section_id in tracked if _rows(widgets.get(section_id)))
    pct = round(available / len(tracked) * 100)
    chips = "".join(
        f'<span class="{"available" if _rows(widgets.get(section_id)) else "missing"}">'
        f"{escape(title)}</span>"
        for section_id, title in _SECTION_ORDER
        if section_id != "audit-chronology"
    )
    return f"""<div class="completeness-panel"><header><h2>Evidence Completeness</h2>
<strong>{pct}%</strong></header><div class="completeness-bar">
<span style="width:{pct}%"></span></div>
<div class="completeness-chips">{chips}</div></div>"""


def _metric(label: str, value: Any, kind: str) -> str:
    return (
        f'<div class="dossier-kpi {escape(kind)}"><span>{escape(label)}</span>'
        f"<strong>{_value(value)}</strong></div>"
    )


def _impact_sentence(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "Measured impact was not recorded."
    first = rows[0]
    impact_detail = _text(first.get("impact")) or "impact details unavailable"
    return (
        f"{_text(first.get('metric')) or 'The primary metric'} reached "
        f"{_plain_text(first.get('observed')) or 'an unavailable value'} "
        f"{_text(first.get('unit')) or ''}; {impact_detail}."
    )


def _response_sentence(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "No response action was recorded."
    first = rows[0]
    return (
        f"{_text(first.get('action_kind')) or 'An action'} was recorded with "
        f"decision {_text(first.get('decision')) or 'unavailable'} and outcome "
        f"{_text(first.get('outcome')) or 'unavailable'}."
    )


def _recovery_sentence(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "Recovery validation evidence was not recorded."
    passed = sum(1 for row in rows if _text(row.get("status")) in {"pass", "passed", "healthy"})
    return f"{passed} of {len(rows)} recorded recovery checks passed."


def _plain_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


__all__ = ["render_rca_dossier"]

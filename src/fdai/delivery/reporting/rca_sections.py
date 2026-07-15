"""Chapter renderers and safe value helpers for the RCA dossier."""

from __future__ import annotations

import json
import textwrap
from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

from fdai.core.reporting.models import RenderedWidget


def render_section_body(
    section_id: str,
    widget: RenderedWidget | None,
    impact: RenderedWidget | None,
) -> str:
    if section_id == "incident-profile":
        return _profile_section(first_row(widget), rows(impact))
    data = rows(widget)
    handlers = {
        "event-chronology": _timeline,
        "root-cause-hypotheses": _hypotheses,
        "causal-chain": _causal_chain,
        "contributing-factors": _factor_cards,
        "alternative-hypotheses": _alternatives,
        "grounded-citations": _evidence_register,
        "response-plan": _response_steps,
        "recovery-validation": _recovery_table,
        "control-gaps": _control_gaps,
        "recommendations": _recommendations,
        "limitations": _limitations,
    }
    handler = handlers.get(section_id)
    return handler(data) if handler else _table(widget)


def _profile_section(profile: Mapping[str, Any], impact: Sequence[Mapping[str, Any]]) -> str:
    if not profile:
        return _unavailable("Incident profile was not recorded for this correlation id.")
    facts = (
        ("Incident id", profile.get("incident_id")),
        ("Ticket id", profile.get("ticket_id")),
        ("Owning vertical", profile.get("vertical")),
        ("Opened", profile.get("opened_at")),
        ("Last updated", profile.get("last_updated_at")),
        ("Observed duration", format_duration(profile.get("duration_seconds"))),
        ("Actors", profile.get("actors")),
        ("Modes", profile.get("modes")),
    )
    fact_html = "".join(_fact(label, value) for label, value in facts)
    return (
        f'<div class="fact-grid">{fact_html}</div><h2>Measured Impact</h2>{_impact_cards(impact)}'
    )


def _timeline(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("No incident milestones were available.")
    body = []
    for row in data:
        summary = text(row.get("summary")) or text(row.get("action_kind")) or "Recorded event"
        date, time = _timestamp_parts(row.get("recorded_at"))
        body.append(
            f"""<tr><td class="chronology-time"><span>{escape(date)}</span>
<strong>{escape(time)}</strong></td>
<td><span class="chronology-phase">{value(row.get("phase"))}</span></td>
<td><strong>{escape(summary)}</strong><small>{value(row.get("action_kind"))}</small></td>
<td>{value(row.get("actor"))}<small>{value(row.get("decision"))} ·
{value(row.get("outcome"))}</small></td></tr>"""
        )
    return f"""<div class="chronology-table-wrap"><table class="chronology-table">
<thead><tr><th>Time</th><th>Phase</th><th>Event</th><th>Actor · result</th></tr></thead>
<tbody>{"".join(body)}</tbody></table></div>"""


def _hypotheses(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("No RCA hypothesis has been recorded.")
    cards = []
    for row in data:
        state = "grounded" if text(row.get("outcome")) == "grounded" else "abstained"
        cards.append(
            f"""<article class="hypothesis-card {state}">
  <div class="hypothesis-meta"><span>{value(row.get("tier"))}</span>
  <span>{value(row.get("outcome"))}</span><span>{format_ratio(row.get("confidence"))}</span></div>
  <h2>{value(row.get("cause"))}</h2><p>{value(row.get("reason"))}</p>
  <footer>Implied remediation: {value(row.get("remediation_ref"))}</footer></article>"""
        )
    return "".join(cards)


def _causal_chain(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("No structured causal chain was recorded.")
    lane_height = 126
    height = 18 + lane_height * len(data)
    lanes = "".join(
        _causal_svg_lane(row, index * lane_height + 12) for index, row in enumerate(data)
    )
    label = escape(f"Causal chain with {len(data)} hop(s)")
    return f"""<svg class="causal-chain-diagram" viewBox="0 0 720 {height}"
role="img" aria-label="{label}" xmlns="http://www.w3.org/2000/svg">
{lanes}</svg>"""


def _causal_svg_lane(row: Mapping[str, Any], y: int) -> str:
    middle = y + 47
    relationship = _plain(row.get("relationship")) or "relationship unavailable"
    detail = f"{_plain(row.get('lead_seconds')) or '?'}s · {format_ratio(row.get('confidence'))}"
    return f"""<g class="causal-lane">
<rect x="12" y="{y}" width="260" height="94" rx="8" fill="#F4F2F0" stroke="#E3E1DE" />
<rect x="448" y="{y}" width="260" height="94" rx="8" fill="#FFFFFF" stroke="#E3E1DE" />
<text x="28" y="{y + 20}" fill="#6B7178" font-family="Noto Sans KR, DejaVu Sans, sans-serif"
font-size="9" font-weight="700" letter-spacing="0.7">CAUSE</text>
{_svg_text(row.get("cause_resource_ref"), 28, y + 43, "causal-title")}
{_svg_text(row.get("cause_event_id"), 28, y + 68, "causal-code")}
<line x1="282" y1="{middle}" x2="429" y2="{middle}" stroke="#44688E" stroke-width="2" />
<polygon points="429,{middle - 6} 441,{middle} 429,{middle + 6}" fill="#44688E" />
<text x="361" y="{middle - 8}" text-anchor="middle" fill="#2C333A"
font-family="Noto Sans KR, DejaVu Sans, sans-serif" font-size="10"
font-weight="700">{escape(relationship)}</text>
<text x="361" y="{middle + 14}" text-anchor="middle" fill="#6B7178"
font-family="Noto Sans KR, DejaVu Sans, sans-serif" font-size="9">{escape(detail)}</text>
<text x="464" y="{y + 20}" fill="#6B7178" font-family="Noto Sans KR, DejaVu Sans, sans-serif"
font-size="9" font-weight="700" letter-spacing="0.7">EFFECT</text>
{_svg_text(row.get("effect_resource_ref"), 464, y + 43, "causal-title")}
{_svg_text(row.get("effect_event_id"), 464, y + 68, "causal-code")}
</g>"""


def _svg_text(raw: Any, x: int, y: int, class_name: str) -> str:
    content = _plain(raw) or "unavailable"
    lines = textwrap.wrap(content, width=34, break_long_words=True, break_on_hyphens=False)[:2]
    tspans = "".join(
        f'<tspan x="{x}" dy="{0 if index == 0 else 14}">{escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )
    if class_name == "causal-title":
        attrs = (
            'fill="#2C333A" font-family="Noto Sans KR, DejaVu Sans, sans-serif" '
            'font-size="13" font-weight="700"'
        )
    else:
        attrs = 'fill="#6B7178" font-family="DejaVu Sans Mono, monospace" font-size="10"'
    return f'<text x="{x}" y="{y}" {attrs}>{tspans}</text>'


def _factor_cards(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("No contributing factors were recorded.")
    cards = "".join(
        f"""<article><span>{value(row.get("category"))}</span><h2>{value(row.get("factor"))}</h2>
<p>{value(row.get("effect"))}</p><footer>{format_ratio(row.get("confidence"))} ·
{value(row.get("evidence_ref"))}</footer></article>"""
        for row in data
    )
    return f'<div class="factor-grid">{cards}</div>'


def _alternatives(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("Alternative hypotheses were not recorded.")
    return "".join(
        f"""<article class="alternative"><header><h2>{value(row.get("hypothesis"))}</h2>
<span>{value(row.get("status"))}</span></header><div class="two-column-evidence">
<div><strong>Supporting evidence</strong><p>{value(row.get("support"))}</p></div>
<div><strong>Contradiction or exclusion</strong>
<p>{value(row.get("contradiction"))}</p></div></div>
<footer>{value(row.get("reason"))}</footer></article>"""
        for row in data
    )


def _evidence_register(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("No grounded evidence references were recorded.")
    return _rows_table(
        data,
        ("tier", "kind", "ref", "summary", "source_at", "freshness", "recorded_at"),
    )


def _response_steps(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("No response or remediation actions were recorded.")
    cards = []
    for index, row in enumerate(data, 1):
        cards.append(
            f"""<article class="response-step"><span class="step-number">{index:02d}</span><div>
<h2>{value(row.get("action_kind"))}</h2>
<p>{value(row.get("decision"))} · {value(row.get("outcome"))} · {value(row.get("mode"))}</p>
<footer>{value(row.get("actor"))} · {value(row.get("recorded_at"))} ·
rollback {value(row.get("rollback_reference"))}</footer></div></article>"""
        )
    return "".join(cards)


def _recovery_table(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("Recovery was not validated with recorded before/after evidence.")
    return _rows_table(data, ("metric", "before", "after", "target", "status", "evidence_ref"))


def _control_gaps(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("No control-gap assessment was recorded.")
    return "".join(
        f"""<article class="control-gap"><h2>{value(row.get("control"))}</h2>
<div class="gap-comparison"><div><span>Expected</span><p>{value(row.get("expected"))}</p></div>
<div><span>Observed</span><p>{value(row.get("observed"))}</p></div></div>
<footer>{value(row.get("gap"))} · {value(row.get("evidence_ref"))}</footer></article>"""
        for row in data
    )


def _recommendations(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("No corrective or preventive actions were recorded.")
    return "".join(
        f"""<article class="recommendation">
<span class="priority">{value(row.get("priority"))}</span>
<div><h2>{value(row.get("action"))}</h2><p>Owner: {value(row.get("owner_role"))} ·
Due: {value(row.get("due"))} · Status: {value(row.get("status"))}</p>
<footer>Verification: {value(row.get("verification"))}</footer></div></article>"""
        for row in data
    )


def _limitations(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("No explicit analysis limitations were recorded.")
    return "".join(
        f"""<article class="limitation"><h2>{value(row.get("limitation"))}</h2>
<p><strong>Effect on analysis:</strong> {value(row.get("effect"))}</p>
<footer>Next evidence: {value(row.get("next_evidence"))} ·
{value(row.get("status"))}</footer></article>"""
        for row in data
    )


def _impact_cards(data: Sequence[Mapping[str, Any]]) -> str:
    if not data:
        return _unavailable("No measured service or user impact was recorded.")
    cards = "".join(
        f"""<article><span>{value(row.get("metric"))}</span><strong>{value(row.get("observed"))}
{value(row.get("unit"))}</strong><p>Baseline {value(row.get("baseline"))} · threshold
{value(row.get("threshold"))}</p><footer>{value(row.get("impact"))}</footer></article>"""
        for row in data
    )
    return f'<div class="impact-grid">{cards}</div>'


def _table(widget: RenderedWidget | None) -> str:
    data = rows(widget)
    columns = _columns(widget)
    if not data:
        return _unavailable("No evidence rows were available for this section.")
    return _rows_table(data, columns)


def _rows_table(data: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    head = "".join(f"<th>{escape(column.replace('_', ' ').title())}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{value(row.get(column))}</td>" for column in columns) + "</tr>"
        for row in data
    )
    return (
        f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def _fact(label: str, raw: Any) -> str:
    return f'<div class="fact"><span>{escape(label)}</span><strong>{value(raw)}</strong></div>'


def _unavailable(message: str) -> str:
    return (
        '<div class="section-unavailable"><strong>Evidence unavailable</strong>'
        f"<p>{escape(message)}</p></div>"
    )


def rows(widget: RenderedWidget | None) -> tuple[Mapping[str, Any], ...]:
    if widget is None:
        return ()
    raw = widget.data.get("rows") or widget.data.get("items")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _columns(widget: RenderedWidget | None) -> tuple[str, ...]:
    if widget is None:
        return ()
    raw = widget.data.get("columns")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    return tuple(str(item) for item in raw)


def first_row(widget: RenderedWidget | None) -> Mapping[str, Any]:
    data = rows(widget)
    return data[0] if data else {}


def scalar(widget: RenderedWidget | None) -> Any:
    return widget.data.get("value", "unavailable") if widget else "unavailable"


def format_duration(raw: Any) -> str:
    try:
        seconds = max(0, int(float(raw)))
    except (TypeError, ValueError):
        return "unavailable"
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def format_ratio(raw: Any) -> str:
    try:
        return f"{float(raw):.2f}"
    except (TypeError, ValueError):
        return "unavailable"


def _timestamp_parts(raw: Any) -> tuple[str, str]:
    timestamp = _plain(raw)
    if "T" in timestamp:
        date, time = timestamp.split("T", 1)
        return date, time
    return timestamp or "unavailable", ""


def _plain(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def text(raw: Any) -> str:
    return raw.strip() if isinstance(raw, str) and raw.strip() else ""


def value(raw: Any) -> str:
    if raw is None or raw == "":
        return '<span class="muted">unavailable</span>'
    if isinstance(raw, (Mapping, list, tuple, set)):
        return f"<code>{escape(json.dumps(raw, sort_keys=True, default=str))}</code>"
    return escape(str(raw))


__all__ = [
    "first_row",
    "format_duration",
    "format_ratio",
    "render_section_body",
    "rows",
    "scalar",
    "text",
    "value",
]

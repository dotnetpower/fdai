"""Stakeholder briefing composer.

An organization keeps a human who writes the periodic operations summary
for leadership: "here is what happened this week, what we did about it,
and where the risk is." This module synthesizes that briefing
deterministically from aggregated operational counts - no per-event
noise, no fabrication. When the window carried no significant activity
it says so explicitly rather than inventing narrative.

The composer is **pure and deterministic**: same input, same briefing.
It holds no vendor knowledge and never dispatches; the caller hands the
resulting :class:`StakeholderBriefing` (a structured markdown body plus
per-section payload) to the existing notification router
([channels-and-notifications.md](../../../../docs/roadmap/interfaces/channels-and-notifications.md))
for delivery. Every figure is sourced from the audit log / KPI telemetry
the caller supplies - the composer asserts nothing it was not given.

Design contract: [channels-and-notifications.md] proactive-briefing
section and the KPI definitions in
[goals-and-metrics.md](../../../../docs/roadmap/architecture/goals-and-metrics.md).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class IncidentTally:
    """Incident counts for the window, keyed by severity label.

    ``by_severity`` maps a severity label (e.g. ``"sev1"``) to a count.
    ``opened`` and ``resolved`` are window totals. All non-negative.
    """

    by_severity: Mapping[str, int]
    opened: int
    resolved: int


@dataclass(frozen=True, slots=True)
class ActionTally:
    """Action counts for the window, split by autonomy path and outcome."""

    auto_executed: int
    hil_approved: int
    rolled_back: int
    shadow_only: int


@dataclass(frozen=True, slots=True)
class CostSnapshot:
    """Cost trend for the window, in a fork-configured currency.

    ``delta_pct`` is the run-rate change vs the prior window; positive is
    a spend increase. ``top_drivers`` is an ordered, generic list of
    driver labels (never customer resource ids).
    """

    current_run_rate: float
    delta_pct: float
    top_drivers: Sequence[str]


@dataclass(frozen=True, slots=True)
class ForecastRisk:
    """One forward-looking risk surfaced by the forecasters."""

    label: str
    horizon: str
    detail: str


@dataclass(frozen=True, slots=True)
class BriefingInput:
    """Everything the composer needs for one window. All fields optional-safe.

    A field left at its empty default simply renders as "no activity" in
    its section - the composer never fabricates a figure it was not
    handed.
    """

    window_label: str
    incidents: IncidentTally
    actions: ActionTally
    cost: CostSnapshot | None = None
    forecast_risks: Sequence[ForecastRisk] = ()
    guard_breaches: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class StakeholderBriefing:
    """Structured, deliverable briefing.

    ``content`` is the full markdown body; ``sections`` is the per-section
    payload a caller can re-template. ``has_significant_activity`` lets the
    caller suppress an empty-window briefing entirely (an organization
    does not email leadership to say nothing happened) without re-parsing
    the markdown.
    """

    window_label: str
    content: str
    sections: Mapping[str, str]
    has_significant_activity: bool
    escalations: tuple[str, ...] = field(default_factory=tuple)


class StakeholderBriefingComposer:
    """Deterministic operational-summary synthesizer for leadership."""

    def compose(self, briefing_input: BriefingInput) -> StakeholderBriefing:
        """Return a structured briefing for ``briefing_input``'s window."""
        sections: dict[str, str] = {}
        sections["incidents"] = _render_incidents(briefing_input.incidents)
        sections["actions"] = _render_actions(briefing_input.actions)
        sections["cost"] = _render_cost(briefing_input.cost)
        sections["risks"] = _render_risks(briefing_input.forecast_risks)
        sections["guardrails"] = _render_guardrails(briefing_input.guard_breaches)

        significant = _is_significant(briefing_input)
        headline = _render_headline(briefing_input, significant=significant)
        content = _assemble(briefing_input.window_label, headline, sections)

        # Guard breaches are the one thing leadership must never miss;
        # surface them as explicit escalations the caller can route at a
        # higher trust tier.
        escalations = tuple(briefing_input.guard_breaches)
        return StakeholderBriefing(
            window_label=briefing_input.window_label,
            content=content,
            sections=sections,
            has_significant_activity=significant,
            escalations=escalations,
        )


# ---------------------------------------------------------------------------
# Deterministic section renderers
# ---------------------------------------------------------------------------


def _is_significant(bi: BriefingInput) -> bool:
    """A window matters if anything actionable happened in it."""
    inc = bi.incidents
    act = bi.actions
    if inc.opened or inc.resolved or sum(inc.by_severity.values()):
        return True
    if act.auto_executed or act.hil_approved or act.rolled_back:
        return True
    if bi.forecast_risks or bi.guard_breaches:
        return True
    if bi.cost is not None and abs(bi.cost.delta_pct) >= 1.0:
        return True
    return False


def _render_headline(bi: BriefingInput, *, significant: bool) -> str:
    if not significant:
        return "No significant operational activity in this window."
    parts = [
        f"{bi.incidents.opened} incident(s) opened, {bi.incidents.resolved} resolved",
        f"{bi.actions.auto_executed} action(s) auto-executed, "
        f"{bi.actions.hil_approved} via HIL approval",
    ]
    if bi.actions.rolled_back:
        parts.append(f"{bi.actions.rolled_back} rolled back")
    if bi.guard_breaches:
        parts.append(f"{len(bi.guard_breaches)} guard-metric breach(es) - see below")
    return "; ".join(parts) + "."


def _render_incidents(tally: IncidentTally) -> str:
    total_by_sev = sum(tally.by_severity.values())
    if not (tally.opened or tally.resolved or total_by_sev):
        return "No incidents in this window."
    if tally.by_severity:
        breakdown = ", ".join(
            f"`{sev}`: {count}" for sev, count in sorted(tally.by_severity.items())
        )
    else:
        breakdown = "no per-severity breakdown recorded"
    return f"{tally.opened} opened, {tally.resolved} resolved. By severity: {breakdown}."


def _render_actions(tally: ActionTally) -> str:
    if not (tally.auto_executed or tally.hil_approved or tally.rolled_back or tally.shadow_only):
        return "No actions taken in this window."
    return (
        f"{tally.auto_executed} auto-executed, {tally.hil_approved} HIL-approved, "
        f"{tally.rolled_back} rolled back, {tally.shadow_only} shadow-only "
        "(judged, not executed)."
    )


def _render_cost(cost: CostSnapshot | None) -> str:
    if cost is None:
        return "No cost data recorded for this window."
    direction = "up" if cost.delta_pct > 0 else "down" if cost.delta_pct < 0 else "flat"
    drivers = ", ".join(cost.top_drivers) if cost.top_drivers else "no dominant drivers"
    return (
        f"Run-rate {cost.current_run_rate:.2f} ({direction} "
        f"{abs(cost.delta_pct):.1f}% vs prior window). Top drivers: {drivers}."
    )


def _render_risks(risks: Sequence[ForecastRisk]) -> str:
    if not risks:
        return "No forward-looking risks above threshold."
    lines = [f"- **{r.label}** (horizon `{r.horizon}`): {r.detail}" for r in risks]
    return "\n".join(lines)


def _render_guardrails(breaches: Sequence[str]) -> str:
    if not breaches:
        return "All guard metrics within threshold."
    lines = [f"- {b}" for b in breaches]
    return "**Guard-metric breaches this window:**\n" + "\n".join(lines)


def _assemble(window_label: str, headline: str, sections: Mapping[str, str]) -> str:
    return (
        f"# Operations briefing: {window_label}\n\n"
        f"{headline}\n\n"
        f"## Incidents\n\n{sections['incidents']}\n\n"
        f"## Actions\n\n{sections['actions']}\n\n"
        f"## Cost\n\n{sections['cost']}\n\n"
        f"## Forward-looking risks\n\n{sections['risks']}\n\n"
        f"## Guardrails\n\n{sections['guardrails']}\n"
    )


__all__ = [
    "ActionTally",
    "BriefingInput",
    "CostSnapshot",
    "ForecastRisk",
    "IncidentTally",
    "StakeholderBriefing",
    "StakeholderBriefingComposer",
]

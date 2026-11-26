"""Approval-escalation ladder and urgency-policy catalog loader.

Loads the YAML declarations under ``rule-catalog/escalation-ladders/`` and
validates each against its shipped JSON Schema. This is the catalog half of
the escalation design in
[escalation-and-standing-authority.md](../../../../../../docs/roadmap/decisioning/escalation-and-standing-authority.md):
which humans a finding walks through, how long each of them gets, and how a
closing forecast compresses those windows.

Not to be confused with :mod:`fdai.core.quality_gate.escalation_ladder`,
which decides whether to spend a *stronger model* on a T2 disagreement.
This module is about *humans* and approval authority.

Design points
-------------
- **Pure data and pure functions.** No adapter, no clock, no I/O beyond
  reading the catalog. :func:`resolve_schedule` takes the elapsed time and
  the forecast reading as arguments, so an audited escalation replays
  identically.
- **Fail closed.** Any schema error, duplicate id, duplicate priority, or
  violated ladder invariant raises :class:`EscalationCatalogError` carrying
  every issue. A partially valid catalog never loads.
- **Every declared rung is reachable.** The loader requires the rung TTLs to
  fit inside ``overall_deadline_seconds``, so a ladder cannot declare an
  audience that the deadline silently makes unreachable.
- **Urgency compresses, never extends.** :func:`resolve_schedule` clamps
  every effective TTL to ``[min_effective_ttl_seconds, rung.ttl_seconds]``,
  so a closing forecast walks the ladder faster while still guaranteeing
  each human a usable window.
- **Paging is not deciding.** ``also_page`` channels ride along with a rung
  for awareness. They never carry approval authority, and the loader refuses
  a rung that pages its own deciding audience.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml
from jsonschema import Draft202012Validator

LADDER_KIND: Final = "escalation_ladder"
URGENCY_KIND: Final = "urgency_policy"

_IMPACT_ORDER: Final[tuple[str, ...]] = ("resource", "resource_group", "subscription")


@dataclass(frozen=True, slots=True)
class EscalationIssue:
    """One error collected during catalog load."""

    key: str
    message: str


class EscalationCatalogError(ValueError):
    """Raised when one or more catalog entries fail schema or invariants."""

    def __init__(self, issues: Sequence[EscalationIssue]) -> None:
        super().__init__(
            "escalation catalog load failed: "
            + "; ".join(f"{issue.key}: {issue.message}" for issue in issues)
        )
        self.issues = tuple(issues)


@dataclass(frozen=True, slots=True)
class LadderSelector:
    """The first-match condition that binds a finding to a ladder."""

    environment: str
    finding_class: str
    impact_at_least: str


@dataclass(frozen=True, slots=True)
class EscalationRung:
    """One human-approval step of a ladder."""

    rung: str
    audience_group: str
    ttl_seconds: int
    category: str
    also_page: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EscalationLadder:
    """One ordered ladder of approval rungs with a hard overall deadline."""

    id: str
    priority: int
    select_when: LadderSelector
    rungs: tuple[EscalationRung, ...]
    overall_deadline_seconds: int
    description: str = ""

    @property
    def declared_walk_seconds(self) -> int:
        """Total time the ladder consumes when every rung runs its full TTL."""
        return sum(rung.ttl_seconds for rung in self.rungs)


@dataclass(frozen=True, slots=True)
class UrgencyPolicy:
    """How a closing forecast compresses rung windows."""

    id: str
    lead_time_factor: float
    min_forecast_confidence: float
    min_effective_ttl_seconds: int
    description: str = ""


@dataclass(frozen=True, slots=True)
class EscalationCatalog:
    """Everything the escalation supervisor reads from the catalog."""

    ladders: tuple[EscalationLadder, ...] = ()
    urgency_policies: tuple[UrgencyPolicy, ...] = ()

    def urgency_policy(self, policy_id: str) -> UrgencyPolicy | None:
        """Return the named policy, or ``None`` when it is not in the catalog."""
        for policy in self.urgency_policies:
            if policy.id == policy_id:
                return policy
        return None


@dataclass(frozen=True, slots=True)
class RungWindow:
    """One rung placed on the deterministic escalation timeline."""

    rung: EscalationRung
    effective_ttl_seconds: int
    starts_at_seconds: int
    expires_at_seconds: int
    compressed: bool
    metadata: Mapping[str, str] = field(default_factory=dict)


def _load_schema(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        loaded = json.load(stream)
    if not isinstance(loaded, dict):
        raise ValueError(f"escalation schema at {path} must be a JSON object")
    return loaded


def _ladder_invariants(raw: Mapping[str, Any], key: str) -> list[EscalationIssue]:
    """Return the invariants the JSON Schema alone cannot express."""
    issues: list[EscalationIssue] = []
    rungs = list(raw["rungs"])

    seen: set[str] = set()
    for rung in rungs:
        name = str(rung["rung"])
        if name in seen:
            issues.append(EscalationIssue(key=key, message=f"duplicate rung {name!r}"))
        seen.add(name)

        pages = [str(channel) for channel in rung.get("also_page") or ()]
        if len(set(pages)) != len(pages):
            issues.append(
                EscalationIssue(key=key, message=f"rung {name!r} repeats an also_page channel")
            )
        if str(rung["audience_group"]) in pages:
            issues.append(
                EscalationIssue(
                    key=key,
                    message=(
                        f"rung {name!r} pages its own deciding audience; "
                        "paging is awareness, never approval authority"
                    ),
                )
            )

    walk = sum(int(rung["ttl_seconds"]) for rung in rungs)
    deadline = int(raw["overall_deadline_seconds"])
    if walk > deadline:
        issues.append(
            EscalationIssue(
                key=key,
                message=(
                    f"rung TTLs total {walk}s but overall_deadline_seconds is {deadline}s, "
                    "so at least one declared rung is unreachable"
                ),
            )
        )
    return issues


def _to_ladder(raw: Mapping[str, Any]) -> EscalationLadder:
    selector = dict(raw["select_when"])
    return EscalationLadder(
        id=str(raw["id"]),
        priority=int(raw["priority"]),
        select_when=LadderSelector(
            environment=str(selector["environment"]),
            finding_class=str(selector["finding_class"]),
            impact_at_least=str(selector["impact_at_least"]),
        ),
        rungs=tuple(
            EscalationRung(
                rung=str(rung["rung"]),
                audience_group=str(rung["audience_group"]),
                ttl_seconds=int(rung["ttl_seconds"]),
                category=str(rung["category"]),
                also_page=tuple(str(channel) for channel in rung.get("also_page") or ()),
            )
            for rung in raw["rungs"]
        ),
        overall_deadline_seconds=int(raw["overall_deadline_seconds"]),
        description=str(raw.get("description", "")).strip(),
    )


def _to_urgency_policy(raw: Mapping[str, Any]) -> UrgencyPolicy:
    return UrgencyPolicy(
        id=str(raw["id"]),
        lead_time_factor=float(raw["lead_time_factor"]),
        min_forecast_confidence=float(raw["min_forecast_confidence"]),
        min_effective_ttl_seconds=int(raw["min_effective_ttl_seconds"]),
        description=str(raw.get("description", "")).strip(),
    )


def load_escalation_catalog(root: Path) -> EscalationCatalog:
    """Load every ladder and urgency policy under ``root``.

    Returns an empty catalog when the directory holds no YAML, which keeps a
    fork that has not authored a ladder yet from failing startup. Every other
    problem - unreadable YAML, a schema violation, a duplicate id or
    priority, a violated ladder invariant - is fatal and reported together.
    """
    if not root.is_dir():
        raise FileNotFoundError(f"escalation catalog root not a directory: {root}")

    ladder_validator = Draft202012Validator(_load_schema(root / "escalation-ladder.schema.json"))
    urgency_validator = Draft202012Validator(_load_schema(root / "urgency-policy.schema.json"))

    issues: list[EscalationIssue] = []
    ladders: list[EscalationLadder] = []
    policies: list[UrgencyPolicy] = []
    ladder_ids: dict[str, str] = {}
    priorities: dict[int, str] = {}
    policy_ids: dict[str, str] = {}

    for path in sorted(root.glob("*.yaml")):
        key = path.name
        try:
            with path.open(encoding="utf-8") as stream:
                raw = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            issues.append(EscalationIssue(key=key, message=f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, dict):
            issues.append(EscalationIssue(key=key, message="top-level must be a mapping"))
            continue

        kind = raw.get("kind")
        builder: Callable[[Mapping[str, Any]], EscalationLadder | UrgencyPolicy]
        if kind == LADDER_KIND:
            validator, builder = ladder_validator, _to_ladder
        elif kind == URGENCY_KIND:
            validator, builder = urgency_validator, _to_urgency_policy
        else:
            issues.append(
                EscalationIssue(
                    key=key,
                    message=f"kind must be {LADDER_KIND!r} or {URGENCY_KIND!r}; got {kind!r}",
                )
            )
            continue

        schema_errors = list(validator.iter_errors(raw))
        if schema_errors:
            for error in schema_errors:
                location = ".".join(str(part) for part in error.absolute_path) or "<root>"
                issues.append(EscalationIssue(key=f"{key}:{location}", message=error.message))
            continue

        if kind == LADDER_KIND:
            invariant_issues = _ladder_invariants(raw, key)
            if invariant_issues:
                issues.extend(invariant_issues)
                continue

        try:
            entry = builder(raw)
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(EscalationIssue(key=key, message=str(exc)))
            continue

        if isinstance(entry, EscalationLadder):
            prior_id = ladder_ids.get(entry.id)
            if prior_id is not None:
                issues.append(
                    EscalationIssue(
                        key=key,
                        message=f"duplicate ladder id {entry.id!r} (also {prior_id})",
                    )
                )
                continue
            prior_priority = priorities.get(entry.priority)
            if prior_priority is not None:
                issues.append(
                    EscalationIssue(
                        key=key,
                        message=(
                            f"duplicate priority {entry.priority} (also {prior_priority}); "
                            "first-match selection would not be deterministic"
                        ),
                    )
                )
                continue
            ladder_ids[entry.id] = key
            priorities[entry.priority] = key
            ladders.append(entry)
        else:
            prior_id = policy_ids.get(entry.id)
            if prior_id is not None:
                issues.append(
                    EscalationIssue(
                        key=key,
                        message=f"duplicate policy id {entry.id!r} (also {prior_id})",
                    )
                )
                continue
            policy_ids[entry.id] = key
            policies.append(entry)

    if issues:
        raise EscalationCatalogError(issues)

    return EscalationCatalog(
        ladders=tuple(sorted(ladders, key=lambda ladder: ladder.priority)),
        urgency_policies=tuple(sorted(policies, key=lambda policy: policy.id)),
    )


def _impact_rank(impact: str) -> int:
    try:
        return _IMPACT_ORDER.index(impact)
    except ValueError as exc:
        raise ValueError(
            f"unknown impact {impact!r}; expected one of {list(_IMPACT_ORDER)}"
        ) from exc


def select_ladder(
    catalog: EscalationCatalog,
    *,
    environment: str,
    finding_class: str,
    impact: str,
) -> EscalationLadder | None:
    """Return the first ladder whose selector matches, in priority order.

    Returns ``None`` when nothing matches. The caller treats that as "no
    ladder governs this finding" and MUST NOT invent one - an unmatched
    finding stays with whatever approval path already applies.
    """
    rank = _impact_rank(impact)
    for ladder in catalog.ladders:
        selector = ladder.select_when
        if (
            selector.environment == environment
            and selector.finding_class == finding_class
            and rank >= _impact_rank(selector.impact_at_least)
        ):
            return ladder
    return None


def resolve_schedule(
    ladder: EscalationLadder,
    *,
    policy: UrgencyPolicy | None = None,
    remaining_lead_time_seconds: int | None = None,
    forecast_confidence: float | None = None,
) -> tuple[RungWindow, ...]:
    """Place every rung on a deterministic timeline.

    Compression applies only when a policy, a remaining lead time, and a
    forecast confidence at or above ``policy.min_forecast_confidence`` are all
    present. Anything less - no policy, no forecast, or a forecast the policy
    does not trust - leaves every rung at its declared TTL, because an
    unproven urgency signal must never shorten a human's window.

    The result depends only on the arguments, so replaying a recorded
    escalation reproduces the same timeline.
    """
    if remaining_lead_time_seconds is not None and remaining_lead_time_seconds < 0:
        raise ValueError("remaining_lead_time_seconds MUST be >= 0")
    if forecast_confidence is not None and not 0.0 <= forecast_confidence <= 1.0:
        raise ValueError("forecast_confidence MUST be in [0.0, 1.0]")

    compressed_ttl: int | None = None
    if (
        policy is not None
        and remaining_lead_time_seconds is not None
        and forecast_confidence is not None
        and forecast_confidence >= policy.min_forecast_confidence
    ):
        compressed_ttl = max(
            int(policy.lead_time_factor * remaining_lead_time_seconds),
            policy.min_effective_ttl_seconds,
        )

    windows: list[RungWindow] = []
    cursor = 0
    for rung in ladder.rungs:
        # Clamp to the declared TTL: urgency may only ever shorten a window,
        # and the floor above keeps it from shortening one into uselessness.
        effective = rung.ttl_seconds
        if compressed_ttl is not None:
            effective = min(rung.ttl_seconds, compressed_ttl)
        windows.append(
            RungWindow(
                rung=rung,
                effective_ttl_seconds=effective,
                starts_at_seconds=cursor,
                expires_at_seconds=cursor + effective,
                compressed=effective < rung.ttl_seconds,
                metadata={
                    "ladder_id": ladder.id,
                    "urgency_policy_id": policy.id if policy is not None else "",
                },
            )
        )
        cursor += effective
    return tuple(windows)


def rung_at_elapsed(schedule: Iterable[RungWindow], elapsed_seconds: int) -> RungWindow | None:
    """Return the rung that owns ``elapsed_seconds``, or ``None`` past the end.

    ``None`` is the terminal no-op: the ladder is exhausted, nobody answered,
    and the loop stops rather than acting unattended.
    """
    if elapsed_seconds < 0:
        raise ValueError("elapsed_seconds MUST be >= 0")
    for window in schedule:
        if elapsed_seconds < window.expires_at_seconds:
            return window
    return None


def fallback_channels(schedule: Iterable[RungWindow]) -> tuple[str, ...]:
    """Return every non-deciding paging channel the ladder will touch, in order."""
    ordered: list[str] = []
    for window in schedule:
        for channel in window.rung.also_page:
            if channel not in ordered:
                ordered.append(channel)
    return tuple(ordered)


__all__ = [
    "EscalationCatalog",
    "EscalationCatalogError",
    "EscalationIssue",
    "EscalationLadder",
    "EscalationRung",
    "LadderSelector",
    "RungWindow",
    "UrgencyPolicy",
    "fallback_channels",
    "load_escalation_catalog",
    "resolve_schedule",
    "rung_at_elapsed",
    "select_ladder",
]

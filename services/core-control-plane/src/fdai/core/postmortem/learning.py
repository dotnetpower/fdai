"""Postmortem knowledge extractor.

Turns a *resolved* incident and its audit timeline into a reusable,
evidence-backed **learning candidate**: the "when this pattern happened,
this action resolved it" knowledge an organization would otherwise keep
only in an engineer's head. The extractor is deterministic and
fail-closed - it never fabricates a lesson. It emits a candidate only
when the audit trail carries a recorded root cause *and* at least one
successfully executed action; otherwise it **abstains** (returns
``None``), the same discipline the anomaly and forecast detectors use.

The output is **inert**: a :class:`PostmortemLearning` is knowledge, not
an action and not a catalog edit. It feeds the memory / discovery loop
(Muninn / Mimir) and must clear the same ``CandidateGuard`` and quality
gate as any other rule candidate before it can influence the catalog.
Every learning therefore carries a grounded ``provenance`` so the guard
in ``rule-catalog`` can accept or quarantine it.

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.6`` (postmortem)
and the living-rules discovery loop in
``docs/roadmap/rules-and-detection/rule-catalog-collection.md``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from fdai.shared.contracts.models import Incident, IncidentState

from .draft import AuditRow

# Incident states from which a durable lesson may be drawn. A lesson is
# only trustworthy once the incident reached a terminal, resolved shape;
# an open or triaging incident is still changing.
_LEARNABLE_STATES = frozenset({IncidentState.RESOLVED, IncidentState.CLOSED})

# Audit-row body keys the extractor reads. Kept as constants so the
# coupling to the audit shape is explicit and testable.
_ROOT_CAUSE_KEY = "root_cause"
_ACTION_TYPE_KEY = "action_type"
_MODE_KEY = "mode"
_OUTCOME_KEY = "outcome"

# Only an action that actually executed (not shadow) and succeeded counts
# as evidence that it resolved the incident.
_ENFORCE_MODE = "enforce"
_SUCCESS_OUTCOME = "success"


@dataclass(frozen=True, slots=True)
class PostmortemLearning:
    """One reusable, evidence-backed lesson mined from a resolved incident.

    ``signature`` is a deterministic, human-readable pattern key
    (severity + correlation anchors + root cause + resolving actions) so
    re-processing the same incident yields the same learning and the
    discovery loop can deduplicate recurring patterns. ``confidence`` in
    ``[0, 1]`` reflects evidence completeness only - it is not a promotion
    verdict. ``provenance`` grounds the learning so ``CandidateGuard`` can
    validate it; a learning without provenance is rejected upstream by
    design.
    """

    incident_id: str
    signature: str
    root_cause: str
    resolving_action_types: tuple[str, ...]
    reuse_hint: str
    confidence: float
    provenance: Mapping[str, object] = field(default_factory=dict)


class PostmortemKnowledgeExtractor:
    """Deterministic miner: resolved incident + audit -> learning candidate.

    Pure and side-effect-free. The caller owns delivery of the candidate
    to the discovery loop; the extractor only decides *whether* there is
    a grounded lesson and *what* it is.
    """

    def extract(
        self,
        *,
        incident: Incident,
        audit_rows: Sequence[AuditRow],
    ) -> PostmortemLearning | None:
        """Return a grounded learning, or ``None`` when evidence is thin.

        Abstains (returns ``None``) when the incident is not yet resolved,
        when no root cause is recorded, or when no successfully executed
        action is linked - never guesses a lesson from a partial trail.
        """
        if incident.state not in _LEARNABLE_STATES:
            return None

        root_cause = _first_root_cause(audit_rows)
        if root_cause is None:
            return None

        resolving = _resolving_action_types(audit_rows)
        if not resolving:
            return None

        anchors = _anchor_keys(incident.correlation_keys)
        signature = _build_signature(
            severity=incident.severity.value,
            anchors=anchors,
            root_cause=root_cause,
            resolving=resolving,
        )
        confidence = _evidence_confidence(
            anchors=anchors,
            resolving=resolving,
            audit_rows=audit_rows,
        )
        reuse_hint = (
            f"When a `{incident.severity.value}` incident matches "
            f"[{', '.join(anchors) or 'no anchors'}] with root cause "
            f"`{root_cause}`, the resolving action(s) were: "
            f"{', '.join(resolving)}."
        )
        provenance: dict[str, object] = {
            "source": "postmortem-learning",
            "incident_id": str(incident.incident_id),
            "severity": incident.severity.value,
            "correlation_keys": list(incident.correlation_keys),
            "evidence_action_count": len(resolving),
        }
        return PostmortemLearning(
            incident_id=str(incident.incident_id),
            signature=signature,
            root_cause=root_cause,
            resolving_action_types=resolving,
            reuse_hint=reuse_hint,
            confidence=confidence,
            provenance=provenance,
        )


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------


def _first_root_cause(rows: Sequence[AuditRow]) -> str | None:
    """Return the first recorded, non-empty root cause, or ``None``."""
    for row in rows:
        raw = row.body.get(_ROOT_CAUSE_KEY)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return None


def _resolving_action_types(rows: Sequence[AuditRow]) -> tuple[str, ...]:
    """Return distinct action types that executed (enforce) and succeeded.

    Order-preserving de-duplication so the signature is stable regardless
    of how many times an action re-fired.
    """
    seen: dict[str, None] = {}
    for row in rows:
        if not row.kind.startswith("action."):
            continue
        if str(row.body.get(_MODE_KEY)) != _ENFORCE_MODE:
            continue
        if str(row.body.get(_OUTCOME_KEY)) != _SUCCESS_OUTCOME:
            continue
        action_type = row.body.get(_ACTION_TYPE_KEY)
        if action_type is None:
            continue
        name = str(action_type).strip()
        if name:
            seen.setdefault(name, None)
    return tuple(seen.keys())


def _anchor_keys(correlation_keys: Sequence[str]) -> tuple[str, ...]:
    """Return the sorted correlation-key *anchors* (type prefixes).

    A correlation key like ``resource:vm-01`` contributes the anchor
    ``resource`` - the reusable dimension - so the learning generalizes
    across specific resource ids instead of overfitting to one. Keys with
    no ``:`` contribute themselves.
    """
    anchors: dict[str, None] = {}
    for key in correlation_keys:
        prefix = key.split(":", 1)[0].strip()
        if prefix:
            anchors.setdefault(prefix, None)
    return tuple(sorted(anchors.keys()))


def _build_signature(
    *,
    severity: str,
    anchors: Sequence[str],
    root_cause: str,
    resolving: Sequence[str],
) -> str:
    """Build a deterministic, human-readable pattern signature."""
    anchor_part = "+".join(anchors) if anchors else "none"
    action_part = "+".join(sorted(resolving))
    return f"{severity}|{anchor_part}|{root_cause}|{action_part}"


def _evidence_confidence(
    *,
    anchors: Sequence[str],
    resolving: Sequence[str],
    audit_rows: Sequence[AuditRow],
) -> float:
    """Score evidence completeness in ``[0, 1]`` - not a promotion verdict.

    More independent anchors, a recorded resolving action, and a richer
    audit timeline all raise confidence; a bare trail scores low so the
    discovery loop treats it as weak. The weights are fixed and explicit
    (no learned magic) so the score is explainable.
    """
    anchor_score = min(len(anchors), 3) / 3.0
    action_score = 1.0 if resolving else 0.0
    timeline_score = min(len(audit_rows), 10) / 10.0
    # Weighted: a resolving action is the strongest single signal.
    score = 0.5 * action_score + 0.3 * anchor_score + 0.2 * timeline_score
    return round(score, 4)


__all__ = ["PostmortemKnowledgeExtractor", "PostmortemLearning"]

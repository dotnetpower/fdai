"""Match atomic claim drafts against collected evidence entries."""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from fdai.delivery.read_api.routes.chat_claim_extraction import SCREEN_ABSENCE_RE
from fdai.delivery.read_api.routes.chat_claim_models import (
    AtomicClaim,
    ClaimDraft,
    ClaimStatus,
    EvidenceEntry,
)
from fdai.delivery.read_api.routes.chat_claim_text import (
    anchor_overlap,
    anchor_score,
    anchors,
    normalize_text,
    normalize_timestamp,
)

CAUSAL_FIELDS: Final = frozenset(
    {
        "cause",
        "detail",
        "disabled_reason",
        "gaps",
        "summary",
        "reason",
        "rca_cause",
        "rca_reason",
        "when",
        "result",
        "on_repeat",
    }
)


def verify_claim(
    index: int,
    draft: ClaimDraft,
    entries: tuple[EvidenceEntry, ...],
    *,
    complete: bool,
) -> AtomicClaim:
    claim_id = f"c{index:03d}"
    if draft.kind == "scope":
        return verify_scope(claim_id, draft, entries, complete=complete)
    if draft.kind == "causal":
        candidates = tuple(
            entry
            for entry in entries
            if entry.kind == "text"
            and entry.field in CAUSAL_FIELDS
            and causal_evidence_matches(draft, entry)
        )
    elif draft.kind == "id":
        candidates = tuple(entry for entry in entries if entry.raw_value == draft.raw_value)
    elif draft.kind == "timestamp":
        candidates = tuple(
            entry
            for entry in entries
            if normalize_timestamp(entry.raw_value) == draft.normalized_value
        )
    elif draft.kind == "percentage":
        candidates = tuple(
            entry
            for entry in entries
            if entry.kind == "percentage" and entry.normalized_value == draft.normalized_value
        )
    else:
        candidates = tuple(
            entry
            for entry in entries
            if entry.kind == "number" and entry.normalized_value == draft.normalized_value
        )
    return resolve_candidates(claim_id, draft, candidates)


def verify_scope(
    claim_id: str,
    draft: ClaimDraft,
    entries: tuple[EvidenceEntry, ...],
    *,
    complete: bool,
) -> AtomicClaim:
    if not complete:
        return claim(claim_id, draft, "unsupported", (), "incomplete_snapshot")
    lower = draft.normalized_value
    narrative = tuple(
        entry
        for entry in entries
        if entry.kind == "text" and narrative_contains(lower, entry.normalized_value)
    )
    if narrative:
        return claim(
            claim_id,
            draft,
            "supported",
            tuple(entry.ref for entry in narrative),
            None,
        )
    if SCREEN_ABSENCE_RE.search(lower):
        target_anchors = screen_absence_anchors(lower) or draft.anchors
        contradicted = tuple(
            entry for entry in entries if anchor_overlap(target_anchors, entry.anchors)
        )
        if contradicted:
            return claim(
                claim_id,
                draft,
                "unsupported",
                tuple(entry.ref for entry in contradicted),
                "screen_absence_contradicted",
            )
        return claim(claim_id, draft, "supported", (), None)
    absence = bool(re.search(r"\b(?:no|none)\b|\uc5c6\uc2b5\ub2c8\ub2e4|\uc5c6\ub2e4", lower))
    if absence:
        zero = tuple(
            entry
            for entry in entries
            if entry.kind == "number"
            and entry.normalized_value == "0"
            and anchor_overlap(draft.anchors, entry.anchors)
        )
        return resolve_candidates(claim_id, draft, zero)
    return claim(claim_id, draft, "unsupported", (), "unverifiable_scope_claim")


def resolve_candidates(
    claim_id: str,
    draft: ClaimDraft,
    candidates: tuple[EvidenceEntry, ...],
) -> AtomicClaim:
    if not candidates:
        return claim(claim_id, draft, "unsupported", (), "no_supporting_evidence")
    aliased = tuple(
        (distance, entry)
        for entry in candidates
        if (distance := nearest_alias_distance(draft, entry.aliases)) is not None
    )
    if aliased:
        nearest = min(distance for distance, _ in aliased)
        selected_by_alias = tuple(entry for distance, entry in aliased if distance == nearest)
        if len(selected_by_alias) == 1:
            return claim(
                claim_id,
                draft,
                "supported",
                (selected_by_alias[0].ref,),
                None,
            )
    anchored = tuple(entry for entry in candidates if anchor_overlap(draft.anchors, entry.anchors))
    if anchored:
        strongest_score = max(anchor_score(draft.anchors, entry.anchors) for entry in anchored)
        anchored = tuple(
            entry
            for entry in anchored
            if anchor_score(draft.anchors, entry.anchors) == strongest_score
        )
    selected = anchored or candidates
    if len(selected) > 1 and not anchored:
        structured_facts = tuple(
            entry for entry in selected if entry.ref.startswith("snapshot:fact:")
        )
        if len(structured_facts) == 1:
            selected = structured_facts
        else:
            return claim(
                claim_id,
                draft,
                "ambiguous",
                tuple(entry.ref for entry in selected),
                "multiple_unanchored_evidence",
            )
    return claim(
        claim_id,
        draft,
        "supported",
        tuple(entry.ref for entry in selected),
        None,
    )


def nearest_alias_distance(draft: ClaimDraft, aliases: tuple[str, ...]) -> int | None:
    if not aliases:
        return None
    text = unicodedata.normalize("NFKC", draft.text).casefold()
    claim_start = max(0, draft.start - draft.text_start)
    claim_end = max(claim_start, draft.end - draft.text_start)
    distances: list[int] = []
    for alias in aliases:
        normalized_alias = unicodedata.normalize("NFKC", alias).casefold().strip()
        if not normalized_alias:
            continue
        offset = text.find(normalized_alias)
        while offset >= 0:
            alias_end = offset + len(normalized_alias)
            if alias_end <= claim_start:
                distances.append(claim_start - alias_end)
            elif offset >= claim_end:
                distances.append(offset - claim_end)
            else:
                distances.append(0)
            offset = text.find(normalized_alias, offset + 1)
    return min(distances) if distances else None


def claim(
    claim_id: str,
    draft: ClaimDraft,
    status: ClaimStatus,
    refs: tuple[str, ...],
    reason: str | None,
) -> AtomicClaim:
    return AtomicClaim(
        claim_id=claim_id,
        kind=draft.kind,
        text=draft.text,
        start=draft.start,
        end=draft.end,
        raw_value=draft.raw_value,
        normalized_value=draft.normalized_value,
        unit=draft.unit,
        anchors=draft.anchors,
        status=status,
        evidence_refs=refs,
        reason_code=reason,
    )


def narrative_contains(claim_text: str, evidence: str) -> bool:
    if not claim_text or not evidence:
        return False
    return claim_text in evidence or evidence in claim_text


def causal_evidence_matches(draft: ClaimDraft, entry: EvidenceEntry) -> bool:
    evidence = normalize_text(entry.raw_value)
    if narrative_contains(draft.normalized_value, evidence):
        return True
    reason_anchors = anchors(entry.raw_value)
    if entry.field != "disabled_reason" or len(reason_anchors) < 3:
        return False
    return set(reason_anchors).issubset(anchors(draft.raw_value))


def screen_absence_anchors(text: str) -> tuple[str, ...]:
    no_target = re.search(
        r"\bno\s+(.{1,80}?)\s+(?:are\s+|is\s+)?"
        r"(?:shown|provided|included|present|visible)\b",
        text,
    )
    if no_target is not None:
        return anchors(no_target.group(1))
    verb_target = re.search(
        r"\b(?:does not|doesn't|do not|don't)\s+"
        r"(?:show|provide|include|contain)\s+(.{1,100})",
        text,
    )
    if verb_target is not None:
        return anchors(verb_target.group(1))
    return ()

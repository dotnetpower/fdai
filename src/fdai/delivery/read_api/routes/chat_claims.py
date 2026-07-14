"""Atomic claim extraction and deterministic screen-evidence verification."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

ClaimKind = Literal["id", "number", "percentage", "timestamp", "causal", "scope"]
ClaimStatus = Literal["supported", "unsupported", "ambiguous"]

_MAX_CLAIMS: Final = 64
_MAX_EVIDENCE_ENTRIES: Final = 512
_ID_RE: Final = re.compile(
    r"\b(?:ops|remediate|governance|tool)\.[a-z0-9]+(?:-[a-z0-9]+)+\b"
    r"|\b(?:corr|evt|event|inc|incident|rule)-[A-Za-z0-9_.:-]*[A-Za-z0-9_]\b"
    r"|\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_TIMESTAMP_RE: Final = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b"
)
_PERCENT_RE: Final = re.compile(
    r"(?<![\w.])[-+]?\d+(?:\.\d+)?\s*(?:%|percent(?:age)?\b|\ud37c\uc13c\ud2b8)",
    re.IGNORECASE,
)
_NUMBER_RE: Final = re.compile(
    r"(?<![\w.-])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?![A-Za-z0-9_-])"
)
_CAUSAL_RE: Final = re.compile(
    r"\b(?:because|due to|caused by|resulted from|reason is)\b"
    r"|\ub54c\ubb38|\uc6d0\uc778\uc740|\uc6d0\uc778\uc774|\uc774\uc720\ub294",
    re.IGNORECASE,
)
_SCOPE_RE: Final = re.compile(
    r"\b(?:no|none)\b"
    r"|\uc5c6\uc2b5\ub2c8\ub2e4|\uc5c6\ub2e4",
    re.IGNORECASE,
)
_SCREEN_ABSENCE_RE: Final = re.compile(
    r"\b(?:does not|doesn't|do not|don't)\s+(?:show|provide|include|contain)\b"
    r"|\bno\s+.{1,80}?\s+(?:are\s+|is\s+)?(?:shown|provided|included|present|visible)\b"
    r"|\bnot\s+(?:shown|provided|included|present|visible)\b"
    "|\ubcf4\uc774\uc9c0 \uc54a|\ud45c\uc2dc\ub418\uc9c0 \uc54a"
    "|\uc81c\uacf5\ub418\uc9c0 \uc54a|\ud3ec\ud568\ub418\uc9c0 \uc54a"
    "|\ud3ec\ud568\ub418\uc5b4 \uc788\uc9c0 \uc54a",
    re.IGNORECASE,
)
_WORD_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{1,}|[\uac00-\ud7a3]{2,}")
_ANCHOR_STOP: Final = frozenset(
    {
        "about",
        "answer",
        "because",
        "current",
        "from",
        "latest",
        "only",
        "screen",
        "shows",
        "that",
        "there",
        "this",
        "value",
        "with",
    }
)
_CAUSAL_FIELDS: Final = frozenset(
    {"cause", "detail", "gaps", "summary", "reason", "rca_cause", "rca_reason"}
)


@dataclass(frozen=True, slots=True)
class EvidenceEntry:
    ref: str
    path: str
    field: str
    kind: str
    raw_value: str
    normalized_value: str
    anchors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "path": self.path,
            "field": self.field,
            "kind": self.kind,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "anchors": list(self.anchors),
        }


@dataclass(frozen=True, slots=True)
class AtomicClaim:
    claim_id: str
    kind: ClaimKind
    text: str
    start: int
    end: int
    raw_value: str
    normalized_value: str
    unit: str | None
    anchors: tuple[str, ...]
    status: ClaimStatus
    evidence_refs: tuple[str, ...]
    reason_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "kind": self.kind,
            "text": self.text,
            "span": {"start": self.start, "end": self.end},
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "unit": self.unit,
            "anchors": list(self.anchors),
            "status": self.status,
            "evidence_refs": list(self.evidence_refs),
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class EvidenceManifest:
    schema_version: int
    manifest_id: str
    authority: str
    route_id: str | None
    captured_at: str | None
    complete: bool
    source_entry_count: int
    entries: tuple[EvidenceEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "authority": self.authority,
            "route_id": self.route_id,
            "captured_at": self.captured_at,
            "complete": self.complete,
            "source_entry_count": self.source_entry_count,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class ScreenClaimResult:
    claims: tuple[AtomicClaim, ...]
    manifest: EvidenceManifest
    overflow: bool = False

    @property
    def failed_claim_ids(self) -> tuple[str, ...]:
        return tuple(claim.claim_id for claim in self.claims if claim.status != "supported")

    @property
    def supported(self) -> bool:
        return not self.overflow and not self.failed_claim_ids


@dataclass(frozen=True, slots=True)
class _ClaimDraft:
    kind: ClaimKind
    text: str
    start: int
    end: int
    raw_value: str
    normalized_value: str
    unit: str | None
    anchors: tuple[str, ...]


def verify_screen_claims(answer: str, view_context: Mapping[str, Any]) -> ScreenClaimResult:
    """Extract atomic claims and match each against browser snapshot evidence."""

    entries = _collect_evidence(view_context)
    drafts, overflow = _extract_claims(answer)
    complete = not bool(
        view_context.get("_records_truncated")
        or view_context.get("_snapshot_truncated")
        or view_context.get("_snapshot_unserialisable")
    )
    claims = tuple(
        _verify_claim(index, draft, entries, complete=complete)
        for index, draft in enumerate(drafts, start=1)
    )
    used_refs = {ref for claim in claims for ref in claim.evidence_refs}
    used_entries = tuple(entry for entry in entries if entry.ref in used_refs)
    route_id = _optional_text(view_context.get("routeId"))
    captured_at = _optional_text(view_context.get("capturedAt"))
    authority = _evidence_authority(view_context)
    manifest_payload = {
        "schema_version": 1,
        "authority": authority,
        "route_id": route_id,
        "captured_at": captured_at,
        "complete": complete,
        "source_entry_count": len(entries),
        "entries": [entry.to_dict() for entry in used_entries],
    }
    canonical = json.dumps(manifest_payload, sort_keys=True, separators=(",", ":"))
    manifest = EvidenceManifest(
        schema_version=1,
        manifest_id=f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}",
        authority=authority,
        route_id=route_id,
        captured_at=captured_at,
        complete=complete,
        source_entry_count=len(entries),
        entries=used_entries,
    )
    return ScreenClaimResult(claims=claims, manifest=manifest, overflow=overflow)


def _collect_evidence(view_context: Mapping[str, Any]) -> tuple[EvidenceEntry, ...]:
    entries: list[EvidenceEntry] = []
    for field in ("headline", "routeLabel", "purpose"):
        value = view_context.get(field)
        if isinstance(value, str) and value:
            _append_entry(
                entries,
                ref=f"snapshot:{field}",
                path=f"/{field}",
                field=field,
                value=value,
                extra_anchors=(),
            )
    facts = view_context.get("facts")
    if isinstance(facts, Sequence) and not isinstance(facts, (str, bytes)):
        for index, fact in enumerate(facts):
            if not isinstance(fact, Mapping):
                continue
            field = _optional_text(fact.get("key")) or f"fact_{index}"
            _append_entry(
                entries,
                ref=f"snapshot:fact:{field}",
                path=f"/facts/{index}/value",
                field=field,
                value=fact.get("value"),
                extra_anchors=(str(fact.get("group", "")),),
            )
    records = view_context.get("records")
    if isinstance(records, Mapping):
        for collection, rows in records.items():
            if not isinstance(collection, str):
                continue
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                continue
            for row_index, row in enumerate(rows):
                if not isinstance(row, Mapping):
                    continue
                for field, value in row.items():
                    if not isinstance(field, str):
                        continue
                    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                        for value_index, item in enumerate(value):
                            _append_entry(
                                entries,
                                ref=(
                                    f"snapshot:record:{collection}:{row_index}:"
                                    f"{field}:{value_index}"
                                ),
                                path=(f"/records/{collection}/{row_index}/{field}/{value_index}"),
                                field=field,
                                value=item,
                                extra_anchors=(collection,),
                            )
                        continue
                    _append_entry(
                        entries,
                        ref=f"snapshot:record:{collection}:{row_index}:{field}",
                        path=f"/records/{collection}/{row_index}/{field}",
                        field=field,
                        value=value,
                        extra_anchors=(collection,),
                    )
    tool = view_context.get("_tool_evidence")
    if isinstance(tool, Mapping):
        _collect_nested_evidence(
            entries,
            tool.get("result"),
            ref_prefix="tool:result",
            path_prefix="/_tool_evidence/result",
        )
    agent = view_context.get("_agent_evidence")
    if isinstance(agent, Mapping):
        _collect_nested_evidence(
            entries,
            agent,
            ref_prefix="agent",
            path_prefix="/_agent_evidence",
        )
    concept = view_context.get("_concept_evidence")
    if isinstance(concept, Mapping):
        _collect_nested_evidence(
            entries,
            concept.get("entries"),
            ref_prefix="glossary:entries",
            path_prefix="/_concept_evidence/entries",
        )
    return tuple(entries)


def _collect_nested_evidence(
    entries: list[EvidenceEntry],
    value: Any,
    *,
    ref_prefix: str,
    path_prefix: str,
) -> None:
    if len(entries) >= _MAX_EVIDENCE_ENTRIES:
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            _collect_nested_evidence(
                entries,
                item,
                ref_prefix=f"{ref_prefix}:{key}",
                path_prefix=f"{path_prefix}/{key}",
            )
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _collect_nested_evidence(
                entries,
                item,
                ref_prefix=f"{ref_prefix}:{index}",
                path_prefix=f"{path_prefix}/{index}",
            )
        return
    field = ref_prefix.rsplit(":", 1)[-1]
    _append_entry(
        entries,
        ref=ref_prefix,
        path=path_prefix,
        field=field,
        value=value,
        extra_anchors=(),
    )


def _append_entry(
    entries: list[EvidenceEntry],
    *,
    ref: str,
    path: str,
    field: str,
    value: Any,
    extra_anchors: tuple[str, ...],
) -> None:
    if len(entries) >= _MAX_EVIDENCE_ENTRIES:
        return
    if value is None or isinstance(value, (Mapping, Sequence)) and not isinstance(value, str):
        return
    if isinstance(value, bool):
        raw = "true" if value else "false"
        kind = "boolean"
        normalized = raw
    elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        raw = str(value)
        kind = "number"
        normalized = _normalize_number(raw) or raw
    elif isinstance(value, str):
        raw = value
        identifier = _ID_RE.fullmatch(raw.strip())
        timestamp = _normalize_timestamp(raw)
        percentage = _PERCENT_RE.fullmatch(raw.strip())
        number_match = _NUMBER_RE.fullmatch(raw.strip())
        if identifier is not None:
            kind = "id"
            normalized = raw.strip()
        elif timestamp is not None:
            kind = "timestamp"
            normalized = timestamp
        elif percentage is not None:
            kind = "percentage"
            normalized = _normalize_claim_value("percentage", raw) or _normalize_text(raw)
        elif number_match is not None:
            kind = "number"
            normalized = _normalize_number(raw) or _normalize_text(raw)
        else:
            kind = "text"
            normalized = _normalize_text(raw)
    else:
        return
    anchor_source = " ".join((field, *extra_anchors, raw if kind == "text" else ""))
    anchors = _anchors(anchor_source)
    entries.append(
        EvidenceEntry(
            ref=ref,
            path=path,
            field=field,
            kind=kind,
            raw_value=raw,
            normalized_value=normalized,
            anchors=anchors,
        )
    )
    if kind == "text":
        occupied: list[tuple[int, int]] = []
        for index, match in enumerate(_ID_RE.finditer(raw)):
            occupied.append((match.start(), match.end()))
            entries.append(
                EvidenceEntry(
                    ref=f"{ref}:id:{index}",
                    path=path,
                    field=field,
                    kind="id",
                    raw_value=match.group(0),
                    normalized_value=match.group(0),
                    anchors=anchors,
                )
            )
        for index, match in enumerate(_PERCENT_RE.finditer(raw)):
            if _overlaps(match.start(), match.end(), occupied):
                continue
            normalized_percent = _normalize_claim_value("percentage", match.group(0))
            if normalized_percent is None:
                continue
            occupied.append((match.start(), match.end()))
            entries.append(
                EvidenceEntry(
                    ref=f"{ref}:percentage:{index}",
                    path=path,
                    field=field,
                    kind="percentage",
                    raw_value=match.group(0),
                    normalized_value=normalized_percent,
                    anchors=anchors,
                )
            )
        for index, match in enumerate(_NUMBER_RE.finditer(raw)):
            if _overlaps(match.start(), match.end(), occupied):
                continue
            normalized_number = _normalize_number(match.group(0))
            if normalized_number is None:
                continue
            entries.append(
                EvidenceEntry(
                    ref=f"{ref}:number:{index}",
                    path=path,
                    field=field,
                    kind="number",
                    raw_value=match.group(0),
                    normalized_value=normalized_number,
                    anchors=anchors,
                )
            )
    if kind == "number" and _is_ratio_field(field):
        ratio_value = _decimal(raw)
        if ratio_value is not None and Decimal("0") <= ratio_value <= Decimal("1"):
            percent = _normalize_number(str(ratio_value * 100))
            if percent is not None:
                entries.append(
                    EvidenceEntry(
                        ref=f"{ref}:percent",
                        path=path,
                        field=field,
                        kind="percentage",
                        raw_value=f"{percent}%",
                        normalized_value=percent,
                        anchors=anchors,
                    )
                )


def _extract_claims(answer: str) -> tuple[tuple[_ClaimDraft, ...], bool]:
    occupied: list[tuple[int, int]] = []
    drafts: list[_ClaimDraft] = []
    for kind, pattern in (
        ("timestamp", _TIMESTAMP_RE),
        ("percentage", _PERCENT_RE),
        ("id", _ID_RE),
        ("number", _NUMBER_RE),
    ):
        for match in pattern.finditer(answer):
            if _overlaps(match.start(), match.end(), occupied):
                continue
            if kind == "number" and _looks_like_non_claim_number(
                answer, match.start(), match.end()
            ):
                continue
            raw = match.group(0).strip()
            normalized = _normalize_claim_value(kind, raw)
            if normalized is None:
                continue
            occupied.append((match.start(), match.end()))
            drafts.append(
                _ClaimDraft(
                    kind=kind,  # type: ignore[arg-type]
                    text=_sentence_at(answer, match.start(), match.end()),
                    start=match.start(),
                    end=match.end(),
                    raw_value=raw,
                    normalized_value=normalized,
                    unit="%" if kind == "percentage" else None,
                    anchors=_anchors(_window(answer, match.start(), match.end())),
                )
            )
    for sentence, start, end in _sentences(answer):
        marker = _CAUSAL_RE.search(sentence)
        if marker:
            cause = sentence[marker.end() :].strip(" :,-.")
            if cause:
                drafts.append(
                    _ClaimDraft(
                        kind="causal",
                        text=sentence,
                        start=start,
                        end=end,
                        raw_value=cause,
                        normalized_value=_normalize_text(cause),
                        unit=None,
                        anchors=_anchors(sentence[: marker.start()]),
                    )
                )
        if _SCOPE_RE.search(sentence) or _SCREEN_ABSENCE_RE.search(sentence):
            drafts.append(
                _ClaimDraft(
                    kind="scope",
                    text=sentence,
                    start=start,
                    end=end,
                    raw_value=sentence,
                    normalized_value=_normalize_text(sentence),
                    unit=None,
                    anchors=_anchors(sentence),
                )
            )
    drafts.sort(key=lambda claim: (claim.start, claim.end, claim.kind))
    overflow = len(drafts) > _MAX_CLAIMS
    return tuple(drafts[:_MAX_CLAIMS]), overflow


def _verify_claim(
    index: int,
    draft: _ClaimDraft,
    entries: tuple[EvidenceEntry, ...],
    *,
    complete: bool,
) -> AtomicClaim:
    claim_id = f"c{index:03d}"
    if draft.kind == "scope":
        return _verify_scope(claim_id, draft, entries, complete=complete)
    if draft.kind == "causal":
        candidates = tuple(
            entry
            for entry in entries
            if entry.kind == "text"
            and entry.field in _CAUSAL_FIELDS
            and _narrative_contains(
                draft.normalized_value,
                _normalize_text(entry.raw_value),
            )
        )
    elif draft.kind == "id":
        candidates = tuple(entry for entry in entries if entry.raw_value == draft.raw_value)
    elif draft.kind == "timestamp":
        candidates = tuple(
            entry
            for entry in entries
            if _normalize_timestamp(entry.raw_value) == draft.normalized_value
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
    return _resolve_candidates(claim_id, draft, candidates)


def _verify_scope(
    claim_id: str,
    draft: _ClaimDraft,
    entries: tuple[EvidenceEntry, ...],
    *,
    complete: bool,
) -> AtomicClaim:
    if not complete:
        return _claim(claim_id, draft, "unsupported", (), "incomplete_snapshot")
    lower = draft.normalized_value
    narrative = tuple(
        entry
        for entry in entries
        if entry.kind == "text" and _narrative_contains(lower, entry.normalized_value)
    )
    if narrative:
        return _claim(
            claim_id,
            draft,
            "supported",
            tuple(entry.ref for entry in narrative),
            None,
        )
    if _SCREEN_ABSENCE_RE.search(lower):
        target_anchors = _screen_absence_anchors(lower) or draft.anchors
        contradicted = tuple(
            entry for entry in entries if _anchor_overlap(target_anchors, entry.anchors)
        )
        if contradicted:
            return _claim(
                claim_id,
                draft,
                "unsupported",
                tuple(entry.ref for entry in contradicted),
                "screen_absence_contradicted",
            )
        return _claim(claim_id, draft, "supported", (), None)
    absence = bool(re.search(r"\b(?:no|none)\b|\uc5c6\uc2b5\ub2c8\ub2e4|\uc5c6\ub2e4", lower))
    if absence:
        zero = tuple(
            entry
            for entry in entries
            if entry.kind == "number"
            and entry.normalized_value == "0"
            and _anchor_overlap(draft.anchors, entry.anchors)
        )
        return _resolve_candidates(claim_id, draft, zero)
    return _claim(claim_id, draft, "unsupported", (), "unverifiable_scope_claim")


def _resolve_candidates(
    claim_id: str,
    draft: _ClaimDraft,
    candidates: tuple[EvidenceEntry, ...],
) -> AtomicClaim:
    if not candidates:
        return _claim(claim_id, draft, "unsupported", (), "no_supporting_evidence")
    anchored = tuple(entry for entry in candidates if _anchor_overlap(draft.anchors, entry.anchors))
    selected = anchored or candidates
    if len(selected) > 1 and not anchored:
        structured_facts = tuple(
            entry for entry in selected if entry.ref.startswith("snapshot:fact:")
        )
        if len(structured_facts) == 1:
            selected = structured_facts
        else:
            return _claim(
                claim_id,
                draft,
                "ambiguous",
                tuple(entry.ref for entry in selected),
                "multiple_unanchored_evidence",
            )
    return _claim(
        claim_id,
        draft,
        "supported",
        tuple(entry.ref for entry in selected),
        None,
    )


def _claim(
    claim_id: str,
    draft: _ClaimDraft,
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


def _normalize_claim_value(kind: str, raw: str) -> str | None:
    if kind == "timestamp":
        return _normalize_timestamp(raw)
    if kind == "percentage":
        value = re.sub(r"(?:%|percent(?:age)?|\ud37c\uc13c\ud2b8)", "", raw, flags=re.I)
        return _normalize_number(value)
    if kind == "number":
        return _normalize_number(raw)
    return raw


def _normalize_number(raw: str) -> str | None:
    number = _decimal(raw.replace(",", "").strip())
    if number is None:
        return None
    normalized = format(number.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _normalize_timestamp(raw: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return raw
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalize_text(raw: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", raw).casefold().split())


def _anchors(raw: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", raw)
    camel_split = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", normalized)
    token_source = re.sub(r"[_.-]+", " ", camel_split)
    return tuple(
        sorted(
            {
                _anchor_token(token)
                for token in _WORD_RE.findall(token_source)
                if _anchor_token(token) not in _ANCHOR_STOP
            }
        )
    )


def _anchor_token(raw: str) -> str:
    token = raw.casefold()
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _anchor_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return bool(set(left) & set(right))


def _window(text: str, start: int, end: int, radius: int = 48) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)]


def _sentence_at(text: str, start: int, end: int) -> str:
    for sentence, sentence_start, sentence_end in _sentences(text):
        if sentence_start <= start and end <= sentence_end:
            return sentence
    return text[start:end]


def _sentences(text: str) -> tuple[tuple[str, int, int], ...]:
    out: list[tuple[str, int, int]] = []
    for match in re.finditer(r"[^\n.!?]+(?:[.!?]+|$)", text):
        sentence = match.group(0).strip()
        if sentence:
            out.append((sentence, match.start(), match.end()))
    return tuple(out)


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def _looks_like_non_claim_number(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 2) : start]
    after = text[end : min(len(text), end + 1)]
    token = text[start:end]
    return bool(
        re.search(r"[TtVv]$", before)
        or (start == 0 or text[start - 1] == "\n")
        and after in {".", ")"}
        or len(token) == 1
        and token in {"0", "1", "2"}
        and before.lower().endswith("t")
    )


def _is_ratio_field(field: str) -> bool:
    lower = field.lower()
    return any(token in lower for token in ("rate", "ratio", "share", "confidence"))


def _narrative_contains(claim: str, evidence: str) -> bool:
    if not claim or not evidence:
        return False
    return claim in evidence or evidence in claim


def _screen_absence_anchors(text: str) -> tuple[str, ...]:
    no_target = re.search(
        r"\bno\s+(.{1,80}?)\s+(?:are\s+|is\s+)?"
        r"(?:shown|provided|included|present|visible)\b",
        text,
    )
    if no_target is not None:
        return _anchors(no_target.group(1))
    verb_target = re.search(
        r"\b(?:does not|doesn't|do not|don't)\s+"
        r"(?:show|provide|include|contain)\s+(.{1,100})",
        text,
    )
    if verb_target is not None:
        return _anchors(verb_target.group(1))
    return ()


def _evidence_authority(view_context: Mapping[str, Any]) -> str:
    tool = view_context.get("_tool_evidence")
    if isinstance(tool, Mapping):
        authority = _optional_text(tool.get("authority"))
        return authority or "server_read_model"
    if isinstance(view_context.get("_agent_evidence"), Mapping):
        return "pantheon_runtime"
    concept = view_context.get("_concept_evidence")
    if isinstance(concept, Mapping):
        authority = _optional_text(concept.get("authority"))
        return authority or "fdai_glossary"
    return "client_snapshot"


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "AtomicClaim",
    "EvidenceEntry",
    "EvidenceManifest",
    "ScreenClaimResult",
    "verify_screen_claims",
]

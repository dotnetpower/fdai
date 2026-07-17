"""Deterministic terminal verification for progressive Command Deck answers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from fdai.delivery.read_api.routes.chat_claims import (
    AtomicClaim,
    EvidenceManifest,
    ScreenClaimResult,
    verify_screen_claims,
)

VerificationStatus = Literal["verified", "consistent", "corrected", "unverified"]

_KOREAN_TOPIC_LABELS = {
    "memory": "\uba54\ubaa8\ub9ac",
    "cpu": "CPU",
    "latency": "\uc9c0\uc5f0",
    "network": "\ub124\ud2b8\uc6cc\ud06c",
    "database": "\ub370\uc774\ud130\ubca0\uc774\uc2a4",
    "storage": "\uc2a4\ud1a0\ub9ac\uc9c0",
    "deployment": "\ubc30\ud3ec",
    "quota": "\ud560\ub2f9\ub7c9",
    "cost": "\ube44\uc6a9",
}


@dataclass(frozen=True, slots=True)
class AnswerVerification:
    """Canonical answer plus the trust state the UI may render."""

    status: VerificationStatus
    answer: str
    authority: str
    checks_completed: int
    checks_total: int
    evidence_refs: tuple[str, ...] = ()
    reason_code: str | None = None
    claims: tuple[AtomicClaim, ...] = ()
    evidence_manifest: EvidenceManifest | None = None
    failed_claim_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "authority": self.authority,
            "checks_completed": self.checks_completed,
            "checks_total": self.checks_total,
            "evidence_refs": list(self.evidence_refs),
            "reason_code": self.reason_code,
            "claims": [claim.to_dict() for claim in self.claims],
            "failed_claim_ids": list(self.failed_claim_ids),
        }
        if self.evidence_manifest is not None:
            payload["evidence_manifest"] = self.evidence_manifest.to_dict()
        return payload


def verify_answer(
    provisional: str,
    view_context: Mapping[str, Any],
    *,
    locale: str | None,
) -> AnswerVerification:
    """Verify one provisional answer and return its canonical revision.

    Screen-only answers can only be checked for consistency with the supplied
    browser snapshot. Operational answers are replaced with deterministic prose
    rendered from the server-owned evidence state, so unsupported model text
    never becomes the terminal conversation history.
    """

    raw = view_context.get("_operational_evidence")
    if not isinstance(raw, Mapping):
        screen = verify_screen_claims(provisional, view_context)
        if screen.overflow or not screen.manifest.complete or not screen.supported:
            concept_correction = _correct_concept_scope_additions(
                provisional,
                view_context,
                screen.claims,
            )
            if concept_correction is not None:
                corrected, corrected_screen = concept_correction
                return AnswerVerification(
                    status="corrected",
                    answer=corrected,
                    authority=corrected_screen.manifest.authority,
                    checks_completed=len(corrected_screen.claims),
                    checks_total=len(corrected_screen.claims),
                    evidence_refs=tuple(
                        dict.fromkeys(
                            ref for claim in corrected_screen.claims for ref in claim.evidence_refs
                        )
                    ),
                    reason_code="concept_scope_claims_removed",
                    claims=corrected_screen.claims,
                    evidence_manifest=corrected_screen.manifest,
                )
            screen_correction = _correct_screen_unsupported_sentences(
                provisional,
                view_context,
                screen,
            )
            if screen_correction is not None:
                corrected, corrected_screen = screen_correction
                return AnswerVerification(
                    status="corrected",
                    answer=corrected,
                    authority=corrected_screen.manifest.authority,
                    checks_completed=len(corrected_screen.claims),
                    checks_total=len(corrected_screen.claims),
                    evidence_refs=tuple(
                        dict.fromkeys(
                            ref for claim in corrected_screen.claims for ref in claim.evidence_refs
                        )
                    ),
                    reason_code="screen_unsupported_sentences_removed",
                    claims=corrected_screen.claims,
                    evidence_manifest=corrected_screen.manifest,
                )
            korean = _is_korean(locale)
            answer = (
                "\ud604\uc7ac \ud654\uba74 \uadfc\uac70\ub85c \ub2f5\ubcc0\uc758 "
                "\ubaa8\ub4e0 \uc0ac\uc2e4 claim\uc744 \ud655\uc778\ud560 \uc218 "
                "\uc5c6\uc5b4 \ub2f5\ubcc0\uc744 \ud655\uc815\ud558\uc9c0 "
                "\uc54a\uc558\uc2b5\ub2c8\ub2e4. \ud654\uba74\uc758 \ubc94\uc704\ub97c "
                "\uc904\uc774\uac70\ub098 \uad6c\uccb4\uc801\uc778 \ud56d\ubaa9\uc744 "
                "\uc120\ud0dd\ud55c \ub4a4 \ub2e4\uc2dc \uc9c8\ubb38\ud574 \uc8fc\uc138\uc694."
                if korean
                else "Not every factual claim could be confirmed from the current screen, "
                "so the answer was not finalized. Narrow the screen or select a specific "
                "item and ask again."
            )
            reason = (
                "screen_claim_overflow"
                if screen.overflow
                else (
                    "screen_snapshot_incomplete"
                    if not screen.manifest.complete
                    else "screen_claim_mismatch"
                )
            )

            return AnswerVerification(
                status="unverified",
                answer=answer,
                authority=screen.manifest.authority,
                checks_completed=sum(1 for claim in screen.claims if claim.status == "supported"),
                checks_total=len(screen.claims),
                evidence_refs=tuple(
                    dict.fromkeys(ref for claim in screen.claims for ref in claim.evidence_refs)
                ),
                reason_code=reason,
                claims=screen.claims,
                evidence_manifest=screen.manifest,
                failed_claim_ids=screen.failed_claim_ids,
            )
        return AnswerVerification(
            status="consistent",
            answer=provisional,
            authority=screen.manifest.authority,
            checks_completed=len(screen.claims),
            checks_total=len(screen.claims),
            evidence_refs=tuple(
                dict.fromkeys(ref for claim in screen.claims for ref in claim.evidence_refs)
            ),
            reason_code=(
                "screen_claims_supported" if screen.claims else "screen_no_checkable_claims"
            ),
            claims=screen.claims,
            evidence_manifest=screen.manifest,
        )

    evidence = dict(raw)
    state = evidence.get("status")
    korean = _is_korean(locale)
    if state == "unavailable":
        answer = (
            "\uc6b4\uc601 \uadfc\uac70 \uc870\ud68c\ub97c \uc644\ub8cc\ud558\uc9c0 "
            "\ubabb\ud574 \ud604\uc7ac \ub2f5\ubcc0\uc744 \uac80\uc99d\ud560 \uc218 "
            "\uc5c6\uc2b5\ub2c8\ub2e4. \uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc "
            "\uc2dc\ub3c4\ud574 \uc8fc\uc138\uc694."
            if korean
            else "Operational evidence could not be retrieved, so this answer could not be "
            "verified. Try again shortly."
        )
        return _result("unverified", answer, "evidence_unavailable")
    if state == "none":
        searched = _integer(evidence.get("searched_recent_incidents"))
        topics = _strings(evidence.get("topic_terms"))
        scope = str(searched) if searched is not None else "the bounded recent set"
        topic = _topic_text(topics, korean=korean)
        answer = (
            f"\ucd5c\uadfc \uc778\uc2dc\ub358\ud2b8 {scope}\uac74\uc744 "
            f"\ud655\uc778\ud588\uc9c0\ub9cc {topic}\uc640 \uc77c\uce58\ud558\ub294 "
            "\uc0ac\uac74\uc740 \uc5c6\uc5c8\uc2b5\ub2c8\ub2e4. \uc774 "
            "\uc81c\ud55c\ub41c \uac80\uc0c9 \ubc94\uc704\uc5d0\uc11c\ub294 "
            "\uc6d0\uc778\uc744 \ud655\uc815\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4."
            if korean and searched is not None
            else (
                f"\uc81c\ud55c\ub41c \ucd5c\uadfc \uc778\uc2dc\ub358\ud2b8 "
                f"\ubc94\uc704\uc5d0\uc11c {topic}\uc640 \uc77c\uce58\ud558\ub294 "
                "\uc0ac\uac74\uc744 \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. "
                "\ub530\ub77c\uc11c \uc6d0\uc778\uc744 \ud655\uc815\ud560 \uc218 "
                "\uc5c6\uc2b5\ub2c8\ub2e4."
                if korean
                else f"The {scope} incidents searched contained no match for {topic}. "
                "No cause can be established from this bounded search."
            )
        )
        search_refs = (f"incident-search:recent:{searched}",) if searched is not None else ()
        return _result(
            _changed(provisional, answer),
            answer,
            "no_matching_incident",
            search_refs,
        )
    if state == "ambiguous":
        candidates = _mappings(evidence.get("candidates"))[:5]
        lines = [
            f"- {_text(item.get('correlation_id'), 'unknown')}: "
            f"{_text(item.get('title'), 'untitled')}"
            for item in candidates
        ]
        answer = (
            "\uc5ec\ub7ec \uc778\uc2dc\ub358\ud2b8\uac00 \uc9c8\ubb38\uacfc "
            "\ub3d9\uc77c\ud558\uac8c \uc77c\uce58\ud569\ub2c8\ub2e4. "
            "\ud655\uc778\ud560 \ub300\uc0c1\uc744 \uc120\ud0dd\ud574 "
            "\uc8fc\uc138\uc694:\n"
            if korean
            else "Multiple incidents match the question equally. Choose one to verify:\n"
        ) + "\n".join(lines)
        candidate_refs = tuple(
            f"incident:{corr}"
            for item in candidates
            if (corr := _optional_text(item.get("correlation_id"))) is not None
        )
        return _result(
            _changed(provisional, answer),
            answer,
            "ambiguous_incident",
            candidate_refs,
        )
    if state != "matched":
        answer = (
            "\uc6b4\uc601 \uadfc\uac70 \uc0c1\ud0dc\ub97c \ud655\uc778\ud560 "
            "\uc218 \uc5c6\uc5b4 \ub2f5\ubcc0\uc744 \uac80\uc99d\ud558\uc9c0 "
            "\ubabb\ud588\uc2b5\ub2c8\ub2e4."
            if korean
            else "The operational evidence state was not recognized, so the answer is unverified."
        )
        return _result("unverified", answer, "unknown_evidence_state")

    selected = evidence.get("selected_incident")
    incident = dict(selected) if isinstance(selected, Mapping) else {}
    correlation = _text(incident.get("correlation_id"), "unknown")
    title = _text(incident.get("title"), "untitled incident")
    recorded_at = _text(incident.get("last_updated_at"), "unknown time")
    hypotheses = _mappings(evidence.get("grounded_hypotheses"))
    refs: list[str] = [f"incident:{correlation}"]
    if hypotheses:
        hypothesis = hypotheses[0]
        cause = _text(hypothesis.get("cause"), "")
        citations = _mappings(hypothesis.get("citations"))
        refs.extend(
            f"{_text(item.get('kind'), 'evidence')}:{_text(item.get('ref'), 'unknown')}"
            for item in citations
        )
        answer = (
            f"{correlation} ({title})\uc758 \uac80\uc99d\ub41c \uc6d0\uc778\uc740 "
            f"\ub2e4\uc74c\uacfc \uac19\uc2b5\ub2c8\ub2e4: {cause} \ub9c8\uc9c0\ub9c9 "
            f"\uadfc\uac70 \uc2dc\uac01\uc740 {recorded_at}\uc785\ub2c8\ub2e4."
            if korean
            else f"The verified cause for {correlation} ({title}) is: {cause} "
            f"The latest evidence is from {recorded_at}."
        )
        return _result(_changed(provisional, answer), answer, "grounded_rca", tuple(refs))

    answer = (
        f"{correlation} ({title})\uc740 {recorded_at}\uc5d0 \ub9c8\uc9c0\ub9c9\uc73c\ub85c "
        "\uac31\uc2e0\ub418\uc5c8\uc9c0\ub9cc, citation\uc744 \uac16\ucd98 grounded "
        "root cause\ub294 \uae30\ub85d\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4. "
        "\uc6d0\uc778\uc744 \ud655\uc815\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4."
        if korean
        else f"{correlation} ({title}) was last updated at {recorded_at}, but no grounded "
        "root cause with citations is recorded. The cause cannot be confirmed."
    )
    return _result(
        _changed(provisional, answer),
        answer,
        "no_grounded_rca",
        tuple(refs),
    )


def _result(
    status: VerificationStatus,
    answer: str,
    reason_code: str,
    refs: tuple[str, ...] = (),
) -> AnswerVerification:
    return AnswerVerification(
        status=status,
        answer=answer,
        authority="server_read_model",
        checks_completed=1,
        checks_total=1,
        evidence_refs=refs,
        reason_code=reason_code,
    )


def _changed(provisional: str, canonical: str) -> VerificationStatus:
    return "verified" if provisional.strip() == canonical.strip() else "corrected"


def _correct_concept_scope_additions(
    answer: str,
    view_context: Mapping[str, Any],
    claims: Sequence[AtomicClaim],
) -> tuple[str, ScreenClaimResult] | None:
    """Remove unsupported scope-only addenda from a glossary answer once."""

    if not isinstance(view_context.get("_concept_evidence"), Mapping):
        return None
    failed = tuple(claim for claim in claims if claim.status != "supported")
    if not failed or any(claim.kind != "scope" for claim in failed):
        return None
    corrected = answer
    for claim in sorted(failed, key=lambda item: item.start, reverse=True):
        corrected = corrected[: claim.start] + corrected[claim.end :]
    corrected = corrected.strip()
    if not corrected:
        return None
    verified = verify_screen_claims(corrected, view_context)
    if verified.overflow or not verified.manifest.complete or not verified.supported:
        return None
    return corrected, verified


def _correct_screen_unsupported_sentences(
    answer: str,
    view_context: Mapping[str, Any],
    result: ScreenClaimResult,
) -> tuple[str, ScreenClaimResult] | None:
    """Remove unsupported sentences when other screen claims are grounded."""

    if result.overflow or not result.manifest.complete:
        return None
    failed = tuple(claim for claim in result.claims if claim.status != "supported")
    supported = tuple(claim for claim in result.claims if claim.status == "supported")
    if not failed or not supported:
        return None
    corrected = answer
    for sentence in sorted({claim.text for claim in failed}, key=len, reverse=True):
        corrected = corrected.replace(sentence, "")
    corrected = corrected.strip()
    if not corrected:
        return None
    verified = verify_screen_claims(corrected, view_context)
    if (
        verified.overflow
        or not verified.manifest.complete
        or not verified.supported
        or not verified.claims
    ):
        return None
    return corrected, verified


def _is_korean(locale: str | None) -> bool:
    if locale is None:
        return False
    return locale.lower().split("-", 1)[0].split("_", 1)[0] == "ko"


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _topic_text(topics: tuple[str, ...], *, korean: bool) -> str:
    if not topics:
        return "\uc694\uccad\ud55c \uc8fc\uc81c" if korean else "the requested topic"
    if korean:
        return ", ".join(_KOREAN_TOPIC_LABELS.get(topic, topic) for topic in topics)
    return ", ".join(topics)


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _text(value: Any, fallback: str) -> str:
    return _optional_text(value) or fallback


__all__ = [
    "AnswerVerification",
    "VerificationStatus",
    "verify_answer",
]

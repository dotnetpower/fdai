"""Intent-specific deterministic rendering for bounded incident evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Any, Final

_TIMELINE: Final = re.compile(
    r"\b(?:timeline|chronology|first signal|through recovery)\b|타임라인|경고부터\s*복구",
    re.IGNORECASE,
)
_HYPOTHESES: Final = re.compile(
    r"\b(?:rank|causal hypotheses|incident hypotheses|possible causes|evidence strength|"
    r"supporting and contradictory evidence|counter-evidence)\b|"
    r"(?:원인\s*가설|가능한\s*원인|가설|반증|순위를\s*매|우선순위)",
    re.IGNORECASE,
)
_SIMILAR: Final = re.compile(
    r"\b(?:happened before|similar(?: resolved)? incidents?|prior recovery|earlier incident|"
    r"past incident|proven action)\b|"
    r"이전에도|이전\s*인시던트|같은 문제|이전 복구|비슷한\s*과거\s*인시던트|"
    r"유사한\s*사례|성공한\s*복구|검증된\s*조치",
    re.IGNORECASE,
)
_IMPACT: Final = re.compile(
    r"\b(?:customer|service|service-level|slo)\s+(?:and\s+)?impact\b|"
    r"\b(?:measured|observed|quantif(?:y|ied)).{0,48}impact\b|"
    r"\bincident.{0,32}(?:customer|service|service-level|slo)\s+impact\b|"
    r"(?:사용자|고객|서비스|서비스\s*수준\s*목표|SLO).{0,32}영향|"
    r"영향.{0,32}(?:사용자|고객|서비스|서비스\s*수준\s*목표|SLO)",
    re.IGNORECASE,
)
_NEXT_ACTION: Final = re.compile(
    r"\b(?:safest|highest-value)\s+next\s+step\b|"
    r"가장\s*먼저.{0,24}(?:확인|완화)|다음\s*(?:단계|조치)",
    re.IGNORECASE,
)
_CONSUMED_EVIDENCE: Final = re.compile(
    r"\b(?:evidence consumed by the conclusion|show only the evidence)\b|"
    r"결론.{0,24}(?:근거|증거).{0,12}(?:만|보여)|(?:근거|증거)만\s*보여",
    re.IGNORECASE,
)
_UNKNOWNS: Final = re.compile(
    r"\b(?:remains unknown|unresolved unknowns|evidence needed to decide)\b|"
    r"확인하지\s*못한|필요한\s*추가\s*(?:근거|증거)|미확인",
    re.IGNORECASE,
)
_DEEP_INVESTIGATION: Final = re.compile(
    r"\b(?:deep investigation|evidence phase)\b|깊이\s*조사|진행\s*단계",
    re.IGNORECASE,
)


class IncidentDossierIntent(StrEnum):
    TIMELINE = "timeline"
    HYPOTHESES = "hypotheses"
    SIMILAR = "similar"
    IMPACT = "impact"
    NEXT_ACTION = "next_action"
    CONSUMED_EVIDENCE = "consumed_evidence"
    UNKNOWNS = "unknowns"
    DEEP_INVESTIGATION = "deep_investigation"


@dataclass(frozen=True, slots=True)
class IncidentDossierRender:
    answer: str
    reason_code: str
    evidence_refs: tuple[str, ...]
    verified: bool


def classify_incident_dossier_intent(prompt: str) -> IncidentDossierIntent | None:
    if _SIMILAR.search(prompt):
        return IncidentDossierIntent.SIMILAR
    if _IMPACT.search(prompt):
        return IncidentDossierIntent.IMPACT
    if _CONSUMED_EVIDENCE.search(prompt):
        return IncidentDossierIntent.CONSUMED_EVIDENCE
    if _NEXT_ACTION.search(prompt):
        return IncidentDossierIntent.NEXT_ACTION
    if _UNKNOWNS.search(prompt):
        return IncidentDossierIntent.UNKNOWNS
    if _DEEP_INVESTIGATION.search(prompt):
        return IncidentDossierIntent.DEEP_INVESTIGATION
    if _TIMELINE.search(prompt):
        return IncidentDossierIntent.TIMELINE
    if _HYPOTHESES.search(prompt):
        return IncidentDossierIntent.HYPOTHESES
    return None


def render_incident_dossier(
    evidence: Mapping[str, Any],
    *,
    locale: str | None,
) -> IncidentDossierRender | None:
    raw_intent = evidence.get("incident_query_intent")
    if not isinstance(raw_intent, str):
        return None
    try:
        intent = IncidentDossierIntent(raw_intent)
    except (TypeError, ValueError):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    selected = evidence.get("selected_incident")
    if not isinstance(selected, Mapping):
        return _invalid_dossier_context(korean=korean)
    raw_correlation = selected.get("correlation_id")
    if (
        not isinstance(raw_correlation, str)
        or not raw_correlation.strip()
        or len(raw_correlation) > 256
        or any(character in raw_correlation for character in ("\x00", "\r", "\n"))
    ):
        return _invalid_dossier_context(korean=korean)
    correlation = raw_correlation.strip()
    if intent is IncidentDossierIntent.TIMELINE:
        return _render_timeline(evidence, correlation=correlation, korean=korean)
    if intent is IncidentDossierIntent.HYPOTHESES:
        return _render_hypotheses(evidence, correlation=correlation, korean=korean)
    if intent is IncidentDossierIntent.SIMILAR:
        return _render_similar(evidence, correlation=correlation, korean=korean)
    if intent is IncidentDossierIntent.IMPACT:
        return _render_impact(evidence, correlation=correlation, korean=korean)
    if intent is IncidentDossierIntent.NEXT_ACTION:
        return _render_next_action(evidence, correlation=correlation, korean=korean)
    if intent is IncidentDossierIntent.CONSUMED_EVIDENCE:
        return _render_consumed_evidence(evidence, correlation=correlation, korean=korean)
    if intent is IncidentDossierIntent.UNKNOWNS:
        return _render_unknowns(evidence, correlation=correlation, korean=korean)
    return _render_deep_investigation(evidence, correlation=correlation, korean=korean)


def _render_timeline(
    evidence: Mapping[str, Any],
    *,
    correlation: str,
    korean: bool,
) -> IncidentDossierRender:
    rows = [item for item in evidence.get("audit_evidence", []) if isinstance(item, Mapping)]
    rows.sort(key=lambda item: _sequence(item.get("seq")) or 0)
    refs = [f"incident:{correlation}"]
    lines: list[str] = []
    for item in rows[:20]:
        seq = _sequence(item.get("seq"))
        if seq is None:
            continue
        recorded_at = _text(item.get("recorded_at"), "unknown")
        action_kind = _text(item.get("action_kind"), "unknown")
        fields = item.get("fields")
        detail = _first_text(fields if isinstance(fields, Mapping) else {})
        suffix = f" - {detail}" if detail else ""
        lines.append(f"- {recorded_at}: {action_kind}{suffix}")
        refs.append(f"audit:{correlation}:{seq}")
    if not lines:
        answer = (
            "선택된 인시던트에 연결된 audit timeline 근거가 없습니다."
            if korean
            else "No audit timeline evidence is linked to the selected incident."
        )
        return IncidentDossierRender(answer, "incident_timeline_unavailable", (), False)
    heading = (
        f"{correlation}의 기록된 timeline입니다. Audit sequence 순서이며 "
        "인과관계를 의미하지 않습니다:"
        if korean
        else (
            f"Recorded timeline for {correlation}, ordered by audit sequence. "
            "Ordering does not establish causality:"
        )
    )
    return IncidentDossierRender(
        answer=f"{heading}\n" + "\n".join(lines),
        reason_code="incident_timeline_grounded",
        evidence_refs=tuple(dict.fromkeys(refs)),
        verified=True,
    )


def _render_hypotheses(
    evidence: Mapping[str, Any],
    *,
    correlation: str,
    korean: bool,
) -> IncidentDossierRender:
    hypotheses = [
        item for item in evidence.get("grounded_hypotheses", []) if isinstance(item, Mapping)
    ]
    refs = [f"incident:{correlation}"]
    lines: list[str] = []
    for rank, hypothesis in enumerate(hypotheses[:10], start=1):
        citation_refs = _citation_refs(hypothesis.get("citations"))
        if not citation_refs:
            continue
        cause = _text(hypothesis.get("cause"), "unknown")
        confidence = hypothesis.get("confidence")
        confidence_text = (
            f", confidence {confidence:g}"
            if isinstance(confidence, int | float)
            and not isinstance(confidence, bool)
            and isfinite(float(confidence))
            and 0 <= confidence <= 1
            else ""
        )
        lines.append(f"{rank}. {cause}{confidence_text}")
        refs.extend(citation_refs)
    if not lines:
        answer = (
            "Citation을 갖춘 grounded causal hypothesis가 없어 순위를 만들지 않았습니다."
            if korean
            else "No citation-grounded causal hypothesis is available, so no ranking was produced."
        )
        return IncidentDossierRender(answer, "incident_hypotheses_unavailable", (), False)
    limitation = (
        "별도로 구조화된 반증 근거는 bounded RCA projection에 기록되어 있지 않습니다."
        if korean
        else (
            "No separately structured contradictory evidence is recorded in the bounded "
            "RCA projection."
        )
    )
    heading = (
        f"{correlation}의 grounded causal hypothesis 순위입니다:"
        if korean
        else f"Ranked grounded causal hypotheses for {correlation}:"
    )
    return IncidentDossierRender(
        answer=f"{heading}\n" + "\n".join(lines) + f"\n{limitation}",
        reason_code="incident_hypotheses_grounded",
        evidence_refs=tuple(dict.fromkeys(refs)),
        verified=True,
    )


def _render_similar(
    evidence: Mapping[str, Any],
    *,
    correlation: str,
    korean: bool,
) -> IncidentDossierRender:
    status = evidence.get("similar_incident_status")
    if status == "unavailable":
        answer = (
            "이전 인시던트 비교 근거를 조회할 수 없어 같은 문제의 복구 이력을 확인하지 않았습니다."
            if korean
            else (
                "Prior-incident comparison evidence is unavailable, so matching recovery "
                "history was not confirmed."
            )
        )
        return IncidentDossierRender(
            answer,
            "similar_incident_lookup_unavailable",
            (),
            False,
        )
    incidents = [
        item for item in evidence.get("similar_incidents", []) if isinstance(item, Mapping)
    ]
    if not incidents:
        answer = (
            "같은 domain signal과 성공한 복구 receipt를 가진 이전 인시던트를 찾지 못했습니다."
            if korean
            else (
                "No prior incident with a matching domain signal and successful recovery "
                "receipt was found."
            )
        )
        return IncidentDossierRender(
            answer,
            "similar_incident_unavailable",
            (f"incident:{correlation}",),
            True,
        )
    lines: list[str] = []
    refs = [f"incident:{correlation}"]
    for item in incidents[:5]:
        candidate = _text(item.get("correlation_id"), "unknown")
        title = _text(item.get("title"), "untitled")
        raw_recovery = item.get("recovery")
        recovery = raw_recovery if isinstance(raw_recovery, Mapping) else {}
        action_kind = _text(recovery.get("action_kind"), "unknown")
        outcome = _text(recovery.get("outcome"), "unknown")
        signals = item.get("matching_domain_signals")
        signal_text = (
            ", ".join(value for value in signals if isinstance(value, str))
            if isinstance(signals, list)
            else "unknown"
        )
        lines.append(
            f"- {candidate}: {title}, shared signals {signal_text}, recovery {action_kind}, "
            f"outcome {outcome}"
        )
        refs.append(f"incident:{candidate}")
        recovery_ref = recovery.get("evidence_ref")
        if isinstance(recovery_ref, str) and _valid_audit_ref(recovery_ref, correlation=candidate):
            refs.append(recovery_ref)
    heading = (
        "같은 domain signal과 성공한 복구 receipt를 가진 이전 인시던트입니다:"
        if korean
        else "Prior incidents with a matching domain signal and successful recovery receipt:"
    )
    return IncidentDossierRender(
        f"{heading}\n" + "\n".join(lines),
        "similar_incident_grounded",
        tuple(dict.fromkeys(refs)),
        True,
    )


def _render_impact(
    evidence: Mapping[str, Any],
    *,
    correlation: str,
    korean: bool,
) -> IncidentDossierRender:
    observations = _audit_field_observations(
        evidence,
        ("affected_count", "customer_impact", "service_impact", "slo_impact", "impact"),
        correlation=correlation,
    )
    if not observations:
        answer = (
            "선택된 인시던트의 bounded audit evidence에 사용자 영향 또는 SLO 측정값이 없어 "
            "영향을 정량화하지 않았습니다."
            if korean
            else (
                "The selected incident's bounded audit evidence contains no customer-impact or "
                "SLO measurement, so impact was not quantified."
            )
        )
        return IncidentDossierRender(
            answer,
            "incident_impact_unavailable",
            (f"incident:{correlation}",),
            True,
        )
    lines = [f"- {key}: {value}" for key, value, _ref in observations]
    refs = [f"incident:{correlation}", *(ref for _key, _value, ref in observations)]
    heading = "기록된 영향 근거:" if korean else "Recorded impact evidence:"
    return IncidentDossierRender(
        f"{heading}\n" + "\n".join(lines),
        "incident_impact_grounded",
        tuple(dict.fromkeys(refs)),
        True,
    )


def _render_next_action(
    evidence: Mapping[str, Any],
    *,
    correlation: str,
    korean: bool,
) -> IncidentDossierRender:
    raw_plan = evidence.get("response_plan")
    plan = raw_plan if isinstance(raw_plan, Mapping) else {}
    decision = _text(plan.get("decision"), "")
    if not decision:
        answer = (
            "검증된 response decision이 없어 가장 우선할 다음 조치를 만들지 않았습니다."
            if korean
            else (
                "No verified response decision is recorded, so no highest-priority next action "
                "was produced."
            )
        )
        return IncidentDossierRender(
            answer,
            "incident_next_action_unavailable",
            (f"incident:{correlation}",),
            True,
        )
    verdict = _text(plan.get("verdict"), "unknown")
    mode = _text(plan.get("mode"), "unknown")
    answer = (
        f"기록된 다음 decision은 {decision}입니다. Verdict는 {verdict}, mode는 "
        f"{mode}입니다. 이 답변은 실행 권한을 부여하지 않습니다."
        if korean
        else (
            f"The recorded next decision is {decision}. Verdict: {verdict}; "
            f"mode: {mode}. This answer does not grant execution authority."
        )
    )
    return IncidentDossierRender(
        answer,
        "incident_next_action_grounded",
        (f"incident:{correlation}",),
        True,
    )


def _render_consumed_evidence(
    evidence: Mapping[str, Any],
    *,
    correlation: str,
    korean: bool,
) -> IncidentDossierRender:
    hypotheses = [
        item for item in evidence.get("grounded_hypotheses", []) if isinstance(item, Mapping)
    ]
    refs: list[str] = [f"incident:{correlation}"]
    for hypothesis in hypotheses[:1]:
        refs.extend(_citation_refs(hypothesis.get("citations")))
    if len(refs) == 1:
        answer = (
            "결론이 사용한 citation evidence가 기록되어 있지 않아 근거 목록을 검증하지 않았습니다."
            if korean
            else (
                "No citation evidence consumed by the conclusion is recorded, so an evidence "
                "list was not verified."
            )
        )
        return IncidentDossierRender(
            answer,
            "incident_consumed_evidence_unavailable",
            (),
            False,
        )
    refs = list(dict.fromkeys(refs))
    heading = (
        "결론에 사용된 근거 reference:"
        if korean
        else "Evidence references consumed by the conclusion:"
    )
    return IncidentDossierRender(
        f"{heading}\n" + "\n".join(f"- {ref}" for ref in refs),
        "incident_consumed_evidence_grounded",
        tuple(refs),
        True,
    )


def _render_unknowns(
    evidence: Mapping[str, Any],
    *,
    correlation: str,
    korean: bool,
) -> IncidentDossierRender:
    unknowns: list[tuple[str, str]] = []
    if not evidence.get("grounded_hypotheses"):
        unknowns.append(("citation-grounded root cause", "citation이 있는 grounded root cause"))
    if not _audit_field_observations(
        evidence,
        ("affected_count", "customer_impact", "service_impact", "slo_impact", "impact"),
        correlation=correlation,
    ):
        unknowns.append(("customer and SLO impact measurements", "사용자 및 SLO 영향 측정값"))
    raw_plan = evidence.get("response_plan")
    if not isinstance(raw_plan, Mapping) or not raw_plan.get("decision"):
        unknowns.append(("verified response decision", "검증된 response decision"))
    if evidence.get("ungrounded_hypothesis_count"):
        unknowns.append(("citations for ungrounded hypotheses", "ungrounded hypothesis의 citation"))
    if not unknowns:
        unknowns.append(
            (
                "no additional structured gap is recorded in this bounded projection",
                "이 bounded projection에는 추가 structured gap이 기록되어 있지 않음",
            )
        )
    heading = "아직 확인되지 않은 항목:" if korean else "Unresolved evidence gaps:"
    return IncidentDossierRender(
        f"{heading}\n"
        + "\n".join(f"- {korean_text if korean else english}" for english, korean_text in unknowns),
        "incident_unknowns_grounded",
        (f"incident:{correlation}",),
        True,
    )


def _render_deep_investigation(
    evidence: Mapping[str, Any],
    *,
    correlation: str,
    korean: bool,
) -> IncidentDossierRender:
    phases = [
        item
        for item in evidence.get("audit_evidence", [])
        if isinstance(item, Mapping)
        and _text(item.get("action_kind"), "").startswith("investigation.")
        and _has_investigation_receipt(item)
        and _sequence(item.get("seq")) is not None
    ]
    if not phases:
        answer = (
            "새 deep investigation을 시작했다는 durable receipt가 없어 시작되었다고 보고하지 "
            "않습니다. 선택된 incident, bounded scope 및 investigation run receipt가 필요합니다."
            if korean
            else (
                "No durable receipt proves that a new deep investigation started. The answer "
                "therefore does not claim one started; a selected incident, bounded scope, and "
                "investigation run receipt are required."
            )
        )
        return IncidentDossierRender(
            answer,
            "deep_investigation_receipt_required",
            (),
            False,
        )
    lines = [
        f"- {_text(item.get('recorded_at'), 'unknown')}: "
        f"{_text(item.get('action_kind'), 'unknown')}"
        for item in phases[:20]
    ]
    refs = tuple(
        f"audit:{correlation}:{sequence}"
        for item in phases[:20]
        if (sequence := _sequence(item.get("seq"))) is not None
    )
    heading = "기록된 investigation phase:" if korean else "Recorded investigation phases:"
    return IncidentDossierRender(
        f"{heading}\n" + "\n".join(lines),
        "deep_investigation_progress_grounded",
        refs,
        True,
    )


def _audit_field_observations(
    evidence: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    correlation: str,
) -> list[tuple[str, object, str]]:
    observations: list[tuple[str, object, str]] = []
    for item in evidence.get("audit_evidence", []):
        if not isinstance(item, Mapping):
            continue
        fields = item.get("fields")
        if not isinstance(fields, Mapping):
            continue
        seq = _sequence(item.get("seq"))
        if seq is None:
            continue
        for key in keys:
            value = fields.get(key)
            if key == "affected_count":
                valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
                normalized = value
            elif isinstance(value, str):
                normalized = _text(value, "")
                valid = bool(normalized)
            else:
                valid = (
                    isinstance(value, int | float)
                    and not isinstance(value, bool)
                    and isfinite(float(value))
                )
                normalized = value
            if valid:
                observations.append((key, normalized, f"audit:{correlation}:{seq}"))
    return observations


def _has_investigation_receipt(item: Mapping[str, Any]) -> bool:
    fields = item.get("fields")
    if not isinstance(fields, Mapping):
        return False
    return any(
        isinstance(fields.get(key), str) and bool(str(fields[key]).strip())
        for key in ("run_id", "investigation_id")
    )


def _first_text(fields: Mapping[str, Any]) -> str | None:
    for key in ("summary", "detail", "reason", "outcome", "decision", "status"):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            return _text(value, "") or None
    return None


def _text(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    collapsed = " ".join(value.split())[:512]
    if not collapsed:
        return fallback
    return re.sub(r"([\\`*[\]<>#|])", r"\\\1", collapsed)


def _sequence(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _citation_refs(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    refs: list[str] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("kind")
        ref = item.get("ref")
        if (
            not isinstance(kind, str)
            or not kind.strip()
            or len(kind) > 64
            or not isinstance(ref, str)
            or not ref.strip()
            or len(ref) > 1_024
            or any(character in kind or character in ref for character in ("\x00", "\r", "\n"))
        ):
            continue
        refs.append(f"{kind.strip()}:{ref.strip()}")
    return tuple(dict.fromkeys(refs))


def _invalid_dossier_context(*, korean: bool) -> IncidentDossierRender:
    answer = (
        "선택된 incident context가 유효하지 않아 dossier answer를 검증하지 않았습니다."
        if korean
        else "The selected incident context is invalid, so no dossier answer was verified."
    )
    return IncidentDossierRender(answer, "incident_dossier_context_invalid", (), False)


def _valid_audit_ref(raw: object, *, correlation: str) -> bool:
    return bool(
        isinstance(raw, str)
        and len(raw) <= 512
        and re.fullmatch(rf"audit:{re.escape(correlation)}:[1-9][0-9]*", raw)
    )


__all__ = [
    "IncidentDossierIntent",
    "IncidentDossierRender",
    "classify_incident_dossier_intent",
    "render_incident_dossier",
]

"""Give a repaired form's mentions back the labels of the proposal it repairs.

A repair returns the whole form again, and a model may number its mentions afresh,
for example in the order their words appear. A mention id is a label, not meaning,
so a repair is compared with the proposal only after each earlier mention's id is
given back to the one repaired mention that can be it: the same form and domain over
a span that holds the earlier span. The renaming is a bijection applied to every
reference, so the repaired form states exactly what it stated before. When any
earlier mention has no single such counterpart, the labels stay as the model wrote
them and the repair comparison decides. A mention the repair was asked to split has
no single counterpart by design, so it is left out of the matching.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .semantic_reasoning_form import MentionDomain, SemanticQuestionForm

_MAX_MENTION_NUMBER = 99
_STATE_LABEL_NOUNS = frozenset(
    {
        "성능",
        "성능이",
        "성능은",
        "상태",
        "상태가",
        "상태는",
        "헬스",
        "헬스가",
        "가동",
        "가동이",
        "동작",
        "동작이",
        "작동",
        "작동이",
        "기능",
        "기능이",
        "전원",
        "전원이",
        "서비스",
        "서비스가",
        "연결",
        "연결이",
        "품질",
        "품질이",
    }
)
_CHANGE_HISTORY_PHRASES = (
    "상태가 변경된",
    "상태 변경된",
    "상태가 바뀐",
    "상태 바뀐",
    "최근 변경된",
    "최근에 변경된",
    "삭제한",
    "삭제된",
    "지운",
    "제거된",
    "제거한",
    "생성된",
    "생성한",
    "변경된",
    "바뀐",
)
_CHANGE_HISTORY_COMPACT = frozenset(p.replace(" ", "") for p in _CHANGE_HISTORY_PHRASES)
_INVENTORY_WORDS = frozenset(
    {
        "inventory",
        "the inventory",
        "in the inventory",
        "in inventory",
        "our inventory",
        "current inventory",
        "인벤토리",
        "인벤토리에",
        "인벤토리에서",
        "인벤토리내",
        "전체 인벤토리",
    }
)
_HEALTH_PHRASES = (
    "문제가 있는",
    "문제 있는",
    "문제있는",
    "이상이 있는",
    "이상 있는",
    "이상있는",
    "장애가 있는",
    "장애 있는",
    "비정상",
    "불량인",
    "불량",
    "사용 불가",
    "저하된",
)
_TRAILING_REQUEST_CUES = (
    "알려줘",
    "보여줘",
    "찾아줘",
    "출력해줘",
    "있어?",
    "있나요?",
    "뭔가요?",
    "뭐야?",
)


def normalize_raw_proposal_payload(payload: dict[str, Any], utterance: str) -> None:
    """Normalize structural proposer mistakes before Pydantic contract validation."""

    from .semantic_reasoning_selection import (
        _DOMAIN_SEED_INDEX,
        _match_seed_or_typo,
        _normalize_concept_term,
    )

    mentions = payload.get("mentions")
    goals = payload.get("goals")
    if not isinstance(mentions, list) or not isinstance(goals, list):
        return
    obj_seeds = _DOMAIN_SEED_INDEX.get(MentionDomain.OBJECT_TYPE, {})
    retyped: set[str] = set()
    for item in mentions:
        if (
            isinstance(item, dict)
            and item.get("form") == "concept"
            and item.get("domain") == "instance"
        ):
            span = item.get("span")
            txt = (
                utterance[span.get("start", 0) : span.get("end", 0)]
                if isinstance(span, dict)
                else ""
            )
            matched_obj = _match_seed_or_typo(_normalize_concept_term(txt), obj_seeds)
            item["domain"] = (
                "object_type"
                if matched_obj is not None and matched_obj != "object:Resource"
                else "resource_type"
            )
            if isinstance(item.get("id"), str):
                retyped.add(item["id"])
    by_id = {
        m.get("id"): m for m in mentions if isinstance(m, dict) and isinstance(m.get("id"), str)
    }
    for goal in goals:
        if isinstance(goal, dict) and goal.get("level") != "schema":
            subj = by_id.get(goal.get("subject"))
            if (
                goal.get("subject_scope") == "anchor"
                and isinstance(subj, dict)
                and subj.get("form") == "concept"
                and subj.get("domain") in {"resource_type", "resource_class", "object_type"}
            ):
                goal["subject_scope"] = "collection"
            for f_item in goal.get("filters") or ():
                if (
                    isinstance(f_item, dict)
                    and f_item.get("role") == "scope"
                    and f_item.get("mention") in retyped
                ):
                    f_item["role"] = "type"
    _rescue_unsupported_and_history(payload, mentions, goals, utterance)
    _normalize_state_and_health_proposals(mentions, goals, utterance)


def _rescue_unsupported_and_history(
    payload: dict[str, Any], mentions: list[Any], goals: list[Any], utterance: str
) -> None:
    import re

    unsupported = payload.get("unsupported_constraints")
    context = payload.setdefault("context", [])
    promoted_history_cue: dict[str, int] | None = None
    if isinstance(unsupported, list) and isinstance(context, list):
        kept_unsup = []
        for span in unsupported:
            if not isinstance(span, dict):
                continue
            raw_txt = utterance[span.get("start", 0) : span.get("end", 0)].strip(" .,?!").casefold()
            if raw_txt in _INVENTORY_WORDS:
                context.append(span)
            elif "".join(raw_txt.split()) in _CHANGE_HISTORY_COMPACT:
                promoted_history_cue = span
            else:
                kept_unsup.append(span)
        payload["unsupported_constraints"] = kept_unsup

    by_id = {
        m.get("id"): m for m in mentions if isinstance(m, dict) and isinstance(m.get("id"), str)
    }
    dropped: set[str] = set()
    for goal in goals:
        if not isinstance(goal, dict) or not isinstance(goal.get("filters"), list):
            continue
        kept_scope_filters = []
        for f_item in goal["filters"]:
            m_id = f_item.get("mention") if isinstance(f_item, dict) else None
            m_obj = by_id.get(m_id) if isinstance(m_id, str) else None
            m_span = m_obj.get("span") if isinstance(m_obj, dict) else None
            m_txt = (
                utterance[m_span.get("start", 0) : m_span.get("end", 0)].strip(" .,?!").casefold()
                if isinstance(m_span, dict)
                else ""
            )
            if (
                isinstance(f_item, dict)
                and m_txt in _INVENTORY_WORDS
                and isinstance(m_id, str)
                and isinstance(context, list)
            ):
                if isinstance(m_span, dict):
                    context.append(m_span)
                if isinstance(f_item.get("cue"), dict):
                    context.append(f_item["cue"])
                dropped.add(m_id)
            else:
                kept_scope_filters.append(f_item)
        goal["filters"] = kept_scope_filters

    referenced: set[str] = set()
    for goal in goals:
        if not isinstance(goal, dict):
            continue
        for key in ("subject", "counterpart"):
            if isinstance(goal.get(key), str):
                referenced.add(goal[key])
        for f_item in goal.get("filters") or ():
            if isinstance(f_item, dict) and isinstance(f_item.get("mention"), str):
                referenced.add(f_item["mention"])
        rel = goal.get("relation")
        if isinstance(rel, dict):
            for key in ("anchor", "counterpart"):
                if isinstance(rel.get(key), str):
                    referenced.add(rel[key])
        meas = goal.get("measure")
        if isinstance(meas, dict) and isinstance(meas.get("mention"), str):
            referenced.add(meas["mention"])

    unused_limits: list[tuple[str, int, dict[str, int]]] = []
    for m in mentions:
        if not isinstance(m, dict) or m.get("id") in referenced or m.get("id") in dropped:
            continue
        span = m.get("span")
        if not isinstance(span, dict):
            continue
        raw_txt = utterance[span.get("start", 0) : span.get("end", 0)].strip()
        digits = "".join(ch for ch in raw_txt if ch.isdigit())
        rest = "".join(ch for ch in raw_txt if not ch.isdigit()).strip()
        if digits and rest in {"개", "건", "개를", "건을", "개만"}:
            unused_limits.append((str(m["id"]), int(digits), span))

    for goal in goals:
        if not isinstance(goal, dict):
            continue
        measure = goal.get("measure")
        if (
            goal.get("operation") == "select"
            and isinstance(measure, dict)
            and measure.get("kind") in {"change", "event"}
        ):
            goal["operation"] = "history"
        if (
            goal.get("operation") == "history"
            and goal.get("subject_scope") == "collection"
            and isinstance(measure, dict)
            and measure.get("kind") == "state"
        ):
            measure["kind"] = "change"
        filters = goal.get("filters")
        if goal.get("operation") in {"select", "history"} and isinstance(filters, list):
            kept_filters = []
            for f_item in filters:
                m_id = f_item.get("mention") if isinstance(f_item, dict) else None
                m_obj = by_id.get(m_id) if isinstance(m_id, str) else None
                m_span = m_obj.get("span") if isinstance(m_obj, dict) else None
                compact = (
                    "".join(
                        utterance[m_span.get("start", 0) : m_span.get("end", 0)].casefold().split()
                    )
                    if isinstance(m_span, dict)
                    else ""
                )
                if (
                    isinstance(f_item, dict)
                    and f_item.get("role") in {"state", "health"}
                    and compact in _CHANGE_HISTORY_COMPACT
                    and isinstance(m_id, str)
                ):
                    promoted_history_cue = (
                        f_item.get("cue") if isinstance(f_item.get("cue"), dict) else m_span
                    )
                    dropped.add(m_id)
                else:
                    kept_filters.append(f_item)
            goal["filters"] = kept_filters
        if (
            promoted_history_cue is None
            and goal.get("subject_scope") == "collection"
            and not goal.get("filters")
        ):
            for phrase in _CHANGE_HISTORY_PHRASES[:11]:
                idx = utterance.find(phrase)
                if idx >= 0:
                    promoted_history_cue = {"start": idx, "end": idx + len(phrase)}
                    break
        if (promoted_history_cue is not None or goal.get("operation") == "history") and goal.get(
            "subject_scope"
        ) == "collection":
            goal["operation"] = "history"
            goal["confidence"] = max(float(goal.get("confidence", 0.85)), 0.85)
            payload["alternatives"] = []
            if not isinstance(goal.get("measure"), dict):
                goal["measure"] = {
                    "kind": "change",
                    "group_by": "none",
                    "mention": None,
                    "order": None,
                    "cue": promoted_history_cue,
                }
            elif goal["measure"].get("cue") is None and promoted_history_cue is not None:
                goal["measure"]["cue"] = promoted_history_cue
            rec_idx = utterance.find("최근")
            time_obj = goal.get("time")
            if rec_idx >= 0 and isinstance(time_obj, dict) and time_obj.get("cue") is None:
                time_obj.update(
                    {
                        "kind": "unspecified",
                        "value": None,
                        "windows": [],
                        "cue": {"start": rec_idx, "end": rec_idx + 2},
                    }
                )
            cue_obj = goal.get("cue")
            if (
                isinstance(cue_obj, dict)
                and cue_obj.get("start") == 0
                and cue_obj.get("end") == len(utterance)
            ):
                for tc in _TRAILING_REQUEST_CUES:
                    if utterance.endswith(tc):
                        goal["cue"] = {"start": len(utterance) - len(tc), "end": len(utterance)}
                        break
            if len(goals) == 1:
                goal["filters"] = []
                for m in mentions:
                    m_id = m.get("id") if isinstance(m, dict) else None
                    if (
                        isinstance(m_id, str)
                        and m_id != goal.get("subject")
                        and m_id not in {u[0] for u in unused_limits}
                    ):
                        dropped.add(m_id)
                        if isinstance(m.get("span"), dict):
                            if goal["measure"].get("cue") is None:
                                goal["measure"]["cue"] = m["span"]
                            elif isinstance(context, list):
                                context.append(m["span"])
        if (
            goal.get("operation") in {"history", "rank"}
            and isinstance(goal.get("measure"), dict)
            and goal["measure"].get("order") is None
        ):
            if len(unused_limits) == 1:
                lim_id, lim_val, lim_span = unused_limits[0]
                goal["measure"]["order"] = {
                    "direction": "descending",
                    "limit": lim_val,
                    "limit_span": lim_span,
                    "cue": None,
                }
                dropped.add(lim_id)
            else:
                m_cnt = re.search(r"(\d+)\s*(?:개|건)(?:를|을|만)?", utterance)
                if m_cnt:
                    d_end = m_cnt.start(1) + len(m_cnt.group(1))
                    goal["measure"]["order"] = {
                        "direction": "descending",
                        "limit": int(m_cnt.group(1)),
                        "limit_span": {"start": m_cnt.start(1), "end": d_end},
                        "cue": {"start": m_cnt.start(0), "end": m_cnt.end(0)},
                    }
    if dropped:
        mentions[:] = [m for m in mentions if not (isinstance(m, dict) and m.get("id") in dropped)]


def _normalize_state_and_health_proposals(
    mentions: list[Any], goals: list[Any], utterance: str
) -> None:
    from .semantic_reasoning_selection import (
        _DOMAIN_SEED_INDEX,
        _match_seed_or_typo,
        _normalize_concept_term,
    )

    state_seeds = _DOMAIN_SEED_INDEX.get(MentionDomain.STATE, {})
    metric_seeds = _DOMAIN_SEED_INDEX.get(MentionDomain.METRIC, {})
    by_id = {
        m.get("id"): m for m in mentions if isinstance(m, dict) and isinstance(m.get("id"), str)
    }
    dropped: set[str] = set()
    for goal in goals:
        if not isinstance(goal, dict):
            continue
        for item in goal.get("filters") or () if isinstance(goal.get("filters"), list) else ():
            if (
                not isinstance(item, dict)
                or item.get("role") != "metric"
                or item.get("comparison") is not None
            ):
                continue
            m_id = item.get("mention")
            m_obj = by_id.get(m_id) if isinstance(m_id, str) else None
            m_span = m_obj.get("span") if isinstance(m_obj, dict) else None
            if not isinstance(m_span, dict) or m_obj is None:
                continue
            q_span = (
                item.get("qualifier_span") if isinstance(item.get("qualifier_span"), dict) else None
            )
            c_start, c_end = m_span.get("start", 0), m_span.get("end", 0)
            if q_span is not None:
                c_start, c_end = min(c_start, q_span["start"]), max(c_end, q_span["end"])
            if isinstance(item.get("cue"), dict):
                c_start, c_end = min(c_start, item["cue"]["start"]), max(c_end, item["cue"]["end"])
            m_text = utterance[m_span.get("start", 0) : m_span.get("end", 0)].strip().casefold()
            combined_norm = _normalize_concept_term(utterance[c_start:c_end])
            is_state_term = (
                m_obj.get("domain") in {"state", "health"}
                or m_text in _STATE_LABEL_NOUNS
                or (
                    _match_seed_or_typo(combined_norm, state_seeds) is not None
                    and _match_seed_or_typo(combined_norm, metric_seeds) is None
                )
            )
            if not is_state_term:
                continue
            companion = next(
                (
                    other
                    for other in mentions
                    if isinstance(other, dict)
                    and other.get("id") != m_id
                    and other.get("domain") in {"state", "health"}
                    and isinstance(other.get("span"), dict)
                    and c_start <= other["span"]["start"]
                    and other["span"]["end"] <= c_end
                ),
                None,
            )
            if companion is not None and isinstance(m_id, str):
                companion["span"] = {"start": c_start, "end": c_end}
                item["role"] = companion.get("domain", "state")
                item["mention"] = companion["id"]
                item["qualifier"] = None
                item["qualifier_span"] = None
                item["cue"] = None
                dropped.add(m_id)
            else:
                target_domain = (
                    m_obj["domain"] if m_obj.get("domain") in {"state", "health"} else "state"
                )
                m_obj["form"] = "value"
                m_obj["domain"] = target_domain
                m_obj["span"] = {"start": c_start, "end": c_end}
                item["role"] = target_domain
                item["qualifier"] = None
                item["qualifier_span"] = None
                item["cue"] = None
                for other in mentions:
                    if (
                        isinstance(other, dict)
                        and other.get("id") not in {m_id, goal.get("subject")}
                        and isinstance(other.get("span"), dict)
                        and c_start < other["span"]["end"]
                        and other["span"]["start"] < c_end
                    ):
                        dropped.add(str(other["id"]))
    if dropped:
        mentions[:] = [m for m in mentions if not (isinstance(m, dict) and m.get("id") in dropped)]
    _normalize_resource_health_proposal(mentions, goals, utterance)


def _normalize_resource_health_proposal(
    mentions: list[Any], goals: list[Any], utterance: str
) -> None:
    rh_idx = utterance.casefold().find("resource health")
    if rh_idx < 0 or len(goals) != 1 or not isinstance(goals[0], dict):
        return
    rh_span = {"start": rh_idx, "end": rh_idx + 15}
    goal = goals[0]
    by_id = {
        m.get("id"): m for m in mentions if isinstance(m, dict) and isinstance(m.get("id"), str)
    }
    measure = goal.get("measure")
    filters = goal.get("filters")
    if isinstance(measure, dict) and measure.get("kind") == "health" and isinstance(filters, list):
        for f_item in filters:
            if isinstance(f_item, dict) and f_item.get("role") in {"state", "health"}:
                f_item["role"] = "health"
                if f_item.get("cue") is None:
                    f_item["cue"] = measure.get("cue") or rh_span
                m_obj = by_id.get(f_item.get("mention"))
                if isinstance(m_obj, dict):
                    m_obj["domain"] = "health"
                    m_obj["form"] = "concept"
                goal["measure"] = None
    res_idx = utterance.find("리소스", rh_span["end"])
    h_span = None
    for hp in _HEALTH_PHRASES:
        idx = utterance.find(hp, rh_span["end"])
        if idx >= 0:
            h_span = {"start": idx, "end": idx + len(hp)}
            break
    if res_idx >= 0 and h_span is not None:
        mentions[:] = [
            {
                "id": "m1",
                "form": "concept",
                "domain": "resource_type",
                "span": {"start": res_idx, "end": res_idx + 3},
                "qualifier": None,
                "position": None,
            },
            {
                "id": "m2",
                "form": "concept",
                "domain": "health",
                "span": h_span,
                "qualifier": None,
                "position": None,
            },
        ]
        goal["subject"] = "m1"
        goal["subject_scope"] = "collection"
        goal["operation"] = "select"
        goal["filters"] = [
            {
                "role": "health",
                "mention": "m2",
                "cue": rh_span,
                "comparison": None,
                "qualifier": None,
                "qualifier_span": None,
            }
        ]
        goal["measure"] = None
        goal["confidence"] = max(float(goal.get("confidence", 0.85)), 0.85)


def relabel_mentions(
    previous: SemanticQuestionForm,
    repaired: SemanticQuestionForm,
    *,
    split: frozenset[str] = frozenset(),
) -> SemanticQuestionForm:
    """Return ``repaired`` with each earlier mention's id restored, when unambiguous.

    ``split`` names earlier mentions the repair replaces with narrower parts; their ids
    are never restored onto a part, so a part keeps the label the model gave it unless
    that label belongs to a restored mention.
    """

    restored: dict[str, str] = {}
    for before in previous.mentions:
        if before.id in split:
            continue
        matches = [
            after.id
            for after in repaired.mentions
            if (after.form, after.domain) == (before.form, before.domain)
            and after.span.start <= before.span.start
            and before.span.end <= after.span.end
        ]
        if len(matches) != 1 or matches[0] in restored:
            return repaired
        restored[matches[0]] = before.id
    if all(old == new for old, new in restored.items()):
        return repaired
    renames = _renames(repaired, restored)
    payload = repaired.model_dump(mode="json")
    for mention in payload["mentions"]:
        mention["id"] = renames[mention["id"]]
        if mention.get("qualifier") is not None:
            _rename(mention["qualifier"], "mention", renames)
    for goal in payload["goals"]:
        _rename(goal, "subject", renames)
        for item in goal.get("filters") or ():
            _rename(item, "mention", renames)
        if goal.get("relation") is not None:
            _rename(goal["relation"], "anchor", renames)
            _rename(goal["relation"], "counterpart", renames)
        if goal.get("measure") is not None:
            _rename(goal["measure"], "mention", renames)
    try:
        return SemanticQuestionForm.model_validate(payload)
    except ValidationError:
        # A longer restored label can cross the form's byte budget; the comparison decides.
        return repaired


def _renames(repaired: SemanticQuestionForm, restored: dict[str, str]) -> dict[str, str]:
    """Extend the restored labels to a bijection over every repaired mention."""

    taken = set(restored.values())
    kept = {
        mention.id
        for mention in repaired.mentions
        if mention.id not in restored and mention.id not in taken
    }
    free = (
        label
        for label in (f"m{number}" for number in range(1, _MAX_MENTION_NUMBER + 1))
        if label not in taken and label not in kept
    )
    renames = dict(restored)
    for mention in repaired.mentions:
        if mention.id in renames:
            continue
        if mention.id in kept:
            renames[mention.id] = mention.id
        else:
            candidate = next(free, None)
            if candidate is None:
                raise ValueError("mention relabel budget exhausted")
            renames[mention.id] = candidate
    return renames


def _rename(holder: dict[str, Any], key: str, renames: dict[str, str]) -> None:
    value = holder.get(key)
    if isinstance(value, str):
        holder[key] = renames.get(value, value)


__all__ = ["normalize_raw_proposal_payload", "relabel_mentions"]

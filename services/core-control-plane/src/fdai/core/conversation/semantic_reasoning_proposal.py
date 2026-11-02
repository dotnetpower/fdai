"""Bind model-quoted text to exact utterance spans before form validation.

Models quote the exact words they rely on; they do not count characters. Core
locates each quoted phrase verbatim, as the given occurrence, and replaces it
with a half-open span. A quote that does not occur verbatim fails closed. This
validates the model's output and never infers meaning from the utterance.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from .semantic_reasoning_form import SemanticQuestionForm

MAX_QUOTE_CHARS = 512
MAX_OCCURRENCE = 16
RequestKind = Literal["direct_read", "action", "quoted", "hypothetical", "unclear"]
REQUEST_KINDS = ("direct_read", "action", "quoted", "hypothetical", "unclear")
_QUOTED_SPAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "occurrence"],
    "properties": {
        "text": {"type": "string", "description": "Exact words copied from the utterance."},
        "occurrence": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_OCCURRENCE,
            "description": "Which verbatim occurrence of text, counting from 1.",
        },
    },
}


class FormInputHeldError(RuntimeError):
    """A proposal call was refused before transmission; ``reason`` is a closed code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class FormResolution:
    """A validated form, or typed reasons plus code-authored notes for one repair."""

    form: SemanticQuestionForm | None
    reasons: tuple[str, ...]
    notes: tuple[str, ...] = ()
    request_kind: RequestKind | None = None


_PROPOSAL_SCHEMA_TEMPLATE: dict[str, Any] | None = None


def question_form_proposal_schema() -> dict[str, Any]:
    """Return the model-facing schema, with quoted spans in place of offsets."""

    global _PROPOSAL_SCHEMA_TEMPLATE
    if _PROPOSAL_SCHEMA_TEMPLATE is None:
        schema = copy.deepcopy(SemanticQuestionForm.model_json_schema())
        definitions = schema.get("$defs", {})
        if "SourceSpan" not in definitions:
            raise ValueError("question form schema has no SourceSpan definition")
        definitions["SourceSpan"] = copy.deepcopy(_QUOTED_SPAN_SCHEMA)
        schema["properties"]["request_kind"] = {
            "type": ["string", "null"],
            "enum": [*REQUEST_KINDS, None],
            "description": "Classify the actual request, not a quoted request or imagined action.",
        }
        schema["required"] = [*schema.get("required", ()), "request_kind"]
        _PROPOSAL_SCHEMA_TEMPLATE = schema
    return copy.deepcopy(_PROPOSAL_SCHEMA_TEMPLATE)


def resolve_question_form(raw: Mapping[str, Any], *, utterance: str) -> FormResolution:
    """Return a validated form whose spans point at the quoted utterance text."""

    try:
        payload = copy.deepcopy(dict(raw))
    except (TypeError, ValueError):
        return FormResolution(None, ("form_payload_invalid",))
    failures: list[str] = []
    notes: list[str] = []
    request_kind = payload.pop("request_kind", None)
    if request_kind is not None and request_kind not in REQUEST_KINDS:
        return FormResolution(None, ("request_kind_invalid",))
    mentions = payload.get("mentions")
    goals = payload.get("goals")
    if not isinstance(mentions, list) or not isinstance(goals, list):
        return FormResolution(
            None, ("form_payload_invalid",), ("form: mentions and goals MUST be lists",)
        )
    for index, mention in enumerate(mentions):
        if isinstance(mention, dict):
            _bind(mention, "span", utterance, failures, notes, f"mentions.{index}.span")
    if not failures:
        separate_mentions(mentions, utterance)
    for index, goal in enumerate(goals):
        if not isinstance(goal, dict):
            continue
        _bind(goal, "cue", utterance, failures, notes, f"goals.{index}.cue")
        filters = goal.get("filters")
        for position, item in enumerate(filters if isinstance(filters, list) else ()):
            if isinstance(item, dict):
                path = f"goals.{index}.filters.{position}.cue"
                _bind(item, "cue", utterance, failures, notes, path, required=False)
                qualifier_path = f"goals.{index}.filters.{position}.qualifier_span"
                _bind(
                    item,
                    "qualifier_span",
                    utterance,
                    failures,
                    notes,
                    qualifier_path,
                    required=False,
                )
                comparison = item.get("comparison")
                if isinstance(comparison, dict):
                    base = f"goals.{index}.filters.{position}.comparison"
                    for key, required in (
                        ("comparator_span", True),
                        ("value_span", True),
                        ("unit_span", False),
                    ):
                        _bind(
                            comparison,
                            key,
                            utterance,
                            failures,
                            notes,
                            f"{base}.{key}",
                            required=required,
                        )
        for key in ("relation", "time", "measure"):
            nested = goal.get(key)
            if isinstance(nested, dict):
                path = f"goals.{index}.{key}.cue"
                _bind(nested, "cue", utterance, failures, notes, path, required=key == "relation")
                if key == "relation":
                    reach_path = f"goals.{index}.relation.reach_cue"
                    _bind(
                        nested, "reach_cue", utterance, failures, notes, reach_path, required=False
                    )
                order = nested.get("order") if key == "measure" else None
                if isinstance(order, dict):
                    order_path = f"goals.{index}.measure.order"
                    for key in ("cue", "limit_span"):
                        _bind(
                            order,
                            key,
                            utterance,
                            failures,
                            notes,
                            f"{order_path}.{key}",
                            required=False,
                        )
    for key in ("context", "unsupported_constraints"):
        quotes = payload.get(key)
        if isinstance(quotes, list):
            for index, quoted in enumerate(quotes):
                holder = {"span": quoted}
                _bind(holder, "span", utterance, failures, notes, f"{key}.{index}")
                quotes[index] = holder["span"]
    if failures:
        return FormResolution(None, tuple(dict.fromkeys(failures)), tuple(notes[:16]))
    measure_words_to_cue(mentions, goals)
    valueless_window_to_unspecified(goals)
    _normalize_comparison_values(goals, utterance)
    try:
        return FormResolution(
            SemanticQuestionForm.model_validate(payload), (), request_kind=request_kind
        )
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False, include_context=False)
        fields = sorted({_path(error["loc"]) for error in errors})
        # Messages are authored by the contract, never copied from the model's values.
        messages = sorted({f"{_path(error['loc'])}: {error['msg']}" for error in errors})
        # A whole-form rule names itself as a closed code, so a trace shows which rule failed.
        rules = sorted({_rule_code(str(error["msg"])) for error in errors if not error["loc"]})
        return FormResolution(
            None,
            (
                *(f"form_contract_invalid:{field}" for field in fields[:8]),
                *(f"form_contract_rule:{rule}" for rule in rules[:4] if rule),
            ),
            tuple(messages[:16]),
        )


_QUOTE_TRAILING_PARTICLES = (
    "목록을",
    "목록이",
    "목록은",
    "목록",
    "리스트",
    "들을",
    "들이",
    "들은",
    "들의",
    "들",
    "에서",
    "에게",
    "으로",
    "로",
    "이",
    "가",
    "을",
    "를",
    "은",
    "는",
    "의",
    "에",
    "도",
    "만",
)


def _one_edit_match(target: str, candidate: str) -> bool:
    if "-" in target or "-" in candidate:
        return False
    a, b = target.casefold(), candidate.casefold()
    if len(a) < 3 or len(b) < 3 or a[0] != b[0] or a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        return (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]]
            and a[diffs[1]] == b[diffs[0]]
        )
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = j = diffs_count = 0
    while i < len(short) and j < len(long):
        if short[i] == long[j]:
            i += 1
            j += 1
        else:
            diffs_count += 1
            if diffs_count > 1:
                return False
            j += 1
    return True


def _strip_quote_particle(token: str) -> str:
    for suffix in _QUOTE_TRAILING_PARTICLES:
        if len(token) > len(suffix) + 1 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _locate_typo_quote(text: str, utterance: str) -> tuple[int, int] | None:
    compact_target = "".join(text.split())
    if len(compact_target) < 3:
        return None
    tokens: list[tuple[int, int, str]] = []
    idx = 0
    n = len(utterance)
    while idx < n:
        while idx < n and utterance[idx].isspace():
            idx += 1
        if idx >= n:
            break
        end = idx
        while end < n and not utterance[end].isspace():
            end += 1
        raw_token = utterance[idx:end].rstrip("?,!.:;)")
        if raw_token:
            tokens.append((idx, idx + len(raw_token), raw_token))
        idx = end
    word_count = len(text.split())
    max_window = min(3, max(2, word_count + 1))
    matches: list[tuple[int, int]] = []
    for win in range(1, max_window + 1):
        for i in range(len(tokens) - win + 1):
            span_start = tokens[i][0]
            last_start, last_end, last_raw = tokens[i + win - 1]
            mid_parts = [tokens[j][2] for j in range(i, i + win - 1)]
            full_compact = "".join((*mid_parts, last_raw))
            if _one_edit_match(compact_target, full_compact):
                matches.append((span_start, last_end))
                continue
            stem_last = _strip_quote_particle(last_raw)
            if stem_last != last_raw:
                stem_compact = "".join((*mid_parts, stem_last))
                if _one_edit_match(compact_target, stem_compact):
                    matches.append((span_start, last_start + len(stem_last)))
    unique = list(dict.fromkeys(matches))
    return unique[0] if len(unique) == 1 else None


def locate_quote(text: str, occurrence: int, utterance: str) -> tuple[int, int] | None:
    """Return the span of the given verbatim occurrence of ``text``, if any."""

    if not text or len(text) > MAX_QUOTE_CHARS or not 1 <= occurrence <= MAX_OCCURRENCE:
        return None
    start = -1
    for _ in range(occurrence):
        start = utterance.find(text, start + 1)
        if start < 0:
            stripped = text.strip()
            if stripped and stripped != text:
                return locate_quote(stripped, occurrence, utterance)
            unquoted = stripped.strip("'\"`")
            if unquoted and unquoted != stripped and len(unquoted) >= 2:
                return locate_quote(unquoted, occurrence, utterance)
            if occurrence == 1:
                return _locate_typo_quote(stripped or text, utterance)
            return None
    return start, start + len(text)


def separate_mentions(mentions: list[Any], utterance: str) -> None:
    """Move a mention that repeats words off another mention's span, when only one fits.

    One mention grounds one thing, so a quote whose stated occurrence lies inside another
    mention, as the first 리소스 inside 리소스 그룹 in 리소스 그룹별 리소스 개수, points at words
    already grounded. When exactly one verbatim occurrence of the same words overlaps no
    other mention, the quote can only mean that occurrence, so the span moves there. Code
    compares positions only; a quote with no such occurrence stays and fails admission.
    """

    spans = [
        (item["span"]["start"], item["span"]["end"])
        if isinstance(item, dict) and isinstance(item.get("span"), dict)
        else None
        for item in mentions
    ]
    for _ in range(len(spans)):
        moved = False
        for index, span in enumerate(spans):
            others = [other for position, other in enumerate(spans) if position != index and other]
            if span is None or not any(_overlaps(span, other) for other in others):
                continue
            text = utterance[span[0] : span[1]]
            free = [
                found
                for occurrence in range(1, MAX_OCCURRENCE + 1)
                if (found := locate_quote(text, occurrence, utterance)) is not None
                and not any(_overlaps(found, other) for other in others)
            ]
            if len(free) == 1:
                spans[index] = free[0]
                mentions[index]["span"] = {"start": free[0][0], "end": free[0][1]}
                moved = True
        if not moved:
            return


_MEASURE_VALUE_DOMAINS = frozenset({"state", "health", "metric"})


def measure_words_to_cue(mentions: list[Any], goals: list[Any]) -> None:
    """Quote a mention that only names its goal's measure as that measure's cue.

    A measure mention may restate the goal subject or cite a state, health, or metric
    value. A concept mention outside those value domains that nothing but one ungrouped
    measure cites, as 이벤트 for an event measure, is the measure's own name, so its words
    become the measure cue and the mention is dropped. A named resource or a literal is
    never moved. Code moves a quote between two fields and reads no word.
    """

    cited: dict[object, int] = {}
    for mention in mentions:
        qualifier = mention.get("qualifier") if isinstance(mention, dict) else None
        if isinstance(qualifier, dict):
            cited[qualifier.get("mention")] = cited.get(qualifier.get("mention"), 0) + 1
    for goal in goals:
        if not isinstance(goal, dict):
            continue
        refs = [goal.get("subject"), goal.get("counterpart")]
        refs.extend(
            item.get("mention") for item in goal.get("filters") or () if isinstance(item, dict)
        )
        relation = goal.get("relation")
        if isinstance(relation, dict):
            refs.extend((relation.get("anchor"), relation.get("counterpart")))
        measure = goal.get("measure")
        if isinstance(measure, dict):
            refs.append(measure.get("mention"))
        for ref in refs:
            cited[ref] = cited.get(ref, 0) + 1
    dropped: set[object] = set()
    for goal in goals:
        measure = goal.get("measure") if isinstance(goal, dict) else None
        # A grouping's mention may name the kind grouped by, so only an ungrouped measure moves.
        if not isinstance(measure, dict) or measure.get("group_by", "none") != "none":
            continue
        mention_id = measure.get("mention")
        mention = next(
            (item for item in mentions if isinstance(item, dict) and item.get("id") == mention_id),
            None,
        )
        cue = measure.get("cue")
        # An existing cue keeps its words; it absorbs the mention only when it holds its span.
        if cue is not None and not (mention is not None and _holds(cue, mention.get("span"))):
            continue
        if (
            mention is None
            or mention_id == goal.get("subject")
            or cited.get(mention_id) != 1
            or mention.get("qualifier") is not None
            # Only a general word names a measure; a named resource or a literal stays a mention,
            # and a state, health, or metric value is a restriction, never a measure's name.
            or mention.get("form") != "concept"
            or mention.get("domain") in _MEASURE_VALUE_DOMAINS
        ):
            continue
        measure["cue"] = cue if cue is not None else mention.get("span")
        measure["mention"] = None
        dropped.add(mention_id)
    if dropped:
        mentions[:] = [
            item for item in mentions if not (isinstance(item, dict) and item.get("id") in dropped)
        ]


def valueless_window_to_unspecified(goals: list[Any]) -> None:
    """Keep a qualitative time cue (such as 'recent' / '최근' with no number) as unspecified.

    When the proposer labels a numberless time cue as ``window`` with ``value: null``,
    the closed schema requires ``unspecified`` so the history compiler applies its
    default window while still accounting for the quoted time cue span.
    """

    for goal in goals:
        time_field = goal.get("time") if isinstance(goal, dict) else None
        if (
            isinstance(time_field, dict)
            and time_field.get("kind") == "window"
            and time_field.get("value") is None
            and not time_field.get("windows")
            and isinstance(time_field.get("cue"), dict)
        ):
            time_field["kind"] = "unspecified"


def _normalize_comparison_values(goals: list[Any], utterance: str) -> None:
    """Strip formatting commas or trailing units from comparison.value when matching value_span."""

    for goal in goals:
        filters = goal.get("filters") if isinstance(goal, dict) else None
        for item in filters if isinstance(filters, list) else ():
            comparison = item.get("comparison") if isinstance(item, dict) else None
            if not isinstance(comparison, dict):
                continue
            raw_val = comparison.get("value")
            vspan = comparison.get("value_span")
            if not isinstance(raw_val, str) or not isinstance(vspan, dict):
                continue
            cleaned = "".join(ch for ch in raw_val.strip() if ch.isdigit() or ch == ".")
            start, end = vspan.get("start", -1), vspan.get("end", -1)
            if 0 <= start < end <= len(utterance):
                span_digits = "".join(
                    ch for ch in utterance[start:end] if ch.isdigit() or ch == "."
                )
                if cleaned and cleaned != raw_val and cleaned == span_digits:
                    comparison["value"] = cleaned


def _holds(outer: object, inner: object) -> bool:
    return (
        isinstance(outer, dict)
        and isinstance(inner, dict)
        and outer.get("start", 1) <= inner.get("start", 0)
        and inner.get("end", 1) <= outer.get("end", 0)
    )


def _overlaps(first: tuple[int, int], second: tuple[int, int]) -> bool:
    return first[0] < second[1] and second[0] < first[1]


def _bind(
    container: dict[str, Any],
    key: str,
    utterance: str,
    failures: list[str],
    notes: list[str],
    path: str,
    *,
    required: bool = True,
) -> None:
    quoted = container.get(key)
    if quoted is None and not required:
        return
    if not isinstance(quoted, Mapping):
        failures.append(f"quote_missing:{key}")
        notes.append(f"{path}: a quote with text and occurrence is required")
        return
    text = quoted.get("text")
    occurrence = quoted.get("occurrence", 1)
    if not isinstance(text, str) or isinstance(occurrence, bool) or not isinstance(occurrence, int):
        failures.append(f"quote_invalid:{key}")
        notes.append(f"{path}: text MUST be a string and occurrence an integer")
        return
    span = locate_quote(text, occurrence, utterance)
    if span is None:
        failures.append(f"quote_not_verbatim:{key}")
        notes.append(f"{path}: the quote MUST copy the utterance verbatim at that occurrence")
        return
    container[key] = {"start": span[0], "end": span[1]}


def _rule_code(message: str) -> str:
    """Return a contract-authored validator message as one closed snake_case code."""

    text = message.removeprefix("Value error, ").casefold()
    words = "".join(char if char.isascii() and char.isalnum() else " " for char in text).split()
    return "_".join(words)[:60].rstrip("_")


def _path(location: tuple[int | str, ...]) -> str:
    return ".".join(str(part) for part in location) or "form"


__all__ = [
    "MAX_OCCURRENCE",
    "MAX_QUOTE_CHARS",
    "FormInputHeldError",
    "FormResolution",
    "locate_quote",
    "measure_words_to_cue",
    "question_form_proposal_schema",
    "resolve_question_form",
    "separate_mentions",
]

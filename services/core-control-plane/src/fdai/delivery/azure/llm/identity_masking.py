"""Opaque placeholders for exact identifiers in verbatim-quoted model input.

Model input minimization hides resource identifiers, addresses, and similar
values. A question-form call must still let the model quote the operator's
exact words, so each distinct identifier becomes one opaque placeholder before
minimization, and every quote the model returns is mapped back to the exact
original span. The model never sees the identifier, and Core never sees a
placeholder. A quote that cuts through a placeholder maps to no original text,
so Core fails it closed as a non-verbatim quote.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai.core.conversation.semantic_reasoning_proposal import MAX_OCCURRENCE, locate_quote
from fdai.delivery.azure.llm.input_detection import identity_segments

_OPEN = "\u27e6"
_CLOSE = "\u27e7"
_QUOTE_CONTAINERS = ("relation", "time", "measure")
_QUOTE_LISTS = ("context", "unsupported_constraints")


@dataclass(frozen=True, slots=True)
class _Placed:
    original_start: int
    original_end: int
    masked_start: int
    masked_end: int


class IdentityMask:
    """Map identifiers in one utterance and its context to stable placeholders."""

    def __init__(self, utterance: str, context: Sequence[str]) -> None:
        self._original = utterance
        self._placeholders: dict[str, str] = {}
        # Text that already carries the placeholder brackets could forge a mapping.
        self.usable = not any(_OPEN in text or _CLOSE in text for text in (utterance, *context))
        placed: list[_Placed] = []
        parts: list[str] = []
        cursor = 0
        length = 0
        for start, end in identity_segments(utterance) if self.usable else ():
            parts.append(utterance[cursor:start])
            length += start - cursor
            token = self._placeholder(utterance[start:end])
            parts.append(token)
            placed.append(_Placed(start, end, length, length + len(token)))
            length += len(token)
            cursor = end
        parts.append(utterance[cursor:])
        self.utterance = "".join(parts)
        self._placed = tuple(placed)
        self.context = tuple(self.mask_text(text) for text in context)

    @property
    def count(self) -> int:
        return len(self._placeholders)

    def mask_text(self, text: str) -> str:
        """Replace every identifier in ``text`` with its placeholder."""

        if not self.usable:
            return text
        output: list[str] = []
        cursor = 0
        for start, end in identity_segments(text):
            output.extend((text[cursor:start], self._placeholder(text[start:end])))
            cursor = end
        output.append(text[cursor:])
        return "".join(output)

    def mask_value(self, value: Any) -> Any:
        """Mask every string inside a JSON-compatible value."""

        if isinstance(value, str):
            return self.mask_text(value)
        if isinstance(value, Mapping):
            return {key: self.mask_value(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self.mask_value(item) for item in value]
        return value

    def unmask_form(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return the proposal with every quote mapped back to the original utterance."""

        if not self._placed:
            return dict(payload)
        return _map_quotes(payload, self._unmask_quote)

    def unmask_quote(self, quote: Mapping[str, Any]) -> Mapping[str, Any]:
        """Map one quote of the masked utterance back to the exact original words."""

        return self._unmask_quote(quote) if self._placed else dict(quote)

    def mask_form(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return an earlier proposal with every quote re-anchored to the masked utterance."""

        anchored = _map_quotes(payload, self._mask_quote) if self._placed else dict(payload)
        return dict(self.mask_value(anchored))

    def _mask_quote(self, quote: Mapping[str, Any]) -> Mapping[str, Any]:
        text = quote.get("text")
        occurrence = quote.get("occurrence", 1)
        if not isinstance(text, str) or type(occurrence) is not int:
            return quote
        span = locate_quote(text, occurrence, self._original)
        if span is None or any(self._inside_original(position) for position in span):
            return {"text": self.mask_text(text), "occurrence": occurrence}
        start, end = self._masked_position(span[0]), self._masked_position(span[1])
        masked = self.utterance[start:end]
        return {"text": masked, "occurrence": _occurrence_at(masked, start, self.utterance)}

    def _inside_original(self, position: int) -> bool:
        return any(item.original_start < position < item.original_end for item in self._placed)

    def _masked_position(self, position: int) -> int:
        offset = 0
        for item in self._placed:
            if item.original_end <= position:
                offset = item.masked_end - item.original_end
            else:
                break
        return position + offset

    def _unmask_quote(self, quote: Mapping[str, Any]) -> Mapping[str, Any]:
        text = quote.get("text")
        occurrence = quote.get("occurrence", 1)
        if not isinstance(text, str) or type(occurrence) is not int:
            return quote
        span = locate_quote(text, occurrence, self.utterance)
        if span is None or any(self._inside(position) for position in span):
            # The model saw only the masked utterance, so this quote cannot be verbatim.
            return {"text": text, "occurrence": MAX_OCCURRENCE + 1}
        start, end = self._original_position(span[0]), self._original_position(span[1])
        original = self._original[start:end]
        return {"text": original, "occurrence": _occurrence_at(original, start, self._original)}

    def _inside(self, position: int) -> bool:
        return any(item.masked_start < position < item.masked_end for item in self._placed)

    def _original_position(self, position: int) -> int:
        offset = 0
        for item in self._placed:
            if item.masked_end <= position:
                offset = item.original_end - item.masked_end
            else:
                break
        return position + offset

    def _placeholder(self, value: str) -> str:
        token = self._placeholders.get(value)
        if token is None:
            token = f"{_OPEN}ID{len(self._placeholders) + 1}{_CLOSE}"
            self._placeholders[value] = token
        return token


def _map_quotes(
    payload: Mapping[str, Any], convert: Callable[[Mapping[str, Any]], Mapping[str, Any]]
) -> dict[str, Any]:
    """Apply ``convert`` to every quote of a question-form payload."""

    def inside(container: object, key: str) -> Any:
        if not isinstance(container, Mapping):
            return container
        output = dict(container)
        quote = output.get(key)
        if isinstance(quote, Mapping):
            output[key] = convert(quote)
        return output

    def _comparison_quotes(item: Any) -> Any:
        if not isinstance(item, dict) or not isinstance(item.get("comparison"), Mapping):
            return item
        comparison: Any = item["comparison"]
        for key in ("comparator_span", "value_span", "unit_span"):
            comparison = inside(comparison, key)
        return {**item, "comparison": comparison}

    output = dict(payload)
    mentions = output.get("mentions")
    if isinstance(mentions, list):
        output["mentions"] = [inside(item, "span") for item in mentions]
    goals = output.get("goals")
    if isinstance(goals, list):
        converted = []
        for goal in goals:
            goal = inside(goal, "cue")
            if isinstance(goal, dict):
                for key in _QUOTE_CONTAINERS:
                    if key in goal:
                        goal[key] = inside(goal[key], "cue")
                if "relation" in goal:
                    goal["relation"] = inside(goal["relation"], "reach_cue")
                measure = goal.get("measure")
                if isinstance(measure, dict) and "order" in measure:
                    order = inside(inside(measure["order"], "cue"), "limit_span")
                    goal["measure"] = {**measure, "order": order}
                filters = goal.get("filters")
                if isinstance(filters, list):
                    goal["filters"] = [_comparison_quotes(inside(item, "cue")) for item in filters]
            converted.append(goal)
        output["goals"] = converted
    for key in _QUOTE_LISTS:
        quotes = output.get(key)
        if isinstance(quotes, list):
            output[key] = [convert(item) if isinstance(item, Mapping) else item for item in quotes]
    return output


def _occurrence_at(text: str, start: int, utterance: str) -> int:
    """Return which verbatim occurrence of ``text`` begins at ``start``, counting from 1."""

    count = 0
    position = -1
    while count <= MAX_OCCURRENCE:
        position = utterance.find(text, position + 1)
        if position < 0:
            break
        count += 1
        if position == start:
            return count
    return MAX_OCCURRENCE + 1


__all__ = ["IdentityMask"]

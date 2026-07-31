"""Generic lexical matching over the inventory query language catalog."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path

import yaml

from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    QueryTerms,
    QueryValues,
    load_inventory_query_language_from_mapping,
)

_TOKEN = re.compile(r"[^\W_]+(?:[.-][^\W_]+)*", re.UNICODE)
_NUMBER_AND_UNIT = re.compile(r"(?P<value>[1-9][0-9]{0,2})\s*(?P<unit>[^\W\d_]+)")


def normalize_query_tokens(value: object) -> tuple[str, ...]:
    """Return locale-neutral NFKC case-folded tokens."""

    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return tuple(match.group(0) for match in _TOKEN.finditer(normalized))


class InventoryQueryLanguageResolver:
    """Resolve catalog terms without prompt-specific regular expressions."""

    def __init__(self, registry: InventoryQueryLanguageRegistry) -> None:
        self.registry = registry
        self._suffixes = tuple(
            sorted(
                (unicodedata.normalize("NFKC", item).casefold() for item in registry.suffixes),
                key=len,
                reverse=True,
            )
        )

    def has(self, entries: Mapping[str, QueryTerms], entry_id: str, text: str) -> bool:
        entry = entries.get(entry_id)
        return entry is not None and self.contains_any(text, entry.terms)

    def matched_ids(self, entries: Mapping[str, QueryTerms], text: str) -> tuple[str, ...]:
        return tuple(
            entry_id for entry_id, entry in entries.items() if self.contains_any(text, entry.terms)
        )

    def matched_values(self, entries: Mapping[str, QueryValues], text: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                value
                for entry in entries.values()
                if self.contains_any(text, entry.terms)
                for value in entry.values
            )
        )

    def matched_value_groups(
        self,
        entries: Mapping[str, QueryValues],
        text: str,
    ) -> tuple[tuple[str, ...], ...]:
        """Return each matched semantic group's canonical provider values."""

        return tuple(
            entry.values for entry in entries.values() if self.contains_any(text, entry.terms)
        )

    def matched_value_entries(
        self,
        entries: Mapping[str, QueryValues],
        text: str,
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Return matched semantic ids together with provider values."""

        return tuple(
            (entry_id, entry.values)
            for entry_id, entry in entries.items()
            if self.contains_any(text, entry.terms)
        )

    def matched_entries(
        self,
        entries: Mapping[str, QueryValues],
        text: str,
    ) -> tuple[QueryValues, ...]:
        """Return complete matched entries for catalog-owned resolution policy."""

        return tuple(entry for entry in entries.values() if self.contains_any(text, entry.terms))

    def contains_any(self, text: str, terms: Sequence[str]) -> bool:
        tokens = normalize_query_tokens(text)
        return any(self._contains(tokens, normalize_query_tokens(term)) for term in terms)

    def is_exact(self, text: str, terms: Sequence[str]) -> bool:
        """Return whether the complete input is one catalog term plus suffix."""

        tokens = normalize_query_tokens(text)
        return any(
            len(tokens) == len(term_tokens) and self._contains(tokens, term_tokens)
            for term in terms
            if (term_tokens := normalize_query_tokens(term))
        )

    def parse_window_seconds(self, text: str) -> int | None:
        normalized = unicodedata.normalize("NFKC", text).casefold()
        tokens = normalize_query_tokens(normalized)
        for match in _NUMBER_AND_UNIT.finditer(normalized):
            value = int(match.group("value"))
            unit_tokens = normalize_query_tokens(match.group("unit"))
            for unit in self.registry.time_units.values():
                if any(
                    self._contains(unit_tokens, normalize_query_tokens(term)) for term in unit.terms
                ):
                    return value * unit.multiplier_seconds
        for index, token in enumerate(tokens[:-1]):
            if not token.isdigit():
                continue
            value = int(token)
            for unit in self.registry.time_units.values():
                if any(
                    self._contains(tokens[index + 1 :], normalize_query_tokens(term))
                    for term in unit.terms
                ):
                    return value * unit.multiplier_seconds
        return None

    def _contains(self, tokens: Sequence[str], term: Sequence[str]) -> bool:
        if not term or len(term) > len(tokens):
            return False
        for start in range(len(tokens) - len(term) + 1):
            candidate = tokens[start : start + len(term)]
            if all(
                left == right for left, right in zip(candidate[:-1], term[:-1], strict=True)
            ) and self._final_matches(candidate[-1], term[-1]):
                return True
        return False

    def _final_matches(self, token: str, expected: str) -> bool:
        return token == expected or any(token == expected + suffix for suffix in self._suffixes)


@lru_cache(maxsize=1)
def default_inventory_query_language_resolver() -> InventoryQueryLanguageResolver:
    repo_root = Path(__file__).resolve().parents[5]
    path = repo_root / "rule-catalog" / "vocabulary" / "inventory-query-language.yaml"
    registry = load_inventory_query_language_from_mapping(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    return InventoryQueryLanguageResolver(registry)


__all__ = [
    "InventoryQueryLanguageResolver",
    "default_inventory_query_language_resolver",
    "normalize_query_tokens",
]

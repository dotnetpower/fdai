"""Rule lookup index for the T0 engine.

Given a loaded rule catalog, the index answers "which rules apply to a
Signal of type ``S`` targeting a Resource of type ``R``?" in O(indexed
lookup), never a linear scan (see
``docs/roadmap/architecture/llm-strategy.md § Rule-to-Decision Lookup Pipeline``).

Ontology dispatch
-----------------
The index compiles the Rule v2 ``applies_to`` and ``triggered_by`` axes.
An explicit ``*`` trigger is a catch-all baseline; otherwise an event type
must match exactly. ``evaluates``, ``required_interfaces``, and
``submission_criteria`` are registration gates enforced by the catalog loader.

Determinism guarantees
----------------------
- The order of returned rules is stable: by ``severity`` desc, then
  ``rule.id`` asc. That is the same ordering
  ``docs/roadmap/phases/phase-1-rule-catalog-t0.md § Precedence`` prescribes,
  so a downstream verdict emitter can pick the top match without a
  second sort.
- Duplicate ``resource_type`` entries are grouped, not overwritten - the
  loader already forbids duplicate ``rule.id`` across files, so grouping
  is safe.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from fdai.rule_catalog.schema.signal_type import SignalTypeRegistry
from fdai.shared.contracts.models import Rule, Severity

# Severity precedence (higher = more urgent). Matches the
# `critical > high > medium > low` ordering documented in
# `phase-1-rule-catalog-t0.md § Precedence`.
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
}


def _severity_order_key(rule: Rule) -> tuple[int, str]:
    # Negative rank so higher severity sorts first with a plain ascending sort.
    return (-_SEVERITY_RANK[rule.severity], rule.id)


@dataclass(frozen=True, slots=True)
class RuleIndex:
    """Immutable lookup index over a loaded rule catalog.

    Instances are created with :meth:`build`; direct construction is not
    part of the public contract (the internal mappings may grow).
    """

    _by_resource_type: dict[str, tuple[Rule, ...]]
    _by_signal_type: dict[str, frozenset[str]]
    _by_id: dict[str, Rule]
    _signal_types: SignalTypeRegistry | None = None

    @classmethod
    def build(
        cls,
        rules: Iterable[Rule],
        *,
        signal_types: SignalTypeRegistry | None = None,
    ) -> RuleIndex:
        by_type: dict[str, list[Rule]] = {}
        by_signal: dict[str, set[str]] = {}
        by_id: dict[str, Rule] = {}
        for rule in rules:
            if rule.id in by_id:
                # The catalog loader rejects duplicates; if a caller
                # bypasses it, fail loudly rather than silently overwrite.
                raise ValueError(f"duplicate rule id in index build: {rule.id!r}")
            by_id[rule.id] = rule
            applies_to = rule.applies_to or [rule.resource_type]
            for resource_type in applies_to:
                by_type.setdefault(resource_type, []).append(rule)
            for signal_type in rule.triggered_by or ["*"]:
                by_signal.setdefault(signal_type, set()).add(rule.id)

        frozen: dict[str, tuple[Rule, ...]] = {
            key: tuple(sorted(items, key=_severity_order_key)) for key, items in by_type.items()
        }
        return cls(
            _by_resource_type=frozen,
            _by_signal_type={key: frozenset(ids) for key, ids in by_signal.items()},
            _by_id=by_id,
            _signal_types=signal_types,
        )

    def rules_for_type(self, resource_type: str) -> tuple[Rule, ...]:
        """Return every rule whose ``resource_type`` matches, severity-ordered."""
        return self._by_resource_type.get(resource_type, ())

    def rules_for_signal(
        self, *, resource_type: str, signal_type: str | None = None
    ) -> tuple[Rule, ...]:
        """Return every rule that would evaluate for this Signal.

        The result is the ``applies_to`` resource candidates intersected
        with catalog-resolved ``triggered_by`` matches plus legacy ``*`` rules.
        """
        allowed_ids = set(self._by_signal_type.get("*", ()))
        if self._signal_types is not None:
            resolved = self._signal_types.resolve(signal_type)
        elif "*" in self._by_signal_type:
            resolved = frozenset({signal_type}) if signal_type is not None else frozenset()
        elif self._by_signal_type and all(
            item.endswith(".observed") for item in self._by_signal_type
        ):
            # Compatibility for callers that load the concrete shipped catalog
            # but have not yet injected SignalTypeRegistry. This preserves the
            # former wildcard candidate set; OPA remains the verdict authority.
            resolved = frozenset(self._by_signal_type)
        else:
            resolved = frozenset({signal_type}) if signal_type is not None else frozenset()
        for resolved_type in resolved:
            allowed_ids.update(self._by_signal_type.get(resolved_type, ()))
        return tuple(rule for rule in self.rules_for_type(resource_type) if rule.id in allowed_ids)

    def rule(self, rule_id: str) -> Rule:
        try:
            return self._by_id[rule_id]
        except KeyError as exc:
            raise LookupError(f"unknown rule id: {rule_id!r}") from exc

    def ids(self) -> frozenset[str]:
        return frozenset(self._by_id.keys())

    def resource_types(self) -> frozenset[str]:
        return frozenset(self._by_resource_type.keys())

    def __len__(self) -> int:
        return len(self._by_id)


__all__ = ["RuleIndex"]

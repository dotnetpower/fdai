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

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from threading import RLock

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


@dataclass(frozen=True, slots=True)
class CatalogReloadReceipt:
    """Evidence for one catalog index transition."""

    attempted_catalog_version: str
    previous_catalog_version: str | None
    current_catalog_version: str
    accepted: bool
    retained_catalog_versions: tuple[str, ...]
    content_digest: str
    failure_reason: str | None = None


class CatalogIndexLifecycle:
    """Atomically publish a current index while retaining one replay version.

    Compilation happens before any lifecycle state is replaced. A failed
    compilation therefore leaves both the current and N-1 indexes available.
    Only the current and immediately preceding accepted versions are retained,
    which bounds replay memory and supports a safe rolling catalog transition.
    """

    def __init__(
        self,
        *,
        catalog_version: str,
        rules: Iterable[Rule],
        signal_types: SignalTypeRegistry | None = None,
        max_version_tombstones: int = 4096,
    ) -> None:
        if not catalog_version.strip():
            raise ValueError("catalog_version MUST be non-empty")
        if max_version_tombstones < 1:
            raise ValueError("max_version_tombstones MUST be >= 1")
        initial_rules = tuple(rules)
        self._lock = RLock()
        self._signal_types = signal_types
        self._max_version_tombstones = max_version_tombstones
        self._indexes: dict[str, RuleIndex] = {
            catalog_version: RuleIndex.build(initial_rules, signal_types=signal_types)
        }
        self._version_digests = {catalog_version: _rules_digest(initial_rules)}
        self._current_catalog_version = catalog_version
        self._previous_catalog_version: str | None = None
        self._last_receipt = CatalogReloadReceipt(
            attempted_catalog_version=catalog_version,
            previous_catalog_version=None,
            current_catalog_version=catalog_version,
            accepted=True,
            retained_catalog_versions=(catalog_version,),
            content_digest=self._version_digests[catalog_version],
        )

    @property
    def current_catalog_version(self) -> str:
        """Return the catalog version used for new dispatches."""
        with self._lock:
            return self._current_catalog_version

    @property
    def previous_catalog_version(self) -> str | None:
        """Return the one retained predecessor, if one exists."""
        with self._lock:
            return self._previous_catalog_version

    @property
    def current_index(self) -> RuleIndex:
        """Return the immutable index for the current catalog."""
        with self._lock:
            return self._indexes[self._current_catalog_version]

    @property
    def last_receipt(self) -> CatalogReloadReceipt:
        """Return evidence for the most recent transition attempt."""
        with self._lock:
            return self._last_receipt

    def reload(self, *, catalog_version: str, rules: Iterable[Rule]) -> CatalogReloadReceipt:
        """Compile and atomically accept a new catalog index.

        The candidate is compiled into a local immutable :class:`RuleIndex`
        before the current pointer changes. Compilation errors are re-raised
        and recorded as a rejected receipt without changing dispatch state.
        Reusing a version is allowed only when it produces the same index.
        """
        if not catalog_version.strip():
            raise ValueError("catalog_version MUST be non-empty")
        candidate_rules = tuple(rules)
        content_digest = _rules_digest(candidate_rules)
        try:
            candidate = RuleIndex.build(candidate_rules, signal_types=self._signal_types)
        except Exception as exc:
            with self._lock:
                previous = self._current_catalog_version
                self._last_receipt = CatalogReloadReceipt(
                    attempted_catalog_version=catalog_version,
                    previous_catalog_version=previous,
                    current_catalog_version=previous,
                    accepted=False,
                    retained_catalog_versions=self._retained_versions(),
                    content_digest=content_digest,
                    failure_reason=type(exc).__name__,
                )
            raise

        with self._lock:
            previous = self._current_catalog_version
            if catalog_version == previous:
                if candidate != self._indexes[previous]:
                    error = ValueError(
                        f"catalog version {catalog_version!r} was already accepted "
                        "with different rules"
                    )
                    self._last_receipt = CatalogReloadReceipt(
                        attempted_catalog_version=catalog_version,
                        previous_catalog_version=previous,
                        current_catalog_version=previous,
                        accepted=False,
                        retained_catalog_versions=self._retained_versions(),
                        content_digest=content_digest,
                        failure_reason=type(error).__name__,
                    )
                    raise error
                self._last_receipt = CatalogReloadReceipt(
                    attempted_catalog_version=catalog_version,
                    previous_catalog_version=self._previous_catalog_version,
                    current_catalog_version=previous,
                    accepted=True,
                    retained_catalog_versions=self._retained_versions(),
                    content_digest=content_digest,
                )
                return self._last_receipt

            if catalog_version in self._indexes:
                error = ValueError(
                    f"catalog version {catalog_version!r} is retained; use rollback explicitly"
                )
                self._last_receipt = CatalogReloadReceipt(
                    attempted_catalog_version=catalog_version,
                    previous_catalog_version=previous,
                    current_catalog_version=previous,
                    accepted=False,
                    retained_catalog_versions=self._retained_versions(),
                    content_digest=content_digest,
                    failure_reason=type(error).__name__,
                )
                raise error

            accepted_digest = self._version_digests.get(catalog_version)
            if accepted_digest is not None and accepted_digest != content_digest:
                error = ValueError(
                    f"catalog version {catalog_version!r} was previously accepted with "
                    "different rules"
                )
                self._last_receipt = CatalogReloadReceipt(
                    attempted_catalog_version=catalog_version,
                    previous_catalog_version=previous,
                    current_catalog_version=previous,
                    accepted=False,
                    retained_catalog_versions=self._retained_versions(),
                    content_digest=content_digest,
                    failure_reason=type(error).__name__,
                )
                raise error
            if (
                accepted_digest is None
                and len(self._version_digests) >= self._max_version_tombstones
            ):
                error = ValueError(
                    "catalog version tombstone capacity is exhausted; refusing reload"
                )
                self._last_receipt = CatalogReloadReceipt(
                    attempted_catalog_version=catalog_version,
                    previous_catalog_version=previous,
                    current_catalog_version=previous,
                    accepted=False,
                    retained_catalog_versions=self._retained_versions(),
                    content_digest=content_digest,
                    failure_reason=type(error).__name__,
                )
                raise error

            # The only state mutation occurs after successful compilation.
            self._indexes = {previous: self._indexes[previous], catalog_version: candidate}
            self._version_digests.setdefault(catalog_version, content_digest)
            self._previous_catalog_version = previous
            self._current_catalog_version = catalog_version
            self._last_receipt = CatalogReloadReceipt(
                attempted_catalog_version=catalog_version,
                previous_catalog_version=previous,
                current_catalog_version=catalog_version,
                accepted=True,
                retained_catalog_versions=self._retained_versions(),
                content_digest=content_digest,
            )
            return self._last_receipt

    def rollback(self) -> CatalogReloadReceipt:
        """Switch dispatch back to the retained N-1 index without recompiling."""
        with self._lock:
            previous = self._previous_catalog_version
            if previous is None:
                raise LookupError("catalog rollback requires a retained previous version")
            current = self._current_catalog_version
            self._current_catalog_version = previous
            self._previous_catalog_version = current
            self._indexes = {
                self._current_catalog_version: self._indexes[self._current_catalog_version],
                self._previous_catalog_version: self._indexes[self._previous_catalog_version],
            }
            self._last_receipt = CatalogReloadReceipt(
                attempted_catalog_version=previous,
                previous_catalog_version=current,
                current_catalog_version=previous,
                accepted=True,
                retained_catalog_versions=self._retained_versions(),
                content_digest=self._version_digests[previous],
            )
            return self._last_receipt

    def index_for(self, catalog_version: str) -> RuleIndex:
        """Return current or N-1 index for a replay, rejecting stale versions."""
        with self._lock:
            try:
                return self._indexes[catalog_version]
            except KeyError as exc:
                raise LookupError(
                    f"catalog version is not replayable: {catalog_version!r}"
                ) from exc

    def _retained_versions(self) -> tuple[str, ...]:
        return tuple(
            version
            for version in (self._current_catalog_version, self._previous_catalog_version)
            if version is not None
        )


def _rules_digest(rules: Iterable[Rule]) -> str:
    """Return a stable identity for a compiled catalog's rule content."""
    payload = tuple(
        sorted(
            ((rule.id, rule.model_dump(mode="json")) for rule in rules),
            key=lambda item: item[0],
        )
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["CatalogIndexLifecycle", "CatalogReloadReceipt", "RuleIndex"]

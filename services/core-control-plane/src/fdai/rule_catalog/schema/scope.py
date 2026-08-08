"""Governance scope - which resources an assignment covers, CSP-neutrally.

An assignment binds a rule/rule-set to a **scope** with an **effect**
(rule-governance.md "Scope"). This module is the pure selection layer: the scope
hierarchy, the selectors, exclusions, and the specificity used for precedence
(most-specific scope wins for parameters; the strictest effect - see
:mod:`fdai.rule_catalog.schema.effect` - wins for conflicting effects; a genuine
tie escalates to HIL).

Pure and I/O-free: ``Scope.covers`` is a deterministic predicate over a
:class:`ResourceContext` (the target's hierarchy + type + tags), so the loader,
the CI gate, and a what-if evaluation share one source of truth. Scope is data;
a broad scope never widens the executor's least-privilege identity
(security-and-identity.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Protocol


class ScopeLevel(IntEnum):
    """The CSP-neutral scope hierarchy, ordered least to most specific.

    Higher value = more specific, so ``max`` over the levels yields the
    most-specific scope for precedence.
    """

    ORGANIZATION = 0
    ACCOUNT = 1  # account / subscription
    RESOURCE_GROUP = 2
    RESOURCE = 3


@dataclass(frozen=True, slots=True)
class ScopeSelector:
    """Narrows a scope within its level (rule-governance.md "Selectors").

    A selector matches a resource when **every declared** criterion matches
    (declared = non-empty); an empty criterion imposes no constraint. An empty
    selector matches every resource in the scope.
    """

    resource_types: frozenset[str] = frozenset()
    tags: Mapping[str, str] = field(default_factory=dict)
    resource_ids: frozenset[str] = frozenset()

    def matches(self, ctx: ResourceContext) -> bool:
        if self.resource_types and ctx.resource_type not in self.resource_types:
            return False
        if self.resource_ids and ctx.resource_id not in self.resource_ids:
            return False
        for key, value in self.tags.items():
            if ctx.tags.get(key) != value:
                return False
        return True


@dataclass(frozen=True, slots=True)
class ResourceContext:
    """The target resource evaluated against a scope - its full hierarchy path
    plus type and tags. CSP-neutral: the ids are neutral scope ids and the
    ``resource_type`` is the vocabulary label."""

    organization: str
    account: str
    resource_group: str
    resource_id: str
    resource_type: str
    tags: Mapping[str, str] = field(default_factory=dict)

    def id_at(self, level: ScopeLevel) -> str:
        """Return this resource's id at the given hierarchy level."""
        return {
            ScopeLevel.ORGANIZATION: self.organization,
            ScopeLevel.ACCOUNT: self.account,
            ScopeLevel.RESOURCE_GROUP: self.resource_group,
            ScopeLevel.RESOURCE: self.resource_id,
        }[level]


@dataclass(frozen=True, slots=True)
class Scope:
    """A CSP-neutral scope: a hierarchy level + id, optional selector, and
    optional excluded child scope ids."""

    level: ScopeLevel
    id: str
    selector: ScopeSelector | None = None
    excludes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.id or self.id != self.id.strip():
            raise ValueError("Scope.id MUST be non-empty and free of leading/trailing whitespace")

    def covers(self, ctx: ResourceContext) -> bool:
        """True when this scope covers the resource.

        The scope's level id must equal the resource's id at that level
        (ancestor-or-self); the resource must not fall under an excluded child
        scope (any of its at-or-below hierarchy ids in ``excludes``); and the
        selector, if any, must match.
        """
        if ctx.id_at(self.level) != self.id:
            return False
        if self.excludes:
            for level in ScopeLevel:
                if level >= self.level and ctx.id_at(level) in self.excludes:
                    return False
        if self.selector is not None and not self.selector.matches(ctx):
            return False
        return True

    @property
    def specificity(self) -> int:
        """Higher = more specific (drives parameter precedence)."""
        return int(self.level)

    def covering_specificity(self, ctx: ResourceContext) -> int:  # noqa: ARG002 - ctx unused for a single-level scope
        """Specificity of this scope relative to ``ctx``.

        A single-level scope has exactly one level, so this is just
        :attr:`specificity` (``ctx`` is unused). Present so the resolver ranks
        both scope shapes context-relative without branching on the concrete
        type.
        """
        return self.specificity


class ScopeMatcher(Protocol):
    """A scope expression: a coverage predicate plus a specificity rank.

    Both :class:`Scope` (a single hierarchy level) and :class:`ScopeBinding`
    (include / exclude address lists) satisfy it, so an assignment may bind
    either without the resolver branching on the concrete type.
    """

    def covers(self, ctx: ResourceContext) -> bool: ...

    @property
    def specificity(self) -> int: ...

    def covering_specificity(self, ctx: ResourceContext) -> int: ...


def scope_specificity(scope: ScopeMatcher) -> int:
    """Higher = more specific (resource > resource-group > account > org)."""
    return scope.specificity


def most_specific[M: ScopeMatcher](scopes: Iterable[M]) -> tuple[M, ...]:
    """Return every scope tied at the highest specificity.

    ``len == 1`` -> a unique most-specific scope wins for parameters. ``len > 1``
    -> a genuine specificity tie: the caller escalates parameter conflicts to HIL
    while :func:`fdai.rule_catalog.schema.effect.strictest_effect` resolves the
    effect. Empty input -> empty tuple.
    """
    ordered = list(scopes)
    if not ordered:
        return ()
    top = max(s.specificity for s in ordered)
    return tuple(s for s in ordered if s.specificity == top)


_SCOPE_URI_PREFIX = "scope://"


@dataclass(frozen=True, slots=True)
class ScopeRef:
    """A canonical CSP-neutral scope address rendered as a ``scope://`` URI.

    ``scope://<org>[/<account>[/<resource-group>[/<resource>]]]`` - the number of
    path segments fixes the level (1 = organization ... 4 = resource), so the
    address is unambiguous and extensible (rule-governance.md "YAML Shapes").
    Unlike a bare :class:`Scope` (level + id), a ``ScopeRef`` carries the full
    ancestor chain, so two accounts that reuse a resource-group id never collide.
    """

    segments: tuple[str, ...]

    def __post_init__(self) -> None:
        if not (1 <= len(self.segments) <= len(ScopeLevel)):
            raise ValueError(
                f"ScopeRef MUST have 1..{len(ScopeLevel)} segments, got {len(self.segments)}"
            )
        for seg in self.segments:
            if not seg or seg != seg.strip() or "/" in seg:
                raise ValueError(
                    f"ScopeRef segment MUST be non-empty, whitespace-trimmed, and '/'-free: {seg!r}"
                )

    @property
    def level(self) -> ScopeLevel:
        """The hierarchy level this address resolves to (deepest segment)."""
        return ScopeLevel(len(self.segments) - 1)

    @property
    def id(self) -> str:
        """The scope id at this address's level (the last segment)."""
        return self.segments[-1]

    @classmethod
    def parse(cls, uri: str) -> ScopeRef:
        """Parse a ``scope://`` URI. Raises :class:`ValueError` on a bad prefix,
        an empty path, or an empty/embedded-slash segment."""
        if not uri.startswith(_SCOPE_URI_PREFIX):
            raise ValueError(f"scope URI MUST start with {_SCOPE_URI_PREFIX!r}: {uri!r}")
        path = uri[len(_SCOPE_URI_PREFIX) :]
        if not path:
            raise ValueError(f"scope URI MUST have at least one segment: {uri!r}")
        return cls(segments=tuple(path.split("/")))

    def render(self) -> str:
        """Render back to the canonical ``scope://`` URI (round-trips ``parse``)."""
        return _SCOPE_URI_PREFIX + "/".join(self.segments)

    def covers(self, ctx: ResourceContext) -> bool:
        """True when this address is an ancestor-or-self of the resource - every
        provided segment equals the resource's id at that level (full-chain
        match, stricter than :meth:`Scope.covers`)."""
        return all(ctx.id_at(ScopeLevel(index)) == seg for index, seg in enumerate(self.segments))

    def to_scope(
        self,
        *,
        selector: ScopeSelector | None = None,
        excludes: frozenset[str] = frozenset(),
    ) -> Scope:
        """Bridge to the single-level :class:`Scope` consumed by the resolver."""
        return Scope(level=self.level, id=self.id, selector=selector, excludes=excludes)


def _ref_dominates(ancestor: ScopeRef, descendant: ScopeRef) -> bool:
    """True when ``ancestor`` is an ancestor-or-equal address of ``descendant``
    (its segments are a prefix), so excluding ``ancestor`` removes everything
    ``descendant`` would include."""
    a = ancestor.segments
    d = descendant.segments
    return len(a) <= len(d) and d[: len(a)] == a


@dataclass(frozen=True, slots=True)
class ScopeBinding:
    """An assignment's scope as include / exclude address lists plus an optional
    selector - the extensible multi-scope form (rule-governance.md "YAML Shapes"
    ``scope.include`` / ``exclude`` / ``selectors``).

    Covers a resource when it matches **at least one** include :class:`ScopeRef`,
    **no** exclude, and the selector. A single-scope assignment is the degenerate
    case (one include, no exclude). ``specificity`` is the most-specific include
    level, so the existing most-specific-wins parameter precedence carries over.
    """

    includes: tuple[ScopeRef, ...]
    excludes: tuple[ScopeRef, ...] = ()
    selector: ScopeSelector | None = None

    def __post_init__(self) -> None:
        if not self.includes:
            raise ValueError("ScopeBinding MUST have at least one include scope")
        # A binding whose every include is structurally dominated by an exclude
        # (an exclude that is an ancestor-or-equal address of the include) covers
        # nothing - a silent dead assignment. Reject it at construction.
        if self.excludes and all(
            any(_ref_dominates(exc, inc) for exc in self.excludes) for inc in self.includes
        ):
            raise ValueError(
                "ScopeBinding covers nothing: every include is excluded "
                "(an exclude is an ancestor-or-equal of each include)"
            )

    def covers(self, ctx: ResourceContext) -> bool:
        if not any(ref.covers(ctx) for ref in self.includes):
            return False
        if any(ref.covers(ctx) for ref in self.excludes):
            return False
        if self.selector is not None and not self.selector.matches(ctx):
            return False
        return True

    @property
    def specificity(self) -> int:
        """The most-specific include level (drives parameter precedence)."""
        return max(int(ref.level) for ref in self.includes)

    def covering_specificity(self, ctx: ResourceContext) -> int:
        """Specificity relative to ``ctx``: the most-specific include that
        actually covers ``ctx``.

        Unlike :attr:`specificity` (the max include level, context-free), this
        ranks the binding by the include that matched the resource being
        resolved - so a broad include (e.g. org) sitting next to an unrelated
        narrow include does not inflate the binding's precedence and wrongly
        win the most-specific-scope parameter contest. Falls back to
        :attr:`specificity` only when no include covers ``ctx`` (which the
        resolver never does - it ranks assignments already known to cover).
        """
        covering = [int(ref.level) for ref in self.includes if ref.covers(ctx)]
        return max(covering) if covering else self.specificity


__all__ = [
    "ResourceContext",
    "Scope",
    "ScopeBinding",
    "ScopeLevel",
    "ScopeMatcher",
    "ScopeRef",
    "ScopeSelector",
    "most_specific",
    "scope_specificity",
]

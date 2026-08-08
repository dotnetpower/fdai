"""Pantheon registry: canonical lookup for agent specs and topic ownership.

Load once at process start; the registry rejects at import time any
violation of the single-writer invariant (two agents claiming the same
ObjectType) or the topic-ownership invariant (publish target does not
match declared owner).
"""

from __future__ import annotations

from collections.abc import Iterable

from fdai.agents._framework.base import AgentSpec
from fdai.agents._framework.pantheon import PANTHEON_NAMES, PANTHEON_SPECS


class PantheonRegistryError(ValueError):
    """Raised when the pantheon violates a hard invariant at load time."""


class PantheonRegistry:
    """In-memory index of agent specs, keyed for O(1) lookup by name / topic / object type."""

    def __init__(self, specs: Iterable[AgentSpec]) -> None:
        specs_tuple = tuple(specs)
        _validate(specs_tuple)
        self._specs_by_name: dict[str, AgentSpec] = {s.name: s for s in specs_tuple}
        # Precompute the owner-of-topic and owner-of-object-type indexes.
        # publishes is derived from owns in AgentSpec.__post_init__ so the
        # two maps stay consistent by construction.
        self._owner_of_topic: dict[str, str] = {}
        self._owner_of_object_type: dict[str, str] = {}
        for spec in specs_tuple:
            for topic in spec.publishes:
                self._owner_of_topic[topic] = spec.name
            for obj in spec.owns:
                self._owner_of_object_type[obj] = spec.name

    # ---- lookup --------------------------------------------------------

    def get(self, name: str) -> AgentSpec:
        try:
            return self._specs_by_name[name]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {name!r}") from exc

    def all(self) -> tuple[AgentSpec, ...]:
        return tuple(self._specs_by_name.values())

    def owner_of_topic(self, topic: str) -> str | None:
        return self._owner_of_topic.get(topic)

    def owner_of_object_type(self, object_type: str) -> str | None:
        return self._owner_of_object_type.get(object_type)

    def names(self) -> frozenset[str]:
        return frozenset(self._specs_by_name.keys())

    # ---- publish authorization ----------------------------------------

    def assert_can_publish(self, principal: str, topic: str) -> None:
        """Raise if `principal` is not the declared owner of `topic`.

        The bus adapter calls this before every publish so a wrong-owner
        publish is a hard error at the boundary, never silent.
        """
        owner = self._owner_of_topic.get(topic)
        if owner is None:
            raise PantheonRegistryError(f"topic {topic!r} has no declared owner in the pantheon")
        if owner != principal:
            raise PantheonRegistryError(
                f"agent {principal!r} is not the owner of topic {topic!r} (owner is {owner!r})"
            )


def _validate(specs: tuple[AgentSpec, ...]) -> None:
    """Enforce hard invariants across the pantheon.

    - Every declared agent name matches the canonical pantheon set.
    - No two agents claim the same ObjectType (single-writer invariant).
    - No two agents claim the same topic (derived; belt-and-braces check).
    - `reports_to` references a known agent (or None for Odin).
    """
    issues: list[str] = []
    seen_names: set[str] = set()
    owners_by_object_type: dict[str, str] = {}
    owners_by_topic: dict[str, str] = {}

    for spec in specs:
        if spec.name in seen_names:
            issues.append(f"duplicate agent name: {spec.name!r}")
        seen_names.add(spec.name)

        if spec.name not in PANTHEON_NAMES:
            issues.append(f"agent {spec.name!r} is not in the canonical pantheon set")

        if spec.reports_to is not None and spec.reports_to not in PANTHEON_NAMES:
            issues.append(f"agent {spec.name!r} reports_to unknown agent {spec.reports_to!r}")

        for obj in spec.owns:
            prior = owners_by_object_type.get(obj)
            if prior is not None:
                issues.append(
                    f"ObjectType {obj!r} is owned by both {prior!r} and {spec.name!r}"
                    " (single-writer invariant)"
                )
            else:
                owners_by_object_type[obj] = spec.name

        for topic in spec.publishes:
            prior_t = owners_by_topic.get(topic)
            if prior_t is not None:
                issues.append(f"topic {topic!r} is owned by both {prior_t!r} and {spec.name!r}")
            else:
                owners_by_topic[topic] = spec.name

    if set(seen_names) != PANTHEON_NAMES:
        missing = PANTHEON_NAMES - seen_names
        extra = seen_names - PANTHEON_NAMES
        if missing:
            issues.append(f"pantheon missing agents: {sorted(missing)!r}")
        if extra:
            issues.append(f"pantheon has extra agents: {sorted(extra)!r}")

    if issues:
        raise PantheonRegistryError("; ".join(issues))


def load_pantheon() -> PantheonRegistry:
    """Load the fixed 15-agent pantheon into a registry."""
    return PantheonRegistry(PANTHEON_SPECS)


__all__ = ["PantheonRegistry", "PantheonRegistryError", "load_pantheon"]

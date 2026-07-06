"""Routing-matrix parsing + validation.

Matrix shape (YAML, config-driven — see
``config/notifications-matrix.yaml`` for the shipped default)::

    matrix:
      version: 1
      default_route: hil_approval          # used when a message's
                                           # category is unknown
      routes:
        hil_approval:
          trust_tier: a1_hil_approval
          primary: teams-hil-prd
          fallback: [slack-hil-prd]
          on_all_fail: hil_escalate
        operational_alert:
          trust_tier: a2_operational_alert
          primary: teams-ops-prd
          fallback:
            - pagerduty-primary
            - email-oncall
          on_all_fail: hil_escalate
        ...

Validation happens at load time (fail-fast):

- every route names a real channel-id (checked when the router binds
  the registry, not here — this module only rejects structural bugs),
- ``on_all_fail`` is one of :class:`OnAllFailAction`,
- the ``default_route`` name references an existing route,
- ``trust_tier`` is a valid :class:`TrustTier` value.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from aiopspilot.shared.providers.notifications.base import TrustTier


class MatrixValidationError(ValueError):
    """Raised when the matrix YAML fails structural validation.

    Never leaks a raw stack trace to the operator — the message is
    English and points at the offending route so a fork can fix its
    config without opening the code.
    """


class OnAllFailAction(StrEnum):
    """What the router does when every configured channel fails.

    ``HIL_ESCALATE`` is the default and matches the design-doc rule
    "if every configured channel for a category fails, the request
    queues and pages the operational lane — it never auto-executes"
    (§1 principle 4). ``DROP`` is deliberately absent — messages are
    never silently discarded.
    """

    HIL_ESCALATE = "hil_escalate"
    QUEUE_AND_PAGE_OPS = "queue_and_page_ops"


@dataclass(frozen=True, slots=True)
class RouteSpec:
    """One row of the routing matrix.

    Frozen so a caller cannot swap the fallback list between the
    router's audit-write and the actual dispatch loop.
    """

    category: str
    trust_tier: TrustTier
    primary: str
    fallback: tuple[str, ...] = ()
    on_all_fail: OnAllFailAction = OnAllFailAction.HIL_ESCALATE

    @property
    def channel_ids(self) -> tuple[str, ...]:
        """Primary + fallback, in dispatch order."""
        return (self.primary, *self.fallback)


@dataclass(frozen=True, slots=True)
class NotificationMatrix:
    """The full parsed matrix — routes keyed by ``category``.

    ``default_route`` is looked up in :attr:`routes` when a message
    carries a category the matrix does not know. If the fork wants
    unknown categories to fail closed instead, it sets ``default_route``
    to a route whose ``on_all_fail`` is :attr:`OnAllFailAction.HIL_ESCALATE`
    (the shipped default).
    """

    version: int
    routes: Mapping[str, RouteSpec]
    default_route: str

    def resolve(self, category: str) -> RouteSpec:
        """Return the matching :class:`RouteSpec` (falls back on default)."""
        route = self.routes.get(category)
        if route is not None:
            return route
        # Guaranteed by validation to exist:
        return self.routes[self.default_route]

    def __post_init__(self) -> None:
        if self.default_route not in self.routes:
            raise MatrixValidationError(
                f"default_route {self.default_route!r} does not name a route"
            )


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_matrix_from_yaml(path: Path) -> NotificationMatrix:
    """Read + validate ``config/notifications-matrix.yaml`` (or a fork override)."""
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise MatrixValidationError(f"matrix file {path} MUST be a YAML mapping")
    return load_matrix_from_mapping(raw)


def load_matrix_from_mapping(raw: Mapping[str, Any]) -> NotificationMatrix:
    """Validate an already-parsed mapping and return the typed matrix.

    Separated from the YAML loader so unit tests can build a matrix
    in-code without touching the filesystem.
    """
    matrix_raw = raw.get("matrix")
    if not isinstance(matrix_raw, dict):
        raise MatrixValidationError("top-level 'matrix' key is required and MUST be a mapping")

    version = matrix_raw.get("version", 1)
    if not isinstance(version, int) or version < 1:
        raise MatrixValidationError("'matrix.version' MUST be a positive integer")

    routes_raw = matrix_raw.get("routes")
    if not isinstance(routes_raw, dict) or not routes_raw:
        raise MatrixValidationError("'matrix.routes' MUST be a non-empty mapping")

    routes: dict[str, RouteSpec] = {}
    for name, spec_raw in routes_raw.items():
        if not isinstance(name, str) or not name:
            raise MatrixValidationError(f"route name MUST be a non-empty string, got {name!r}")
        if not isinstance(spec_raw, dict):
            raise MatrixValidationError(f"route {name!r} MUST be a mapping")
        routes[name] = _parse_route(name, spec_raw)

    default_route = matrix_raw.get("default_route")
    if not isinstance(default_route, str) or not default_route:
        raise MatrixValidationError(
            "'matrix.default_route' MUST be a non-empty string naming one of the routes"
        )

    return NotificationMatrix(version=version, routes=routes, default_route=default_route)


def _parse_route(name: str, raw: Mapping[str, Any]) -> RouteSpec:
    trust_tier_raw = raw.get("trust_tier")
    if not isinstance(trust_tier_raw, str):
        raise MatrixValidationError(f"route {name!r}: 'trust_tier' MUST be a string")
    try:
        trust_tier = TrustTier(trust_tier_raw)
    except ValueError as exc:
        raise MatrixValidationError(
            f"route {name!r}: unknown trust_tier {trust_tier_raw!r}"
        ) from exc

    primary = raw.get("primary")
    if not isinstance(primary, str) or not primary:
        raise MatrixValidationError(
            f"route {name!r}: 'primary' MUST be a non-empty channel-id string"
        )

    fallback_raw = raw.get("fallback", [])
    if not isinstance(fallback_raw, list):
        raise MatrixValidationError(f"route {name!r}: 'fallback' MUST be a list")
    fallback: list[str] = []
    for i, entry in enumerate(fallback_raw):
        if not isinstance(entry, str) or not entry:
            raise MatrixValidationError(
                f"route {name!r}: fallback[{i}] MUST be a non-empty channel-id string"
            )
        fallback.append(entry)

    on_all_fail_raw = raw.get("on_all_fail", OnAllFailAction.HIL_ESCALATE.value)
    if not isinstance(on_all_fail_raw, str):
        raise MatrixValidationError(f"route {name!r}: 'on_all_fail' MUST be a string")
    try:
        on_all_fail = OnAllFailAction(on_all_fail_raw)
    except ValueError as exc:
        raise MatrixValidationError(
            f"route {name!r}: unknown on_all_fail {on_all_fail_raw!r}"
        ) from exc

    return RouteSpec(
        category=name,
        trust_tier=trust_tier,
        primary=primary,
        fallback=tuple(fallback),
        on_all_fail=on_all_fail,
    )


__all__ = [
    "MatrixValidationError",
    "NotificationMatrix",
    "OnAllFailAction",
    "RouteSpec",
    "load_matrix_from_mapping",
    "load_matrix_from_yaml",
]

"""Injector + probe factory contracts for the chaos-scenarios catalog.

The catalog (`rule-catalog/chaos-scenarios/`) ships each scenario with
an ``injector`` string (e.g. ``"chaos-mesh:StressChaos"``,
``"az:vm-run-command"``, ``"needs-injector"``) and an
``expected_signal``. This module defines the seams that turn a loaded
:class:`~fdai.core.chaos.scenario_catalog.CatalogEntry` into a concrete
``(FaultInjector, SignalProbe)`` pair the harness can run.

Design intent:

- **Pluggable registries**, not hardcoded switches. The `core/` layer
  defines the interfaces and the empty default registries; the
  `delivery/` layer registers concrete builders. A fork can register
  additional builders in the composition root without touching this
  file.
- **Fail closed** on unknown injectors or probes. `needs-injector`
  entries raise :class:`UnavailableInjectorError` instead of silently
  returning a no-op - the caller is meant to filter them out with
  :meth:`SceneryFactory.executable_entries`, or handle the exception
  and move on.
- **No `delivery/` imports.** The `core/` seams are pure interfaces;
  the composition root wires the delivery-layer builders in via the
  `register_*` methods.
- **Deterministic dispatch.** Every builder is a callable
  ``(CatalogEntry, dict[str, Any]) -> FaultInjector | SignalProbe``;
  registration is by exact injector string (e.g. ``"chaos-mesh"``,
  ``"kubectl:scale"``) and lookup is a two-tier match (prefix, then
  full string).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from fdai.core.chaos.injector import FaultInjector, SignalProbe
from fdai.core.chaos.scenario_catalog import CatalogEntry

#: Injector-string markers that flag a catalog entry as intentionally
#: NOT executable in this composition. Anything in this set makes
#: :meth:`ScenarioFactory.is_executable` return False and
#: :meth:`ScenarioFactory.build` raise :class:`UnavailableInjectorError`.
#:
#: - ``needs-injector`` - a delivery adapter has not landed yet.
#: - ``cross-csp-reference`` - the scenario is catalog data borrowed
#:   from another CSP (e.g. AWS FIS on an Azure-only FDAI). Kept for
#:   symptom vocabulary and T2 RCA candidate matching; never executed.
NON_EXECUTABLE_MARKERS: frozenset[str] = frozenset({"needs-injector", "cross-csp-reference"})

# Callables the delivery layer registers.
InjectorBuilder = Callable[[CatalogEntry, dict[str, Any]], FaultInjector]
"""``(entry, context) -> FaultInjector``. ``context`` is the composition
root's dispatch context (kubectl context, resource group, AOAI endpoint,
etc.) - never a secret; secrets stay in provider adapters."""

ProbeBuilder = Callable[[CatalogEntry, dict[str, Any]], SignalProbe]
"""``(entry, context) -> SignalProbe``."""


class UnavailableInjectorError(RuntimeError):
    """No builder is registered for this scenario's ``injector`` string.

    Raised for legitimate cases (``needs-injector`` catalog entries whose
    delivery adapter has not landed yet) and for genuinely unknown
    strings. The message names both the scenario id and the injector
    string so a fork can decide whether to register a builder or
    filter the entry out.
    """


class UnavailableProbeError(RuntimeError):
    """No probe builder is registered for this scenario's expected signal.

    Raised when the catalog entry uses a registered ``expected_signal``
    but no probe builder is bound to it in this composition. Distinct
    from the above so callers can distinguish "no injector" from
    "injector shipped, probe not wired".
    """


class ScenarioFactory:
    """Dispatch a :class:`CatalogEntry` to a concrete injector + probe.

    Registry keys are matched two-tier for injectors:

    1. **Exact** match on the full injector string
       (``"chaos-mesh:StressChaos"``).
    2. **Prefix** match on everything before the first ``:``
       (``"chaos-mesh"``) - the generic Chaos Mesh builder wraps every
       CRD kind, so most `chaos-mesh:*` scenarios use one prefix
       registration and dispatch by ``kind`` inside the builder.

    Probes are dispatched by ``expected_signal`` only (a single probe
    class can cover multiple scenarios that produce the same signal).

    The registries are plain dicts so a composition root can freeze or
    replace them per environment.
    """

    def __init__(self) -> None:
        self._injectors_exact: dict[str, InjectorBuilder] = {}
        self._injectors_prefix: dict[str, InjectorBuilder] = {}
        self._probes: dict[str, ProbeBuilder] = {}

    # ---- registration -------------------------------------------------

    def register_injector(self, injector_ref: str, builder: InjectorBuilder) -> None:
        """Register a builder for a full injector string
        (``"chaos-mesh:StressChaos"``) or a prefix (``"chaos-mesh"``).

        A prefix registration matches any scenario whose injector string
        starts with ``<prefix>:``. Exact registrations take precedence
        so a per-kind adapter can override the generic one.
        """
        if not injector_ref:
            raise ValueError("injector_ref MUST be non-empty")
        if ":" in injector_ref:
            self._injectors_exact[injector_ref] = builder
        else:
            self._injectors_prefix[injector_ref] = builder

    def register_probe(self, expected_signal: str, builder: ProbeBuilder) -> None:
        """Register a probe builder for one expected_signal."""
        if not expected_signal:
            raise ValueError("expected_signal MUST be non-empty")
        self._probes[expected_signal] = builder

    # ---- lookup -------------------------------------------------------

    def is_executable(self, entry: CatalogEntry) -> bool:
        """True iff both an injector builder and a probe builder are wired.

        ``needs-injector`` entries always return False. Useful to filter
        a large catalog down to what a specific composition can actually
        run today (delivery adapters vary per fork / environment).
        """
        return self._resolve_injector(entry) is not None and (entry.expected_signal in self._probes)

    def executable_entries(self, entries: Iterable[CatalogEntry]) -> list[CatalogEntry]:
        """Return the subset of `entries` this factory can dispatch."""
        return [e for e in entries if self.is_executable(e)]

    def build(
        self, entry: CatalogEntry, context: dict[str, Any] | None = None
    ) -> tuple[FaultInjector, SignalProbe]:
        """Instantiate a `(FaultInjector, SignalProbe)` pair for one entry.

        Raises:
            UnavailableInjectorError: no builder registered for the
                scenario's injector string (or the entry is
                ``needs-injector``).
            UnavailableProbeError: no probe builder registered for the
                scenario's ``expected_signal``.
        """
        ctx = dict(context or {})
        builder = self._resolve_injector(entry)
        if builder is None:
            raise UnavailableInjectorError(
                f"{entry.id}: no injector builder registered for {entry.spec['injector']!r}"
            )
        injector = builder(entry, ctx)
        probe_builder = self._probes.get(entry.expected_signal)
        if probe_builder is None:
            raise UnavailableProbeError(
                f"{entry.id}: no probe builder registered for signal {entry.expected_signal!r}"
            )
        probe = probe_builder(entry, ctx)
        return injector, probe

    # ---- diagnostics --------------------------------------------------

    def registered_injectors(self) -> tuple[str, ...]:
        return tuple(
            sorted(list(self._injectors_exact) + [f"{p}:*" for p in self._injectors_prefix])
        )

    def registered_probes(self) -> tuple[str, ...]:
        return tuple(sorted(self._probes))

    # ---- internal -----------------------------------------------------

    def _resolve_injector(self, entry: CatalogEntry) -> InjectorBuilder | None:
        ref = str(entry.spec.get("injector", ""))
        if ref in NON_EXECUTABLE_MARKERS or not ref:
            return None
        # Exact wins over prefix.
        if ref in self._injectors_exact:
            return self._injectors_exact[ref]
        prefix = ref.split(":", 1)[0]
        return self._injectors_prefix.get(prefix)


__all__ = [
    "InjectorBuilder",
    "NON_EXECUTABLE_MARKERS",
    "ProbeBuilder",
    "ScenarioFactory",
    "UnavailableInjectorError",
    "UnavailableProbeError",
]

"""Detection-signal registry tests.

The signal registry is the shared vocabulary the detection layer, the
trust router, the investigation analyzers, and the chaos harness use to
name one observable condition. It MUST stay stable (constant values are
audit and config surface) and internally consistent.
"""

from __future__ import annotations

import re

from fdai.core.detection.signals import (
    SIGNAL_BACKEND_HEALTH,
    SIGNAL_DB_CPU,
    SIGNAL_GATEWAY_LATENCY,
    SIGNAL_HOST_CPU,
    SIGNAL_HOST_MEMORY,
    SIGNAL_MEMBER_HOTSPOT,
    SIGNAL_NODE_CPU,
    SIGNAL_POD_RESTART,
    SIGNAL_RATE_LIMIT,
    SIGNAL_REQUEST_FAILURE,
    SIGNAL_ROLLOUT_STALL,
    SignalRole,
    SignalSpec,
    is_known_signal,
    known_signals,
    signals_with_role,
)

_ALL_CONSTANTS = (
    SIGNAL_BACKEND_HEALTH,
    SIGNAL_DB_CPU,
    SIGNAL_GATEWAY_LATENCY,
    SIGNAL_HOST_CPU,
    SIGNAL_HOST_MEMORY,
    SIGNAL_MEMBER_HOTSPOT,
    SIGNAL_NODE_CPU,
    SIGNAL_POD_RESTART,
    SIGNAL_RATE_LIMIT,
    SIGNAL_REQUEST_FAILURE,
    SIGNAL_ROLLOUT_STALL,
)

# Signal names flow into audit records, log lines, and Rego identifiers.
# Enforce a grep-friendly shape - lowercase, snake_case, ASCII only, no
# whitespace, no punctuation.
_SIGNAL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def test_every_constant_is_registered() -> None:
    for name in _ALL_CONSTANTS:
        assert is_known_signal(name), f"constant {name!r} missing from registry"


def test_registry_keys_match_specs() -> None:
    for key, spec in known_signals().items():
        assert isinstance(spec, SignalSpec)
        assert key == spec.signal, "registry key must equal SignalSpec.signal"


def test_registry_is_read_only() -> None:
    registry = known_signals()
    try:
        registry["injected_signal"] = SignalSpec(  # type: ignore[index]
            signal="injected_signal",
            description="d",
            tier_hint="T0",
            rca_hint="r",
        )
    except TypeError:
        return
    raise AssertionError("known_signals() must return a read-only mapping")


def test_tier_hint_is_recognized() -> None:
    """Tier hints stay within the known routing shapes."""
    allowed = {"T0", "T0+T1", "T0+T2", "T0+forecast"}
    for spec in known_signals().values():
        assert spec.tier_hint in allowed, (
            f"{spec.signal}: unknown tier_hint {spec.tier_hint!r}"
        )


def test_unknown_signal_is_rejected() -> None:
    assert not is_known_signal("nope_not_here")


def test_every_registered_signal_matches_shape() -> None:
    """Every SIGNAL_* string is lowercase snake_case, ASCII, no
    whitespace / punctuation - safe as an audit/log/Rego identifier."""
    for name in known_signals():
        assert _SIGNAL_NAME_RE.match(name), (
            f"signal {name!r} does not match {_SIGNAL_NAME_RE.pattern!r} "
            f"(signals flow into audit/log/Rego identifiers)"
        )


def test_registry_description_is_non_empty_ascii() -> None:
    """Descriptions surface in operator-facing text; enforce non-empty
    ASCII so L0 audit/log lines stay grep-friendly."""
    for spec in known_signals().values():
        assert spec.description.strip(), f"{spec.signal}: description empty"
        assert spec.description.isascii(), (
            f"{spec.signal}: description contains non-ASCII characters"
        )


# ---------------------------------------------------------------------------
# Signal-role field (R3-again hardening: single source of truth)
# ---------------------------------------------------------------------------


def test_role_field_defaults_to_scenario() -> None:
    """Adding a new signal without thinking about its role is treated
    as ``SignalRole.SCENARIO`` (safest default); RCA-only signals must
    opt in explicitly."""
    spec = SignalSpec(
        signal="throwaway_test_signal",
        description="Fixture only; not registered.",
        tier_hint="T0",
        rca_hint="none",
    )
    assert spec.role is SignalRole.SCENARIO


def test_member_hotspot_is_rca_only_in_the_registry() -> None:
    """The registry is the single source of truth. If member_hotspot
    ever loses its RCA_ONLY tag, tests in tests/core/chaos would
    (correctly) start treating it as a scenario signal."""
    spec = known_signals()[SIGNAL_MEMBER_HOTSPOT]
    assert spec.role is SignalRole.RCA_ONLY


def test_signals_with_role_partitions_the_registry() -> None:
    """Every registered signal is exactly one role."""
    all_signals = set(known_signals().keys())
    scenario = signals_with_role(SignalRole.SCENARIO)
    rca_only = signals_with_role(SignalRole.RCA_ONLY)
    assert scenario.isdisjoint(rca_only)
    assert scenario | rca_only == all_signals

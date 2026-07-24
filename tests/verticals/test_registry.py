"""Vertical registry - #28 new-domain onboarding seam.

Verifies the registry validates onboarding (unique ASCII ids, enabled
verticals need a rule source, shadow-first only) and enumerates verticals
deterministically.
"""

from __future__ import annotations

import pytest

from fdai.core.verticals import (
    VerticalDescriptor,
    VerticalRegistrationError,
    VerticalRegistry,
)
from fdai.shared.contracts.models import Category, Mode


def _descriptor(
    vertical_id: str = "security-posture",
    *,
    category: Category = Category.SECURITY,
    rule_source_ids: tuple[str, ...] = ("mcsb",),
    enabled: bool = True,
    default_mode: Mode = Mode.SHADOW,
) -> VerticalDescriptor:
    return VerticalDescriptor(
        vertical_id=vertical_id,
        display_name="Security Posture",
        category=category,
        rule_source_ids=rule_source_ids,
        enabled=enabled,
        default_mode=default_mode,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_register_and_lookup() -> None:
    reg = VerticalRegistry()
    reg.register(_descriptor())
    assert reg.has("security-posture")
    assert reg.get("security-posture").category is Category.SECURITY


def test_all_and_enabled_are_id_sorted() -> None:
    reg = VerticalRegistry()
    reg.register_all(
        [
            _descriptor("compliance", category=Category.COMPLIANCE),
            _descriptor("security-posture"),
            _descriptor(
                "patch-mgmt", category=Category.RELIABILITY, enabled=False, rule_source_ids=()
            ),
        ]
    )
    assert [d.vertical_id for d in reg.all()] == [
        "compliance",
        "patch-mgmt",
        "security-posture",
    ]
    # patch-mgmt is disabled -> excluded from enabled().
    assert [d.vertical_id for d in reg.enabled()] == ["compliance", "security-posture"]


def test_disabled_vertical_may_omit_rule_source() -> None:
    reg = VerticalRegistry()
    # A disabled (not-yet-wired) domain can be pre-registered with no source.
    reg.register(_descriptor("draft-domain", enabled=False, rule_source_ids=()))
    assert reg.has("draft-domain")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_duplicate_id_is_rejected() -> None:
    reg = VerticalRegistry()
    reg.register(_descriptor())
    with pytest.raises(VerticalRegistrationError, match="already registered"):
        reg.register(_descriptor())


def test_empty_id_is_rejected() -> None:
    reg = VerticalRegistry()
    with pytest.raises(VerticalRegistrationError, match="non-empty"):
        reg.register(_descriptor(""))


def test_non_ascii_id_is_rejected() -> None:
    reg = VerticalRegistry()
    # "보안" is Korean text (non-ASCII) - the literal subject under
    # test: an id that must be rejected because config/audit/metrics keys
    # MUST be ASCII (encoded per language.instructions.md fixture rule).
    with pytest.raises(VerticalRegistrationError, match="ASCII"):
        reg.register(_descriptor("보안"))


def test_enabled_without_rule_source_is_rejected() -> None:
    reg = VerticalRegistry()
    with pytest.raises(VerticalRegistrationError, match="at least one rule source"):
        reg.register(_descriptor(enabled=True, rule_source_ids=()))


def test_onboarding_in_enforce_mode_is_rejected() -> None:
    reg = VerticalRegistry()
    with pytest.raises(VerticalRegistrationError, match="shadow mode"):
        reg.register(_descriptor(default_mode=Mode.ENFORCE))


def test_register_all_aborts_on_first_failure() -> None:
    reg = VerticalRegistry()
    with pytest.raises(VerticalRegistrationError):
        reg.register_all(
            [
                _descriptor("good"),
                _descriptor("good"),  # duplicate -> abort
                _descriptor("never-reached"),
            ]
        )
    assert reg.has("good")
    assert not reg.has("never-reached")


def test_get_missing_raises_key_error() -> None:
    reg = VerticalRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")

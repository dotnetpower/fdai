"""Tests for the capability catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.core.capability_catalog import (
    Capability,
    CapabilityCatalog,
    CapabilityCategory,
    DuplicateCapabilityError,
    SideEffectClass,
    default_capability_catalog,
)
from fdai.shared.contracts.models import Mode


def test_mutating_capability_must_default_to_shadow() -> None:
    with pytest.raises(ValueError, match="shadow"):
        Capability(
            capability_id="bad",
            name="bad",
            category=CapabilityCategory.REMEDIATION,
            summary="s",
            side_effect_class=SideEffectClass.EXECUTE,
            default_mode=Mode.ENFORCE,
        )


def test_read_capability_may_be_enforce_mode() -> None:
    cap = Capability(
        capability_id="ok",
        name="ok",
        category=CapabilityCategory.INVESTIGATION,
        summary="s",
        side_effect_class=SideEffectClass.READ,
        default_mode=Mode.ENFORCE,
    )
    assert cap.default_mode is Mode.ENFORCE


def test_duplicate_registration_rejected() -> None:
    cap = Capability(
        capability_id="x",
        name="x",
        category=CapabilityCategory.KNOWLEDGE,
        summary="s",
        side_effect_class=SideEffectClass.READ,
    )
    catalog = CapabilityCatalog((cap,))
    with pytest.raises(DuplicateCapabilityError):
        catalog.register(cap)


def test_list_filters_by_category_and_enabled() -> None:
    enabled = Capability(
        capability_id="a",
        name="a",
        category=CapabilityCategory.CHAOS,
        summary="s",
        side_effect_class=SideEffectClass.EXECUTE,
    )
    disabled = Capability(
        capability_id="b",
        name="b",
        category=CapabilityCategory.CHAOS,
        summary="s",
        side_effect_class=SideEffectClass.READ,
        enabled=False,
    )
    catalog = CapabilityCatalog((enabled, disabled))

    assert [c.capability_id for c in catalog.list(category=CapabilityCategory.CHAOS)] == ["a"]
    assert len(catalog.list(category=CapabilityCategory.CHAOS, enabled_only=False)) == 2


def test_default_catalog_covers_slides_8_to_20() -> None:
    catalog = default_capability_catalog()
    slide_refs = {c.slide_ref for c in catalog.list()}
    # Representative slides from the tracked range are present.
    assert {"8", "9", "10-14", "15", "16", "17", "18"} <= slide_refs


def test_default_catalog_has_auditable_fifty_plus_sre_capabilities() -> None:
    entries = default_capability_catalog().list()
    parity_entries = [entry for entry in entries if "sre-parity" in entry.tags]
    assert len(entries) >= 50
    assert len(parity_entries) >= 40
    assert all(entry.official_source for entry in parity_entries)
    assert all(entry.evidence_refs for entry in parity_entries)
    assert all(Path(ref).exists() for entry in parity_entries for ref in entry.evidence_refs)
    assert {entry.parity.value for entry in parity_entries} <= {
        "native",
        "safer-alternative",
        "external-binding",
    }


def test_console_view_is_serializable_metadata() -> None:
    view = default_capability_catalog().as_console_view()
    assert view
    first = view[0]
    assert set(first) >= {
        "capability_id",
        "category",
        "side_effect_class",
        "default_mode",
        "required_role",
        "parity",
        "official_source",
        "evidence_refs",
    }
    # Every mutating capability advertises shadow as its default mode.
    for entry in view:
        if entry["side_effect_class"] in {"execute", "breakglass"}:
            assert entry["default_mode"] == "shadow"

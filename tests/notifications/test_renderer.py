"""Unit tests for the notification catalog + renderer (L2 localization).

English is the source of truth and renders byte-identical to the strings the
control loop composed before i18n; Korean is asserted structurally (no Hangul
literals in this .py, per the english-only gate) plus the mandatory English
fallback. L0 values (decision word, rule ids) are substituted verbatim in every
locale.
"""

from __future__ import annotations

import pytest

from fdai.core.notifications.renderer import NotificationCatalog, default_catalog

_PARAMS = {
    "decision": "auto",
    "resource_title": "compute.vm",
    "resource_body": "compute.vm",
    "rules": "nsg-deny-all",
    "mode": "shadow",
}


def test_english_render_is_byte_identical() -> None:
    title, body = default_catalog().render("decision", _PARAMS, "en")
    assert title == "FDAI decision: auto (compute.vm)"
    assert body == (
        "**Decision:** auto\n\n"
        "**Resource type:** compute.vm\n\n"
        "**Citing rules:** nsg-deny-all\n\n"
        "**Mode:** shadow"
    )


def test_ko_localizes_labels_but_keeps_values_verbatim() -> None:
    en_title, en_body = default_catalog().render("decision", _PARAMS, "en")
    ko_title, ko_body = default_catalog().render("decision", _PARAMS, "ko")
    # Localized: the labels differ from English.
    assert ko_title != en_title
    assert ko_body != en_body
    assert "Decision:" not in ko_body
    # L0 values are substituted verbatim, never translated.
    for value in ("auto", "compute.vm", "nsg-deny-all", "shadow"):
        assert value in ko_body
    assert "auto" in ko_title
    # The FDAI mark is preserved in the localized title.
    assert "FDAI" in ko_title


def test_unknown_locale_falls_back_to_english() -> None:
    en = default_catalog().render("decision", _PARAMS, "en")
    other = default_catalog().render("decision", _PARAMS, "fr")
    assert other == en


def test_missing_key_returns_the_key() -> None:
    title, body = default_catalog().render("no.such.template", {}, "en")
    assert title == "no.such.template"
    assert body == "no.such.template"


def test_lagging_locale_field_falls_back_to_english() -> None:
    # ko translates the title but not the body -> body renders in English.
    catalog = NotificationCatalog(
        locales={
            "en": {"x": {"title": "EN Title {v}", "body": "EN Body {v}"}},
            "ko": {"x": {"title": "KO Title {v}"}},
        }
    )
    title, body = catalog.render("x", {"v": "1"}, "ko")
    assert title == "KO Title 1"
    assert body == "EN Body 1"  # mandatory English fallback


def test_unmatched_placeholder_is_left_verbatim() -> None:
    catalog = NotificationCatalog(locales={"en": {"x": {"title": "{a}/{b}", "body": ""}}})
    title, _ = catalog.render("x", {"a": "1"}, "en")
    assert title == "1/{b}"


def test_source_locale_is_required() -> None:
    with pytest.raises(ValueError, match="source locale"):
        NotificationCatalog(locales={"ko": {}})


def test_has_requires_full_english_template() -> None:
    catalog = NotificationCatalog(
        locales={
            "en": {"full": {"title": "t", "body": "b"}, "partial": {"title": "t"}},
        }
    )
    assert catalog.has("full") is True
    assert catalog.has("partial") is False  # missing body -> treated as absent
    assert catalog.has("missing") is False


def test_default_catalog_fully_defines_decision() -> None:
    assert default_catalog().has("decision") is True

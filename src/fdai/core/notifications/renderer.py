"""Notification message catalog + renderer - L2 localization for notifications.

Option C from the notifications-i18n design: ``core`` emits a ``template_key``
plus typed ``params`` on every :class:`NotificationMessage`; this catalog turns
that key + params + a channel locale into the final ``title`` / ``body_markdown``
at dispatch time.

English (``messages.en.json``) is the source of truth. A locale catalog
(``messages.ko.json``) MAY lag: a missing locale key or field falls back to the
English source (mandatory English fallback), and a missing English key renders
the key itself so a typo is visible rather than blank.

Crucially, only the template *labels* localize. The L0 values (decision word,
rule ids, resource type, mode) are passed as ``params`` and substituted
verbatim, so the machine-parseable data is identical in every language and the
audit entry (which records the un-rendered message) stays English. This mirrors
the L3 rule "render in the operator locale over an English pipeline".
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Final

_PLACEHOLDER: Final = re.compile(r"\{(\w+)\}")
_DEFAULT_LOCALE: Final = "en"
_CATALOG_DIR: Final = Path(__file__).parent


def _canonical_locale(locale: str) -> str:
    """Reduce a locale tag to its lowercased BCP47 primary subtag.

    So ``ko-KR`` and ``KO`` both resolve to ``ko``; an unknown tag simply misses
    the catalog and falls back to English. This stops a channel configured with
    a region tag or the wrong case from silently rendering in English.
    """
    return locale.split("-", 1)[0].strip().lower()


def _load(locale: str) -> dict[str, dict[str, str]]:
    path = _CATALOG_DIR / f"messages.{locale}.json"
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"failed to load notification catalog {path.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"notification catalog messages.{locale}.json must be an object")
    catalog: dict[str, dict[str, str]] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            raise ValueError(f"notification catalog entry {key!r} must be an object")
        catalog[str(key)] = {str(f): str(v) for f, v in entry.items()}
    return catalog


class NotificationCatalog:
    """Renders ``(template_key, params, locale)`` into ``(title, body)``.

    Constructed with in-memory catalogs (test-friendly) or via
    :meth:`load_default`, which reads the bundled ``messages.*.json``.
    """

    def __init__(
        self,
        *,
        locales: Mapping[str, Mapping[str, Mapping[str, str]]],
    ) -> None:
        if _DEFAULT_LOCALE not in locales:
            raise ValueError(
                f"notification catalog MUST include the {_DEFAULT_LOCALE!r} source locale"
            )
        self._locales: Final = locales

    @classmethod
    def load_default(cls) -> NotificationCatalog:
        """Load the ``en`` + ``ko`` catalogs bundled next to this module."""
        return cls(locales={"en": _load("en"), "ko": _load("ko")})

    def render(
        self,
        template_key: str,
        params: Mapping[str, str],
        locale: str = _DEFAULT_LOCALE,
    ) -> tuple[str, str]:
        """Return the localized ``(title, body_markdown)`` for ``template_key``.

        Falls back to the English source per field, then to the key itself.
        """
        title = self._resolve(template_key, "title", locale)
        body = self._resolve(template_key, "body", locale)
        return _substitute(title, params), _substitute(body, params)

    def has(self, template_key: str) -> bool:
        """True when the English source fully defines ``template_key``.

        A caller (the router) checks this before rendering so that an unknown or
        malformed key falls back to the caller's baked English message instead of
        rendering the key string itself. English is the source of truth, so a key
        the ``en`` catalog cannot fully render is treated as absent.
        """
        entry = self._locales[_DEFAULT_LOCALE].get(template_key)
        return entry is not None and "title" in entry and "body" in entry

    def _resolve(self, template_key: str, field: str, locale: str) -> str:
        localized = self._lookup(locale, template_key, field)
        if localized is not None:
            return localized
        english = self._lookup(_DEFAULT_LOCALE, template_key, field)
        if english is not None:
            return english
        return template_key

    def _lookup(self, locale: str, template_key: str, field: str) -> str | None:
        entry = self._locales.get(_canonical_locale(locale), {}).get(template_key)
        if entry is None:
            return None
        return entry.get(field)


def _substitute(template: str, params: Mapping[str, str]) -> str:
    """Replace ``{name}`` placeholders; leave an unmatched one verbatim."""

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = params.get(name)
        return match.group(0) if value is None else value

    return _PLACEHOLDER.sub(_replace, template)


_DEFAULT_CATALOG: NotificationCatalog | None = None
_CATALOG_LOCK: Final = threading.Lock()


def default_catalog() -> NotificationCatalog:
    """Process-wide default catalog (lazy-loaded, immutable after load).

    Double-checked locking so concurrent first-callers (multiple worker threads)
    load it at most once.
    """
    global _DEFAULT_CATALOG
    if _DEFAULT_CATALOG is None:
        with _CATALOG_LOCK:
            if _DEFAULT_CATALOG is None:
                _DEFAULT_CATALOG = NotificationCatalog.load_default()
    return _DEFAULT_CATALOG


__all__ = ["NotificationCatalog", "default_catalog"]

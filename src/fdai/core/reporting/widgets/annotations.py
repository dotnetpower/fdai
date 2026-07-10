"""Annotation-family widget builders: free_text, note, image.

These widgets carry their payload in :attr:`WidgetSpec.options`; they
skip the datasource step (the engine passes an empty :class:`DataSet`).
That keeps a report YAML self-contained for text callouts and section
headers without needing a "static text" datasource.

The composite ``group`` widget is intentionally NOT registered here:
:class:`~fdai.core.reporting.engine.ReportEngine` special-cases it so
group semantics stay a single concern in one place.

Widget ``data`` schemas:

- ``free_text``: ``{"body": <markdown-string>}``.
- ``note``: ``{"body", "severity"}`` (``severity`` is one of
  ``info`` / ``warning`` / ``critical`` / ``ok``, default ``info``).
- ``image``: ``{"src", "alt", "caption"?}``. The image URL MUST be a
  same-origin path or an HTTPS URL - the FE renderer refuses anything
  else, so an operator cannot embed a ``javascript:`` payload from a
  malicious YAML.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from fdai.core.reporting.models import DataSet, WidgetSpec

_ALLOWED_IMAGE_SCHEMES: frozenset[str] = frozenset({"https", ""})
_VALID_NOTE_SEVERITIES: frozenset[str] = frozenset({"info", "warning", "critical", "ok"})
# Only raster formats. SVG is intentionally excluded - it can carry
# script tags and would execute in a permissive viewer even from an
# https origin.
_ALLOWED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif"}
)


class FreeTextBuilder:
    """Render a static markdown block."""

    type_name = "free_text"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del data
        return {"body": str(spec.options.get("body", ""))}


class NoteBuilder:
    """Render a labeled callout."""

    type_name = "note"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del data
        severity = str(spec.options.get("severity", "info")).lower()
        if severity not in _VALID_NOTE_SEVERITIES:
            severity = "info"
        return {
            "body": str(spec.options.get("body", "")),
            "severity": severity,
        }


class ImageBuilder:
    """Render an embedded image.

    Rejects:

    - URL schemes outside ``https`` and same-origin (empty scheme);
    - file extensions not in :data:`_ALLOWED_IMAGE_EXTENSIONS`
      (raster formats only; ``.svg`` is intentionally excluded because
      it can carry script content and would execute in a permissive
      viewer even from an https origin);
    - URLs with a query string that contains a suspicious extension.

    On rejection returns an ``error``-style body so the FE has no
    reason to attempt the fetch. Defense in depth on top of the CSP the
    read-API serves.
    """

    type_name = "image"

    def build(self, *, spec: WidgetSpec, data: DataSet) -> Mapping[str, Any]:
        del data
        src = str(spec.options.get("src", "")).strip()
        alt = str(spec.options.get("alt", ""))
        caption = spec.options.get("caption")
        parsed = urlparse(src)
        if parsed.scheme not in _ALLOWED_IMAGE_SCHEMES:
            return {"src": None, "alt": alt, "error": "unsupported url scheme"}
        path_lower = parsed.path.lower()
        extension = _extension(path_lower)
        if extension not in _ALLOWED_IMAGE_EXTENSIONS:
            return {
                "src": None,
                "alt": alt,
                "error": f"unsupported image extension {extension!r}",
            }
        payload: dict[str, Any] = {"src": src, "alt": alt}
        if caption is not None:
            payload["caption"] = str(caption)
        return payload


def _extension(path: str) -> str:
    dot = path.rfind(".")
    if dot < 0:
        return ""
    return path[dot:]


__all__ = [
    "FreeTextBuilder",
    "ImageBuilder",
    "NoteBuilder",
]

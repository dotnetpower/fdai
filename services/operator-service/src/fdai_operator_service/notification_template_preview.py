"""Render service-owned synthetic notification template previews."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from typing import Final

from fdai_service_contracts import JsonObject

_INCIDENT_OPENED_TEMPLATE: Final = "templates/incident-opened.html"
_INCIDENT_OPENED_SUBJECT: Final = "[SEV2] Incident opened - API latency after configuration rollout"
_INCIDENT_OPENED_PLAIN_TEXT: Final = (
    "SEV2 incident opened at 06:03 UTC. Eight signals were correlated. No recovery action has run."
)


@lru_cache(maxsize=1)
def _incident_opened_html() -> str:
    return (
        files("fdai_operator_service")
        .joinpath(_INCIDENT_OPENED_TEMPLATE)
        .read_text(encoding="utf-8")
    )


def incident_opened_template_preview() -> JsonObject:
    """Return the reviewed synthetic incident-open email preview."""

    return {
        "key": "incident-opened",
        "subject": _INCIDENT_OPENED_SUBJECT,
        "plain_text": _INCIDENT_OPENED_PLAIN_TEXT,
        "html": _incident_opened_html(),
    }

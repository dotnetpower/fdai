"""Shared bounded text and payload checks for pure channel renderers."""

from __future__ import annotations

import json
from collections.abc import Mapping

from fdai.shared.providers.channel_presentation import (
    ChannelPresentationCapabilities,
    ChannelPresentationEnvelope,
    ChannelPresentationRenderError,
)

_TRUNCATION_MARKER = "[CHANNEL TEXT TRUNCATED]"


def build_fallback_text(
    envelope: ChannelPresentationEnvelope,
    capabilities: ChannelPresentationCapabilities,
) -> tuple[str, bool]:
    """Preserve mandatory safety context and trim only canonical prose if needed."""
    mandatory = _mandatory_text(envelope)
    separator = "\n\n" if mandatory else ""
    available = capabilities.max_text_chars - len(separator) - len(mandatory)
    if available < 1:
        raise ChannelPresentationRenderError(
            "mandatory channel presentation text exceeds the capability limit"
        )
    canonical = envelope.canonical_text
    degraded = envelope.artifact_degraded
    if len(canonical) > available:
        marker = "\n" + _TRUNCATION_MARKER
        if available <= len(marker):
            raise ChannelPresentationRenderError(
                "channel presentation cannot retain canonical text and mandatory context"
            )
        canonical = canonical[: available - len(marker)].rstrip() + marker
        degraded = True
    return canonical + separator + mandatory, degraded


def payload_size(body: Mapping[str, object]) -> int:
    """Return deterministic UTF-8 JSON size without allowing NaN."""
    return len(
        json.dumps(
            body,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def ensure_payload_fits(
    body: Mapping[str, object],
    capabilities: ChannelPresentationCapabilities,
) -> None:
    if payload_size(body) > capabilities.max_serialized_bytes:
        raise ChannelPresentationRenderError(
            "mandatory channel presentation payload exceeds the capability limit"
        )


def _mandatory_text(envelope: ChannelPresentationEnvelope) -> str:
    sections: list[str] = []
    if envelope.limitations:
        sections.append("Limitations:\n" + "\n".join(f"- {item}" for item in envelope.limitations))
    sections.append("Evidence:\n" + "\n".join(f"- {item}" for item in envelope.evidence_refs))
    sections.append(f"Authority: {envelope.authority}\nExecution authority: none")
    if envelope.unavailable:
        sections.append("Availability: unavailable")
    if envelope.web_url is not None:
        sections.append(f"Web: {envelope.web_url}")
    return "\n\n".join(sections)


__all__ = ["build_fallback_text", "ensure_payload_fits", "payload_size"]

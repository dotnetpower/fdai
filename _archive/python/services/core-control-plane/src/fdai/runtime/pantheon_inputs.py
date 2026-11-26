"""Environment-derived inputs for the Pantheon composition root."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.runtime.development_authority import pantheon_development_bindings


def pantheon_heartbeat(environment: Mapping[str, str]) -> float | None:
    """Return the optional positive Pantheon heartbeat interval in seconds."""
    raw = environment.get("FDAI_PANTHEON_HEARTBEAT_SECONDS", "").strip()
    if not raw:
        return None
    try:
        heartbeat = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"FDAI_PANTHEON_HEARTBEAT_SECONDS={raw!r} is not a float") from exc
    if heartbeat <= 0:
        raise RuntimeError(f"FDAI_PANTHEON_HEARTBEAT_SECONDS MUST be > 0; got {heartbeat}")
    return heartbeat


__all__ = ["pantheon_development_bindings", "pantheon_heartbeat"]

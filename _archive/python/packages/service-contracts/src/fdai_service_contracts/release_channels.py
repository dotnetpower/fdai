"""Release channel spellings are metadata, never promotion or execution authority."""

from __future__ import annotations

RELEASE_CHANNELS = ("DEV", "RELEASE_CANDIDATE", "RELEASE")
_LEGACY_CHANNELS = {
    "development": "DEV",
    "beta": "RELEASE_CANDIDATE",
    "stable": "RELEASE",
}


class ReleaseChannelError(ValueError):
    """A channel is outside the supported built-in channel contract."""


def current_release_channel(value: str) -> str:
    """Validate a new signature's channel without accepting legacy aliases."""
    if value not in RELEASE_CHANNELS:
        raise ReleaseChannelError("release channel must be DEV, RELEASE_CANDIDATE or RELEASE")
    return value


def verified_release_channel(value: str) -> str:
    """Map metadata only after authenticating original signed document bytes."""
    return current_release_channel(_LEGACY_CHANNELS.get(value, value))

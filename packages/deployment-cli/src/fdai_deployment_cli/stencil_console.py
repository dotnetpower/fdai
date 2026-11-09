"""Project one verified Release Stencil into Console publication inputs."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_deployment_cli.console_config import validate_console_stencil_flags
from fdai_deployment_cli.standalone_console_publish import publish_verified_console


def flags(
    selection: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if selection is None or "stencil" not in selection:
        return None
    stencil = selection["stencil"]
    if not isinstance(stencil, dict):
        raise TypeError("Hub selection Stencil metadata is invalid")
    stencil_id = stencil.get("stencil_id")
    feature_flags = stencil.get("feature_flags")
    if (
        not isinstance(stencil_id, str)
        or not isinstance(feature_flags, dict)
        or feature_flags.get("stencil_id") != stencil_id
    ):
        raise ValueError("Hub selection Stencil feature flags are invalid")
    return dict(feature_flags)


def console_update_stencil_flags(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise TypeError("Console update target Stencil feature flags are invalid")
    flags = validate_console_stencil_flags(raw)
    if (
        flags.get("schema_version") != "fdai.stencil-feature-flags.v1"
        or flags.get("enforcement_mode") != "fail-closed"
        or not isinstance(flags.get("stencil_id"), str)
    ):
        raise ValueError("Console update target requires fail-closed Stencil feature flags")
    return flags


__all__ = [
    "console_update_stencil_flags",
    "flags",
    "publish_verified_console",
]

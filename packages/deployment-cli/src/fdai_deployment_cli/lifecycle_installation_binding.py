"""Private installation binding contract shared by the Hub infrastructure and workload agents."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from fdai_deployment_cli.private_output import write_private_output

INSTALLATION_BINDING_FORMAT = "fdai.installation-binding.v1"
_BINDING_KEY = re.compile(r"[a-z][a-z0-9_.-]{0,62}\Z", re.ASCII)
_MAX_BINDING_VALUES = 128
_MAX_BINDING_VALUE_LENGTH = 1024
_CREDENTIAL_VALUE = re.compile(
    r"(?i)([a-z][a-z0-9+.-]*://[^/\s]*@|\*{6}|accountkey=|sharedaccesskey=|-----BEGIN )"
)


def validate_installation_binding_values(
    values: Mapping[str, object],
    *,
    allowed_keys: frozenset[str],
) -> dict[str, str]:
    """Validate exact reviewed Terraform outputs without exposing rejected values."""

    if len(values) > _MAX_BINDING_VALUES:
        raise ValueError("installation binding has too many values")
    if set(values) - allowed_keys:
        raise ValueError("installation binding names a key the bundle does not reference")
    if allowed_keys - set(values):
        raise ValueError("installation binding lacks a key the bundle references")
    validated: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str) or _BINDING_KEY.fullmatch(key) is None:
            raise ValueError("installation binding key is invalid")
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= _MAX_BINDING_VALUE_LENGTH
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or _CREDENTIAL_VALUE.search(value)
        ):
            raise ValueError("installation binding value is invalid")
        validated[key] = value
    return validated


def write_installation_binding(
    path: Path,
    values: Mapping[str, object],
    *,
    allowed_keys: frozenset[str],
) -> None:
    """Persist exact reviewed Terraform outputs as one private installation binding."""

    validated = validate_installation_binding_values(values, allowed_keys=allowed_keys)
    document = {
        "format": INSTALLATION_BINDING_FORMAT,
        "values": validated,
    }
    write_private_output(
        path,
        json.dumps(document, sort_keys=True, separators=(",", ":")),
    )

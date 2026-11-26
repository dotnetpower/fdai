"""Config loader - schema check *and* pydantic validation at one boundary.

Every :class:`~fdai.shared.config.provider.ConfigProvider` funnels
through :func:`load_from_mapping` so config load always applies both:

1. **JSON Schema** (draft-2020-12) - structural + type + enum + pattern.
2. **pydantic** - additional invariants encoded in the model layer.

Both stages aggregate their findings into a single
:class:`~fdai.shared.config.errors.ConfigError` so an operator sees the
full remediation list on the first attempt.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from typing import Any, cast

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from .errors import ConfigError, ConfigIssue
from .models import AppConfig

_SCHEMA_PACKAGE = "fdai.shared.config"
_SCHEMA_FILE = "schema.json"


def load_from_mapping(raw: Mapping[str, Any]) -> AppConfig:
    """Validate ``raw`` and return an :class:`AppConfig`.

    Aggregates JSON Schema issues + pydantic issues into one
    :class:`ConfigError`.
    """
    issues: list[ConfigIssue] = []

    # 1) JSON Schema pass.
    schema = _load_schema()
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(dict(raw)), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(ConfigIssue(key=path, message=err.message))

    if issues:
        # Bail out before pydantic - pydantic errors on missing keys would be
        # redundant with the schema pass and add noise.
        raise ConfigError(issues)

    # 2) pydantic pass - catches invariants the schema can't express (e.g. an
    # enum coerced from an env-var string).
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        for e in exc.errors():
            loc = ".".join(str(p) for p in e.get("loc", ()))
            issues.append(ConfigIssue(key=loc or "<root>", message=e["msg"]))
        raise ConfigError(issues) from exc


def load_config_from_env() -> AppConfig:
    """Convenience: build an :class:`EnvVarConfigProvider` and call ``.get()``.

    Kept as a top-level function so composition roots can import one symbol.
    """
    from .provider import EnvVarConfigProvider

    return EnvVarConfigProvider().get()


def _load_schema() -> dict[str, Any]:
    raw = resources.files(_SCHEMA_PACKAGE).joinpath(_SCHEMA_FILE).read_text(encoding="utf-8")
    return cast(dict[str, Any], json.loads(raw))


__all__ = ["load_config_from_env", "load_from_mapping"]

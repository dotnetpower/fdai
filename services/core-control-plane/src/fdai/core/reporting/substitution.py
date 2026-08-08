"""Variable substitution for :class:`~fdai.core.reporting.models.QuerySpec` parameters.

A report YAML can reference declared variables inside the ``query.parameters``
mapping with either ``"$var"`` or ``"${var}"`` syntax. The engine calls
:func:`substitute` once per widget - after
:meth:`~fdai.core.reporting.engine.ReportEngine._resolve_variables` has
validated the override map - so the datasource sees a fully materialized
value.

Substitution rules (fail-closed, minimal, no shell semantics):

- Only string values in the parameters tree are substituted; other types
  (int / float / bool / None / nested containers) are copied verbatim.
- ``"$var"`` / ``"${var}"`` inside a string is replaced with the string
  value from the ``variables`` map. Unknown names raise
  :class:`VariableRejectedError` (the caller should have declared every
  variable it references).
- A **whole-string** reference (``"$var"`` with no surrounding text)
  passes through the underlying string as-is; a **partial** reference
  (``"prod-$env-vm"``) always produces a string. Variables can never
  inject a boolean / number - a datasource that wants a typed override
  reads it from the ``variables`` mapping that is already handed in.
- Reserved characters: ``$$`` is a literal ``$``. Anything else after a
  bare ``$`` that is not a valid identifier is a literal ``$`` followed
  by the next character (defensive against `$foo!bar` typos).

Kept pure so it is trivially testable and reusable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fdai.core.reporting.contracts import VariableRejectedError

_TOKEN_RE = re.compile(r"\$\$|\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def substitute(value: Any, variables: Mapping[str, str]) -> Any:
    """Return ``value`` with every ``$var`` / ``${var}`` reference resolved.

    Recurses into ``dict`` / ``list`` / ``tuple`` containers. Non-string
    scalars pass through unchanged.
    """
    if isinstance(value, str):
        return _substitute_string(value, variables)
    if isinstance(value, Mapping):
        return {key: substitute(sub, variables) for key, sub in value.items()}
    if isinstance(value, (list, tuple)):
        rendered = [substitute(item, variables) for item in value]
        return type(value)(rendered) if isinstance(value, tuple) else rendered
    return value


def _substitute_string(value: str, variables: Mapping[str, str]) -> str:
    if "$" not in value:
        return value

    def _sub(match: re.Match[str]) -> str:
        raw = match.group(0)
        if raw == "$$":
            return "$"
        name = match.group(1) or match.group(2)
        if name is None:  # pragma: no cover - re guarantees one branch
            return raw
        if name not in variables:
            raise VariableRejectedError(f"query references undeclared variable {name!r}")
        return str(variables[name])

    return _TOKEN_RE.sub(_sub, value)


__all__ = ["substitute"]

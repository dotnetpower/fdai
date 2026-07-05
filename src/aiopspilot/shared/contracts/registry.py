"""Schema registry — the DI seam that decides *where raw JSON schemas come from*.

Core modules depend on the :class:`SchemaRegistry` :class:`~typing.Protocol`
only; a fork registers a concrete implementation at the composition root and
selects it via config. The upstream default,
:class:`PackageResourceSchemaRegistry`, loads schemas that ship inside this
package (``importlib.resources``). A fork MAY plug in a remote registry
(e.g. a schema-registry service, a git-tracked catalog snapshot) by
implementing :class:`SchemaRegistry` and registering that binding — no change
to ``core/`` required.

The registry deliberately hands back *raw JSON dicts*, not pydantic models,
because it must service the JSON-Schema-based validator in
:mod:`aiopspilot.shared.contracts.validation` before any model coercion.

Naming convention
-----------------
Schema names use forward slashes to match the on-disk / URI layout:

    ``event/1.0.0``
    ``action/1.0.0``
    ``rule/1.0.0``
    ``ontology/object-type/1.0.0``
    ``ontology/link-type/1.0.0``
    ``ontology/action-type/1.0.0``

Callers may omit the version to receive the latest known revision.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# DI seam (Protocol)
# ---------------------------------------------------------------------------


@runtime_checkable
class SchemaRegistry(Protocol):
    """Return raw JSON Schemas by name (and optional version)."""

    def get(self, name: str, version: str | None = None) -> Mapping[str, object]:
        """Return the schema for ``name`` (semver ``version`` optional).

        Implementations MUST raise :class:`SchemaNotFoundError` when the
        requested schema is absent — never return a partial or empty dict.
        """
        ...

    def names(self) -> list[str]:
        """List every ``name`` this registry can serve (unversioned)."""
        ...


class SchemaNotFoundError(LookupError):
    """Raised when a :class:`SchemaRegistry` cannot resolve a name/version."""


# ---------------------------------------------------------------------------
# Upstream default: package-resource loader
# ---------------------------------------------------------------------------


# One entry per shipped schema. The value is the resource path relative to
# ``aiopspilot.shared.contracts``. Only one version per schema is shipped at
# v1.0.0 today; introducing v1.1.0 means adding an entry, not editing v1.0.0.
_PACKAGE_SCHEMAS: dict[tuple[str, str], str] = {
    ("event", "1.0.0"): "event/schema.json",
    ("action", "1.0.0"): "action/schema.json",
    ("rule", "1.0.0"): "rule/schema.json",
    ("ontology/object-type", "1.0.0"): "ontology/object-type.json",
    ("ontology/link-type", "1.0.0"): "ontology/link-type.json",
    ("ontology/action-type", "1.0.0"): "ontology/action-type.json",
}


class PackageResourceSchemaRegistry:
    """Default :class:`SchemaRegistry` — reads schemas shipped in the package.

    This implementation is intentionally minimal: no network, no filesystem
    walk, no caching magic. It exists so ``core/`` has a working seam even
    when a fork has not registered anything.
    """

    def __init__(self, package: str = "aiopspilot.shared.contracts") -> None:
        self._package = package

    def get(self, name: str, version: str | None = None) -> Mapping[str, object]:
        target_version = version or self._latest_version(name)
        if target_version is None:
            raise SchemaNotFoundError(f"unknown schema name: {name!r}")

        rel = _PACKAGE_SCHEMAS.get((name, target_version))
        if rel is None:
            raise SchemaNotFoundError(
                f"unknown schema: name={name!r} version={target_version!r}"
            )

        raw = resources.files(self._package).joinpath(rel).read_text(encoding="utf-8")
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise SchemaNotFoundError(  # pragma: no cover — schema files are dicts
                f"schema {name!r} is not a JSON object"
            )
        return loaded

    def names(self) -> list[str]:
        return sorted({n for (n, _v) in _PACKAGE_SCHEMAS})

    def _latest_version(self, name: str) -> str | None:
        versions = [v for (n, v) in _PACKAGE_SCHEMAS if n == name]
        if not versions:
            return None
        return max(versions, key=_semver_key)


def _semver_key(v: str) -> tuple[int, int, int]:
    major, minor, patch = v.split(".", 2)
    return (int(major), int(minor), int(patch))


__all__ = [
    "PackageResourceSchemaRegistry",
    "SchemaNotFoundError",
    "SchemaRegistry",
]

"""Strict loader for the deterministic weakness-verifier catalog (``verifiers.yaml``).

The catalog lists, per language and weakness class, the sinks a verifier confirms and the sources,
sanitizers, and validation guards its taint analysis honors. Loading fails closed on unknown keys,
a sink without exactly one of ``call`` or ``method``, or a class outside the weakness catalog.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fdai.rule_catalog.code_security import CodeSecurityCatalogError

_DOTTED = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"
_IDENT = r"^[A-Za-z_][A-Za-z0-9_]*$"


Ident = Annotated[str, Field(pattern=_IDENT)]
Dotted = Annotated[str, Field(pattern=_DOTTED)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VerifierLimits(_Strict):
    max_file_bytes: Annotated[int, Field(ge=1_000, le=10_000_000)]
    max_issues: Annotated[int, Field(ge=1, le=100_000)]


class Sink(_Strict):
    call: Dotted | None = None
    method: Ident | None = None
    arg: Annotated[int, Field(ge=0, le=10)]
    require_keyword: dict[Ident, bool] = Field(default_factory=dict)
    unsafe_unless_keyword: dict[Ident, tuple[Ident, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_target(self) -> Sink:
        if (self.call is None) == (self.method is None):
            raise ValueError("a sink names exactly one of call or method")
        return self


class VerifierClass(_Strict):
    sanitizers: tuple[Dotted, ...]
    sinks: Annotated[tuple[Sink, ...], Field(min_length=1)]


class PythonVerifier(_Strict):
    entrypoint_decorators: Annotated[tuple[Ident, ...], Field(min_length=1)]
    safe_parameter_annotations: tuple[Dotted, ...]
    ignored_parameters: tuple[Ident, ...]
    request_roots: Annotated[tuple[Dotted, ...], Field(min_length=1)]
    request_attributes: Annotated[tuple[Ident, ...], Field(min_length=1)]
    source_calls: tuple[Dotted, ...]
    source_attributes: tuple[Dotted, ...]
    global_sanitizers: tuple[Dotted, ...]
    validators: tuple[Ident, ...]
    classes: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")], VerifierClass]


class VerifierCatalog(_Strict):
    schema_version: Literal[1]
    catalog_id: Annotated[str, Field(min_length=3, max_length=128)]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    limits: VerifierLimits
    python: PythonVerifier


def load_verifier_catalog(root: Path, known_classes: frozenset[str]) -> VerifierCatalog:
    """Load ``verifiers.yaml`` and require every class to exist in the weakness catalog."""
    try:
        catalog = VerifierCatalog.model_validate(
            yaml.safe_load((root / "verifiers.yaml").read_text(encoding="utf-8"))
        )
    except FileNotFoundError as exc:
        raise CodeSecurityCatalogError(
            "missing code-security catalog file: verifiers.yaml"
        ) from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise CodeSecurityCatalogError(f"invalid verifier catalog: {exc}") from exc
    unknown = sorted(set(catalog.python.classes) - known_classes)
    if unknown:
        raise CodeSecurityCatalogError(f"verifier catalog names unknown classes: {unknown}")
    return catalog


__all__ = [
    "PythonVerifier",
    "Sink",
    "VerifierCatalog",
    "VerifierClass",
    "VerifierLimits",
    "load_verifier_catalog",
]

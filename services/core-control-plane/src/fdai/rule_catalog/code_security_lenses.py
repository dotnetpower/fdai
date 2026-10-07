"""Strict loader for the LLM lens catalog (``lenses.yaml``).

Lenses parameterize the off-path LLM lane: the system prompt, per-lens focus text, deterministic
sink hints for excerpt selection, allowed CWEs, languages, and hard budgets. Loading fails closed
on unknown keys, regular expressions that do not compile, unknown languages, or a quorum below two.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fdai.rule_catalog.code_security import CodeSecurityCatalogError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LensLimits(_Strict):
    max_candidates_per_lens: Annotated[int, Field(ge=1, le=500)]
    max_model_calls: Annotated[int, Field(ge=1, le=5_000)]
    excerpt_radius: Annotated[int, Field(ge=3, le=200)]
    max_excerpt_bytes: Annotated[int, Field(ge=500, le=100_000)]
    max_file_bytes: Annotated[int, Field(ge=1_000, le=5_000_000)]
    max_files: Annotated[int, Field(ge=1, le=100_000)]
    max_findings_per_response: Annotated[int, Field(ge=1, le=20)]
    quorum: Annotated[int, Field(ge=2, le=5)]
    line_tolerance: Annotated[int, Field(ge=0, le=10)]


class Lens(_Strict):
    weakness_class: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")]
    cwe: Annotated[tuple[int, ...], Field(min_length=1)]
    languages: Annotated[tuple[str, ...], Field(min_length=1)]
    sink_hints: Annotated[tuple[str, ...], Field(min_length=1, max_length=16)]
    focus: Annotated[str, Field(min_length=20, max_length=800)]

    @model_validator(mode="after")
    def _hints_compile(self) -> Lens:
        for hint in self.sink_hints:
            try:
                re.compile(hint)
            except re.error as exc:
                raise ValueError(f"sink hint does not compile: {exc}") from exc
        return self


class LensCatalog(_Strict):
    schema_version: Literal[1]
    catalog_id: Annotated[str, Field(min_length=3, max_length=128)]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    system_prompt: Annotated[str, Field(min_length=50, max_length=4_000)]
    limits: LensLimits
    languages: dict[str, tuple[str, ...]]
    lenses: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")], Lens]

    @model_validator(mode="after")
    def _known_languages(self) -> LensCatalog:
        for lens_id, lens in self.lenses.items():
            unknown = set(lens.languages) - set(self.languages)
            if unknown:
                raise ValueError(f"lens {lens_id} uses unknown languages {sorted(unknown)}")
        return self

    def language_for(self, path: str) -> str | None:
        for language, suffixes in self.languages.items():
            if any(path.endswith(suffix) for suffix in suffixes):
                return language
        return None


def load_lens_catalog(root: Path) -> LensCatalog:
    """Load ``lenses.yaml`` from the code-security catalog root, failing closed."""
    try:
        return LensCatalog.model_validate(
            yaml.safe_load((root / "lenses.yaml").read_text(encoding="utf-8"))
        )
    except FileNotFoundError as exc:
        raise CodeSecurityCatalogError("missing code-security catalog file: lenses.yaml") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise CodeSecurityCatalogError(f"invalid lens catalog: {exc}") from exc


__all__ = ["Lens", "LensCatalog", "LensLimits", "load_lens_catalog"]

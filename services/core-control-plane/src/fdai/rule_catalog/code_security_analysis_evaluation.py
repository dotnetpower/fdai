"""Strict corpus loader for owned code-security analysis evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from fdai.rule_catalog.code_security import CodeSecurityCatalogError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AnalysisEvaluationCase(_Strict):
    case_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")]
    split: Literal["dev", "holdout"]
    vulnerable: bool
    files: Annotated[dict[str, str], Field(min_length=1, max_length=20)]

    @field_validator("files")
    @classmethod
    def _safe_paths(cls, value: dict[str, str]) -> dict[str, str]:
        for raw, source in value.items():
            path = PurePosixPath(raw)
            if (
                path.is_absolute()
                or path.suffix not in {".cs", ".java", ".py", ".ts", ".tsx"}
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise ValueError("evaluation file paths must use an allowed relative source path")
            if not source or len(source.encode("utf-8")) > 100_000:
                raise ValueError("evaluation source must be non-empty and bounded")
        return value


class AnalysisEvaluationCorpus(_Strict):
    schema_version: Literal["1.0.0"]
    corpus_id: Annotated[str, Field(pattern=r"^fdai\.code-security\.analysis\.[a-z-]+$")]
    language: Literal["csharp", "java", "python", "typescript"]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    rule_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9.-]{2,127}$")]
    cases: Annotated[tuple[AnalysisEvaluationCase, ...], Field(min_length=4)]

    @model_validator(mode="after")
    def _balanced_splits(self) -> AnalysisEvaluationCorpus:
        identities = [case.case_id for case in self.cases]
        if len(identities) != len(set(identities)):
            raise ValueError("evaluation case ids must be unique")
        required = {
            (split, vulnerable) for split in ("dev", "holdout") for vulnerable in (True, False)
        }
        observed = {(case.split, case.vulnerable) for case in self.cases}
        if not required <= observed:
            raise ValueError("each evaluation split requires vulnerable and safe cases")
        suffixes = {
            "csharp": {".cs"},
            "java": {".java"},
            "python": {".py"},
            "typescript": {".ts", ".tsx"},
        }[self.language]
        if any(
            PurePosixPath(path).suffix not in suffixes for case in self.cases for path in case.files
        ):
            raise ValueError("evaluation source paths must match the corpus language")
        return self

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


def load_analysis_evaluation_corpus(
    root: Path, name: str = "python-sql-injection"
) -> AnalysisEvaluationCorpus:
    """Load one pinned owned-analysis evaluation corpus by safe catalog name."""
    if not name.replace("-", "").isalnum() or name.startswith("-"):
        raise CodeSecurityCatalogError("invalid analysis evaluation corpus name")
    path = root / "analysis-evaluation" / f"{name}.yaml"
    try:
        return AnalysisEvaluationCorpus.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        )
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CodeSecurityCatalogError(f"invalid analysis evaluation corpus: {exc}") from exc


__all__ = [
    "AnalysisEvaluationCase",
    "AnalysisEvaluationCorpus",
    "load_analysis_evaluation_corpus",
]

"""Reviewed exact-evaluator bindings layered over the generated WARA catalog."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai.rule_catalog.schema.wara_assessment import (
    QuerySafetyClassification,
    ResourceTypeDisposition,
    WaraAssessmentCatalog,
    WaraQueryCatalog,
    canonical_digest,
)

_SHA256 = r"^sha256:[a-f0-9]{64}$"
_UUID = (
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-"
    r"[a-f0-9]{4}-[a-f0-9]{12}$"
)
_GIT_REF = r"^[a-f0-9]{40}$"
_IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{0,255}$"


class WaraEvaluatorSemantics(StrEnum):
    """Supported deterministic interpretations of an exact query result."""

    MATCHING_ROWS_FAILED = "matching_rows_failed"


class WaraEvaluatorBinding(BaseModel):
    """One reviewed evaluator bound to an exact APRL query generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    aprl_guid: Annotated[str, Field(pattern=_UUID)]
    query_digest: Annotated[str, Field(pattern=_SHA256)]
    evaluator_ref: Annotated[str, Field(pattern=_IDENTIFIER)]
    provider: Annotated[str, Field(pattern=r"^azure_resource_graph$")]
    semantics: WaraEvaluatorSemantics
    resource_id_column: Annotated[str, Field(pattern=r"^id$")]
    reviewer: Annotated[str, Field(pattern=_IDENTIFIER)]
    review_state: Annotated[str, Field(pattern=r"^reviewed-exact$")]

    @property
    def key(self) -> tuple[str, str]:
        """Return the exact lookup identity for this reviewed binding."""

        return self.aprl_guid, self.query_digest


class WaraEvaluatorBindingCatalog(BaseModel):
    """Content-addressed overlay of reviewed WARA evaluator bindings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^1\.0\.0$")]
    source_revision: Annotated[str, Field(pattern=_GIT_REF)]
    crosswalk_digest: Annotated[str, Field(pattern=_SHA256)]
    bindings: tuple[WaraEvaluatorBinding, ...]
    overlay_digest: Annotated[str, Field(pattern=_SHA256)]

    @model_validator(mode="after")
    def validate_identity(self) -> WaraEvaluatorBindingCatalog:
        keys = tuple(binding.key for binding in self.bindings)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("WARA evaluator bindings MUST be unique and ordered")
        material = self.model_dump(mode="json")
        material.pop("overlay_digest")
        if self.overlay_digest != canonical_digest(material):
            raise ValueError("WARA evaluator binding overlay digest mismatch")
        return self

    def resolve(self, aprl_guid: str, query_digest: str) -> WaraEvaluatorBinding | None:
        """Resolve only an exact APRL GUID and query-digest pair."""

        return next(
            (binding for binding in self.bindings if binding.key == (aprl_guid, query_digest)),
            None,
        )


def load_wara_evaluator_bindings(
    path: Path,
    *,
    catalog: WaraAssessmentCatalog,
    queries: WaraQueryCatalog,
) -> WaraEvaluatorBindingCatalog:
    """Load an overlay and reject any drift from the generated WARA catalogs."""

    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    overlay = WaraEvaluatorBindingCatalog.model_validate(raw)
    if overlay.source_revision != catalog.source_revision:
        raise ValueError("WARA evaluator bindings source revision mismatch")
    if overlay.crosswalk_digest != catalog.crosswalk_digest:
        raise ValueError("WARA evaluator bindings crosswalk digest mismatch")

    records = {record.aprl_guid: record for record in catalog.recommendations}
    query_bodies = {query.aprl_guid: query for query in queries.queries}
    for binding in overlay.bindings:
        record = records.get(binding.aprl_guid)
        query = query_bodies.get(binding.aprl_guid)
        if record is None or query is None or record.query_review is None:
            raise ValueError(f"{binding.aprl_guid}: evaluator binding has no generated query")
        review = record.query_review
        if binding.query_digest != review.body_digest or binding.query_digest != query.body_digest:
            raise ValueError(f"{binding.aprl_guid}: evaluator binding query digest mismatch")
        if review.safety_classification is not QuerySafetyClassification.READ_ONLY_BOUNDED:
            raise ValueError(
                f"{binding.aprl_guid}: evaluator binding query is not read-only bounded"
            )
        if review.declared_tables != ("resources",):
            raise ValueError(f"{binding.aprl_guid}: evaluator binding requires Resources coverage")
        if record.applicability.disposition is not ResourceTypeDisposition.CANONICAL:
            raise ValueError(
                f"{binding.aprl_guid}: evaluator binding resource type is not canonical"
            )
        if review.evaluator_ref is not None:
            raise ValueError(f"{binding.aprl_guid}: generated catalog already binds an evaluator")
        if set(review.blocked_reasons) != {"missing_exact_evaluator"}:
            raise ValueError(f"{binding.aprl_guid}: evaluator binding would hide other blockers")
    return overlay


__all__ = [
    "WaraEvaluatorBinding",
    "WaraEvaluatorBindingCatalog",
    "WaraEvaluatorSemantics",
    "load_wara_evaluator_bindings",
]

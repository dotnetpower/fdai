"""Content-addressed, reviewed installation choices for shadow assessment."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$")]


class ControlEnablementOverride(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    control_id: Identifier
    enabled: bool


class ControlEnablementProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    framework_id: Literal["azure-waf", "azure-wara", "azure-caf", "azure-mcsb"]
    source_revision: Annotated[str, Field(min_length=1, max_length=256)]
    scope_digest: Digest
    reviewed_by: Identifier
    reviewed_at: datetime
    overrides: tuple[ControlEnablementOverride, ...] = Field(min_length=1, max_length=1_000)
    profile_digest: Digest

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if self.reviewed_at.tzinfo is None:
            raise ValueError("control enablement review time MUST be timezone-aware")
        identifiers = tuple(item.control_id for item in self.overrides)
        if identifiers != tuple(sorted(set(identifiers))):
            raise ValueError("control enablement overrides MUST be unique and ordered")
        if self.profile_digest != self.digest_material(self.model_dump(mode="json")):
            raise ValueError("control enablement profile digest mismatch")
        return self

    @staticmethod
    def digest_material(material: dict[str, object]) -> str:
        value = {key: item for key, item in material.items() if key != "profile_digest"}
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()

    def validate_binding(
        self,
        *,
        framework_id: str,
        source_revision: str,
        scope_digest: str,
        evaluated_at: datetime,
        control_ids: set[str],
    ) -> None:
        if evaluated_at.tzinfo is None:
            raise ValueError("control evaluation time MUST be timezone-aware")
        if (
            self.framework_id != framework_id
            or self.source_revision != source_revision
            or self.scope_digest != scope_digest
        ):
            raise ValueError("control enablement profile binding mismatch")
        if self.reviewed_at > evaluated_at:
            raise ValueError("control enablement review is outside the evaluation cutoff")
        if not {item.control_id for item in self.overrides}.issubset(control_ids):
            raise ValueError("control enablement profile references an unknown control")

    def override_for(self, control_id: str) -> bool | None:
        return next(
            (item.enabled for item in self.overrides if item.control_id == control_id),
            None,
        )


class ControlEnablementProfiles(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"]
    profiles: tuple[ControlEnablementProfile, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_frameworks(self) -> Self:
        frameworks = [profile.framework_id for profile in self.profiles]
        if len(set(frameworks)) != len(frameworks):
            raise ValueError("control enablement bundle contains duplicate frameworks")
        return self

    def for_framework(self, framework_id: str) -> ControlEnablementProfile | None:
        return next((item for item in self.profiles if item.framework_id == framework_id), None)

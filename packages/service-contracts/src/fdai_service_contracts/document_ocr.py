"""Authority-free settings contract for document OCR provider selection."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentOcrProvider(StrEnum):
    LOCAL_PYTHON = "local_python"
    AZURE_DOCUMENT_INTELLIGENCE = "azure_document_intelligence"


class DocumentOcrResourceState(StrEnum):
    ABSENT = "absent"
    PLAN_REQUIRED = "plan-required"
    PLAN_REQUESTED = "plan-requested"
    PROVISIONING = "provisioning"
    VERIFYING = "verifying"
    READY = "ready"
    DRAINING = "draining"
    FAILED = "failed"


class DocumentOcrPolicy(BaseModel):
    """One revisioned desired provider policy with no deployment authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    environment: Literal["dev", "staging", "prod"]
    revision: Annotated[int, Field(ge=1)]
    desired_provider: DocumentOcrProvider
    azure_resource_desired: bool
    deprovision_requested: bool = False

    @model_validator(mode="after")
    def _validate_resource_intent(self) -> DocumentOcrPolicy:
        azure = self.desired_provider is DocumentOcrProvider.AZURE_DOCUMENT_INTELLIGENCE
        if azure and not self.azure_resource_desired:
            raise ValueError("Azure provider requires Azure resource intent")
        if self.deprovision_requested and (azure or self.azure_resource_desired):
            raise ValueError("deprovision requires local provider and no Azure resource intent")
        return self

    def digest(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True)
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

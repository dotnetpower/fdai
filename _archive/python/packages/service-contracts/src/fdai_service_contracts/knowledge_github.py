"""Authority-free GitHub knowledge source and connection request contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALIAS_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
LOCATION_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$"
CredentialReference = Literal["public", "deployment-github-app"]


class GitHubKnowledgeSource(BaseModel):
    """A bounded provider observation, never scan consent or indexing evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    credential_reference: CredentialReference
    knowledge_read_enabled: bool
    repository_id: int = Field(gt=0)
    private: bool
    observed_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    readme_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: str
    request_id: str = Field(pattern=r"^operator-[0-9a-f]{32}$")

    @field_validator("observed_at")
    @classmethod
    def _aware_time(cls, value: str) -> str:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("observation time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _public_scope(self) -> GitHubKnowledgeSource:
        if self.credential_reference == "public" and self.private:
            raise ValueError("anonymous access cannot verify a private repository")
        return self


class GitHubKnowledgeChangeBody(BaseModel):
    """Owner intent with an exact revision; no credentials or scan permission fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action: Literal["connect", "disconnect"]
    repository_alias: str = Field(pattern=ALIAS_PATTERN)
    expected_revision: int = Field(ge=0)
    location: str | None = Field(default=None, pattern=LOCATION_PATTERN)
    credential_reference: CredentialReference | None = None

    @model_validator(mode="after")
    def _action_fields(self) -> GitHubKnowledgeChangeBody:
        if self.action == "connect":
            if self.location is None or self.credential_reference is None:
                raise ValueError("connect requires repository and credential reference")
            if self.location.split("/")[1] in {".", ".."}:
                raise ValueError("repository name is invalid")
        elif self.location is not None or self.credential_reference is not None:
            raise ValueError("disconnect takes only alias and expected revision")
        elif self.expected_revision == 0:
            raise ValueError("disconnect requires an existing revision")
        return self

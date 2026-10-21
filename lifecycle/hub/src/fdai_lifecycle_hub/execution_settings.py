"""Bounded operator requests for scheduling an already enrolled installation."""

from __future__ import annotations

from datetime import time, timedelta
from uuid import UUID

from fdai_deployment_cli.contracts import canonical_digest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fdai_lifecycle_hub.domain import DailyWindow, Settings
from fdai_lifecycle_hub.schemas import maintenance_window_record, settings_json


class ExecutionSettingsError(ValueError):
    pass


class WindowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start: time
    duration_minutes: float = Field(ge=1, le=1440, allow_inf_nan=False)
    timezone: str = Field(min_length=1, max_length=128)
    allows_downtime: bool = False

    def to_window(self) -> DailyWindow:
        return DailyWindow(
            self.start,
            timedelta(minutes=self.duration_minutes),
            self.timezone,
            allows_downtime=self.allows_downtime,
        )

    @model_validator(mode="after")
    def validate_window(self) -> WindowRequest:
        self.to_window()
        return self


class SettingsChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: UUID
    expected_settings_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    confirmation: str = Field(min_length=1, max_length=256)

    @property
    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


class ExecutionSettingsRequest(SettingsChangeRequest):
    windows: tuple[WindowRequest, ...] = Field(max_length=32)
    plan_duration_minutes: int = Field(ge=1, le=1440)


class ApplicationBindingRequest(SettingsChangeRequest):
    product: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")


def settings_digest(settings: Settings) -> str:
    fields = settings_json.dump_python(settings, mode="json")
    fields["allowed_regions"] = sorted(settings.allowed_regions)
    return canonical_digest(fields)


def settings_record(settings: Settings) -> dict[str, object]:
    return {
        "settings_digest": settings_digest(settings),
        "product": settings.product,
        "windows": [maintenance_window_record(window) for window in settings.windows],
        "plan_duration_minutes": settings.plan_duration_minutes,
    }

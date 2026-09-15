"""Inert, durable Trial records and monotonic transitions; not entitlement authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

TRIAL_DURATION = timedelta(days=30)
_DIGEST = re.compile(r"[0-9a-f]{64}")


class TrialStatus(StrEnum):
    """Recorded usage state, independent from promotion or execution authorization."""

    ACTIVE = "trial-active"
    EXPIRED = "trial-expired"
    CLOCK_BLOCKED = "trial-clock-blocked"


@dataclass(frozen=True, slots=True)
class TrialRecord:
    """One installation-bound time window persisted by the deployment-owned writer.

    Construction validates structure only. A caller must obtain this record from an
    authenticated durable store; parsing or creating one never grants capability access.
    """

    installation_binding: str
    deployment_binding: str
    activated_at: datetime
    last_observed_at: datetime
    revision: int = 1
    clock_blocked: bool = False

    def __post_init__(self) -> None:
        for binding in (self.installation_binding, self.deployment_binding):
            if not isinstance(binding, str) or _DIGEST.fullmatch(binding) is None:
                raise ValueError("Trial requires exact installation and deployment digests")
        for moment in (self.activated_at, self.last_observed_at):
            _require_utc(moment)
        if self.last_observed_at < self.activated_at:
            raise ValueError("Trial observation cannot precede activation")
        if (
            type(self.revision) is not int
            or self.revision < 1
            or type(self.clock_blocked) is not bool
        ):
            raise ValueError("Trial revision or clock state is invalid")
        if (
            self.activated_at
            > datetime.max.replace(tzinfo=self.activated_at.tzinfo) - TRIAL_DURATION
        ):
            raise ValueError("Trial activation is outside the supported time range")

    @property
    def expires_at(self) -> datetime:
        """Derive expiry from activation; callers cannot supply a longer window."""
        try:
            return self.activated_at + TRIAL_DURATION
        except OverflowError:
            raise ValueError("Trial activation is outside the supported time range") from None

    @property
    def status(self) -> TrialStatus:
        """Describe the durable observation, not eligibility at an unobserved later time."""
        if self.clock_blocked:
            return TrialStatus.CLOCK_BLOCKED
        if self.last_observed_at >= self.expires_at:
            return TrialStatus.EXPIRED
        return TrialStatus.ACTIVE

    def observe(self, *, now: datetime) -> TrialRecord:
        """Return the next CAS candidate while preserving activation and clock denial.

        The store must compare the complete previous revision and commit this result
        before availability is evaluated. No write, retry, or authorization occurs here.
        """
        _require_utc(now)
        return replace(
            self,
            last_observed_at=max(now, self.last_observed_at),
            revision=self.revision + 1,
            clock_blocked=self.clock_blocked or now < self.last_observed_at,
        )

    def to_mapping(self) -> dict[str, object]:
        """Return portable state with no credentials, raw tenant identity or source pin."""
        return {
            "schema_version": "fdai.trial-record.v1",
            "installation_binding": self.installation_binding,
            "deployment_binding": self.deployment_binding,
            "activated_at": self.activated_at.isoformat(),
            "last_observed_at": self.last_observed_at.isoformat(),
            "revision": self.revision,
            "clock_blocked": self.clock_blocked,
        }

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> TrialRecord:
        """Decode exact durable state without repairing fields or restarting its clock."""
        expected = {
            "schema_version",
            "installation_binding",
            "deployment_binding",
            "activated_at",
            "last_observed_at",
            "revision",
            "clock_blocked",
        }
        if set(value) != expected or value["schema_version"] != "fdai.trial-record.v1":
            raise ValueError("Trial record schema is invalid")
        installation, deployment = value["installation_binding"], value["deployment_binding"]
        activated, observed = value["activated_at"], value["last_observed_at"]
        revision, blocked = value["revision"], value["clock_blocked"]
        if (
            not isinstance(installation, str)
            or not isinstance(deployment, str)
            or not isinstance(activated, str)
            or not isinstance(observed, str)
        ):
            raise ValueError("Trial record field types are invalid")
        if type(revision) is not int or type(blocked) is not bool:
            raise ValueError("Trial record field types are invalid")
        record = cls(
            installation,
            deployment,
            datetime.fromisoformat(activated),
            datetime.fromisoformat(observed),
            revision,
            blocked,
        )
        if record.to_mapping() != value:
            raise ValueError("Trial record timestamps must use canonical UTC encoding")
        return record


def _require_utc(moment: datetime) -> None:
    if (
        not isinstance(moment, datetime)
        or moment.tzinfo is None
        or moment.utcoffset() != timedelta(0)
    ):
        raise ValueError("Trial timestamps must use explicit UTC")

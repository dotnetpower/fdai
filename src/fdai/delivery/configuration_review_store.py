"""StateStore-backed durable configuration review campaigns."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.core.detection.configuration_drift_models import DriftVerdict
from fdai.core.detection.configuration_review import (
    ConfigurationReviewCampaign,
    ConfigurationReviewRun,
    ConfigurationReviewState,
)
from fdai.shared.providers.state_store import StateStore

_PREFIX = "configuration-review:"


def configuration_review_campaign_id(*, scope: str, version: str) -> str:
    digest = hashlib.sha256(f"{scope}\0{version}".encode()).hexdigest()[:32]
    return f"configuration-review-{digest}"


class StateStoreConfigurationReviewCampaignStore:
    """Persist campaigns with StateStore create/CAS and append-only audit."""

    def __init__(
        self,
        store: StateStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._store = store
        self._clock = clock

    async def get(self, campaign_id: str) -> ConfigurationReviewCampaign | None:
        raw = await self._store.read_state(_key(campaign_id))
        return None if raw is None else _decode(raw)

    async def create(self, campaign: ConfigurationReviewCampaign) -> bool:
        return await self._store.write_state_with_audit_if_absent(
            _key(campaign.campaign_id),
            _encode(campaign),
            _audit(campaign, action="configuration_review.created", at=self._clock()),
        )

    async def replace(
        self,
        campaign: ConfigurationReviewCampaign,
        *,
        expected_revision: int,
    ) -> bool:
        return await self._store.compare_and_set_state_with_audit(
            _key(campaign.campaign_id),
            _encode(campaign),
            expected_revision=expected_revision,
            audit_entry=_audit(
                campaign,
                action="configuration_review.advanced",
                at=self._clock(),
            ),
        )


def _key(campaign_id: str) -> str:
    return f"{_PREFIX}{campaign_id}"


def _encode(campaign: ConfigurationReviewCampaign) -> dict[str, Any]:
    return {
        "schema_version": "1.1.0",
        "campaign_id": campaign.campaign_id,
        "baseline_version": campaign.baseline_version,
        "baseline_sha256": campaign.baseline_sha256,
        "scope": campaign.scope,
        "run_limit": campaign.run_limit,
        "required_successes": campaign.required_successes,
        "state": campaign.state.value,
        "revision": campaign.revision,
        "runs": [_encode_run(run) for run in campaign.runs],
        "failed_attempts": [
            [_encode_run(run) for run in attempt] for attempt in campaign.failed_attempts
        ],
    }


def _decode(raw: Mapping[str, Any]) -> ConfigurationReviewCampaign:
    runs_raw = raw.get("runs")
    if raw.get("schema_version") not in {"1.0.0", "1.1.0"} or not isinstance(runs_raw, list):
        raise ValueError("configuration review campaign state is invalid")
    runs = [_decode_run(item) for item in runs_raw]
    attempts_raw = raw.get("failed_attempts", [])
    if not isinstance(attempts_raw, list):
        raise ValueError("configuration review failed attempts are invalid")
    failed_attempts: list[tuple[ConfigurationReviewRun, ...]] = []
    for attempt in attempts_raw:
        if not isinstance(attempt, list):
            raise ValueError("configuration review failed attempt is invalid")
        failed_attempts.append(tuple(_decode_run(item) for item in attempt))
    return ConfigurationReviewCampaign(
        campaign_id=_text(raw, "campaign_id"),
        baseline_version=_text(raw, "baseline_version"),
        baseline_sha256=_text(raw, "baseline_sha256"),
        scope=_text(raw, "scope"),
        run_limit=_int(raw, "run_limit"),
        required_successes=_int(raw, "required_successes"),
        state=ConfigurationReviewState(_text(raw, "state")),
        runs=tuple(runs),
        failed_attempts=tuple(failed_attempts),
        revision=_int(raw, "revision"),
    )


def _encode_run(run: ConfigurationReviewRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "observed_at": run.observed_at.isoformat(),
        "verdict": run.verdict.value,
        "verified": run.verified,
        "evidence_refs": list(run.evidence_refs),
    }


def _decode_run(item: object) -> ConfigurationReviewRun:
    if not isinstance(item, Mapping):
        raise ValueError("configuration review run state is invalid")
    refs = item.get("evidence_refs")
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise ValueError("configuration review evidence refs are invalid")
    return ConfigurationReviewRun(
        run_id=_text(item, "run_id"),
        observed_at=datetime.fromisoformat(_text(item, "observed_at")),
        verdict=DriftVerdict(_text(item, "verdict")),
        verified=_bool(item, "verified"),
        evidence_refs=tuple(refs),
    )


def _audit(
    campaign: ConfigurationReviewCampaign,
    *,
    action: str,
    at: datetime,
) -> dict[str, Any]:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("configuration review audit clock MUST be timezone-aware")
    return {
        "event_id": f"{campaign.campaign_id}:{campaign.revision}",
        "action": action,
        "campaign_id": campaign.campaign_id,
        "revision": campaign.revision,
        "state": campaign.state.value,
        "baseline_sha256": campaign.baseline_sha256,
        "timestamp": at.isoformat(),
    }


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"configuration review {key} is invalid")
    return value


def _int(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"configuration review {key} is invalid")
    return value


def _bool(raw: Mapping[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"configuration review {key} is invalid")
    return value


__all__ = [
    "StateStoreConfigurationReviewCampaignStore",
    "configuration_review_campaign_id",
]

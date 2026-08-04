"""Inert scheduler blueprint projection for ready configuration reviews."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from fdai.core.detection.configuration_review import ConfigurationReviewScheduleProposal
from fdai.core.scheduler.blueprints.models import AutomationBlueprintCandidate
from fdai.core.scheduler.models import ScheduledRunIsolationProfile


def configuration_review_blueprint(
    proposal: ConfigurationReviewScheduleProposal,
    *,
    proposer: str,
    now: datetime,
) -> AutomationBlueprintCandidate:
    """Project exact review evidence into a disabled shadow-only candidate."""

    identity = _digest(
        proposal.campaign_id,
        proposal.baseline_version,
        proposal.baseline_sha256,
        proposal.scope,
        proposal.cron_expression,
        proposal.timezone,
        *proposal.evidence_run_ids,
    )
    evidence = tuple(
        _digest(proposal.baseline_sha256, proposal.campaign_id, run_id)
        for run_id in proposal.evidence_run_ids
    )
    return AutomationBlueprintCandidate(
        candidate_id=f"configuration-review-{identity[:32]}",
        dedup_key=_digest(proposal.scope, proposal.baseline_version, "weekly"),
        normalized_task_intent=(
            f"Run the pinned configuration drift check for baseline {proposal.baseline_version}."
        ),
        schedule_class="cron",
        schedule_expression=proposal.cron_expression,
        event_type="configuration.drift.check.requested",
        principal_id=proposer,
        resource_scope=f"scope://configuration/{_digest(proposal.scope)[:32]}",
        delivery_intent="configuration-drift-audit",
        required_tools=(),
        isolation_profile=ScheduledRunIsolationProfile(),
        estimated_cost_microusd=0,
        evidence_fingerprints=evidence,
        proposer=proposer,
        confidence=1.0,
        created_at=now,
        expires_at=now + timedelta(days=30),
    )


def _digest(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode()).hexdigest()


__all__ = ["configuration_review_blueprint"]

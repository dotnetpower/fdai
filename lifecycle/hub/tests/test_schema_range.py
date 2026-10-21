"""Exact schema refusal boundaries at the real Hub planning entry point."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.domain import Installation, Issued, NoEligibleRelease
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.signing import HubSigningKey


@pytest.mark.parametrize(
    ("revision", "reason"),
    [
        (11, "schema_revision_outside_tolerated_range"),
        (12, None),
        (15, None),
        (16, "schema_target_not_forward"),
        (17, "schema_revision_outside_tolerated_range"),
    ],
)
def test_reported_schema_is_checked_before_hub_plan_issuance(
    installation: Installation,
    catalog: ReleaseCatalog,
    key: HubSigningKey,
    now: datetime,
    revision: int,
    reason: str | None,
) -> None:
    release = catalog.releases["1.6.0"]
    assert release.schema_target == 15
    assert release.schema_range is not None
    assert (release.schema_range.minimum, release.schema_range.maximum) == (12, 16)
    current = replace(
        installation, reported=replace(installation.reported, schema_revision=revision)
    )
    outcome = plan_next(current, now, catalog=catalog, key=key)
    if reason is None:
        assert isinstance(outcome, Issued)
        assert outcome.plan.target_release_id == "1.6.0"
        key.public_key.verify(outcome.plan.signature, outcome.plan.signed_payload)
    else:
        assert isinstance(outcome, NoEligibleRelease)
        assert outcome.checks
        assert all(
            reason in {block.reason_code for block in check.blocks} for check in outcome.checks
        )

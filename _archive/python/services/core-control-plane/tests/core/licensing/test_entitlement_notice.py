"""Watermark notice derivation tests.

The notice decides only what the Console says. These prove that only the acting
capability hides it and that every withheld state maps to one of the two notices.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.executor.licensing_gate import MUTATION_CAPABILITY_ID
from fdai.core.licensing.entitlement import Entitlement, LicenseStatus
from fdai.core.licensing.entitlement_notice import (
    ACTING_CAPABILITY_ID,
    EntitlementNotice,
    entitlement_notice,
)

_READ_ONLY = frozenset({"cost.metering"})
_ACTING = frozenset({"cost.metering", ACTING_CAPABILITY_ID})


def test_the_notice_uses_the_capability_the_execution_ceiling_checks() -> None:
    assert ACTING_CAPABILITY_ID == MUTATION_CAPABILITY_ID


@pytest.mark.parametrize(
    "status",
    [LicenseStatus.ACTIVE, LicenseStatus.ISSUER_WORKSTATION, LicenseStatus.ABSENT],
)
def test_only_the_acting_capability_hides_the_watermark(status: LicenseStatus) -> None:
    entitlement = Entitlement(status=status, available_capability_ids=_ACTING)

    assert entitlement_notice(entitlement) is EntitlementNotice.NONE


def test_an_active_status_without_the_acting_capability_still_shows_it() -> None:
    entitlement = Entitlement(status=LicenseStatus.ACTIVE, available_capability_ids=_READ_ONLY)

    assert entitlement_notice(entitlement) is EntitlementNotice.NOT_ACTIVATED


def test_an_expired_token_or_ended_trial_reads_as_an_ended_evaluation() -> None:
    entitlement = Entitlement(
        status=LicenseStatus.EXPIRED,
        available_capability_ids=_READ_ONLY,
        not_after=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert entitlement_notice(entitlement) is EntitlementNotice.EVALUATION_ENDED


@pytest.mark.parametrize(
    "status",
    [
        LicenseStatus.ABSENT,
        LicenseStatus.UNTRUSTED,
        LicenseStatus.NOT_YET_VALID,
        LicenseStatus.MISBOUND,
    ],
)
def test_every_other_withheld_state_reads_as_not_activated(status: LicenseStatus) -> None:
    entitlement = Entitlement(status=status, available_capability_ids=_READ_ONLY)

    assert entitlement_notice(entitlement) is EntitlementNotice.NOT_ACTIVATED


def test_the_notice_vocabulary_is_closed() -> None:
    assert {notice.value for notice in EntitlementNotice} == {
        "none",
        "evaluation-ended",
        "not-activated",
    }

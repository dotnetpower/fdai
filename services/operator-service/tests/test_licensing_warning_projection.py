"""Focused tests for secret-free Operator licensing status and renewal warning projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai_operator_service.licensing_warning_projection import (
    LicensingWarningProjection,
    LicensingWarningState,
    build_licensing_warning_projection,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def test_requires_authenticated_principal() -> None:
    with pytest.raises(PermissionError, match="authenticated principal"):
        build_licensing_warning_projection(
            principal_id="",
            license_status="active",
            acting_available=True,
            observed_at=NOW,
            now=NOW,
        )


def test_projects_normal_and_expiring_soon_states() -> None:
    normal = build_licensing_warning_projection(
        principal_id="operator-reader-1",
        license_status="active",
        acting_available=True,
        license_id="lic-2026-11",
        expires_at=NOW + timedelta(days=20),
        observed_at=NOW,
        now=NOW,
    )
    assert normal.state is LicensingWarningState.NORMAL
    assert normal.proactive_warning is False
    assert normal.acting_available is True
    assert normal.watermark_notice == "none"
    assert normal.remaining_days == 20
    assert normal.read_only is True
    assert normal.authority == "none"
    assert normal.secret_free is True

    expiring = build_licensing_warning_projection(
        principal_id="operator-reader-1",
        license_status="active",
        acting_available=True,
        license_id="lic-2026-11",
        expires_at=NOW + timedelta(days=3, hours=2),
        observed_at=NOW,
        now=NOW,
    )
    assert expiring.state is LicensingWarningState.EXPIRING_SOON
    assert expiring.proactive_warning is True
    assert expiring.acting_available is True
    assert expiring.watermark_notice == "none"
    assert expiring.remaining_days == 4


def test_projects_expired_clock_regression_and_read_only_trial_states() -> None:
    expired = build_licensing_warning_projection(
        principal_id="operator-reader-1",
        license_status="expired",
        acting_available=False,
        license_id="lic-2026-10",
        expires_at=NOW - timedelta(hours=1),
        observed_at=NOW,
        now=NOW,
    )
    assert expired.state is LicensingWarningState.EXPIRED
    assert expired.acting_available is False
    assert expired.proactive_warning is True
    assert expired.watermark_notice == "evaluation-ended"
    assert expired.remaining_seconds == 0

    clock_reg = build_licensing_warning_projection(
        principal_id="operator-reader-1",
        license_status="absent",
        acting_available=False,
        clock_blocked=True,
        observed_at=NOW,
        now=NOW,
    )
    assert clock_reg.state is LicensingWarningState.CLOCK_REGRESSION
    assert clock_reg.acting_available is False
    assert clock_reg.proactive_warning is True
    assert clock_reg.watermark_notice == "not-activated"

    stale_obs = build_licensing_warning_projection(
        principal_id="operator-reader-1",
        license_status="active",
        acting_available=True,
        observed_at=NOW - timedelta(minutes=10),
        now=NOW,
    )
    assert stale_obs.state is LicensingWarningState.READ_ONLY_TRIAL
    assert stale_obs.acting_available is False
    assert stale_obs.watermark_notice == "not-activated"


def test_rejects_raw_tokens_private_keys_and_signatures() -> None:
    with pytest.raises(ValueError, match="secret or token keys"):
        build_licensing_warning_projection(
            principal_id="operator-reader-1",
            license_status="active",
            acting_available=True,
            observed_at=NOW,
            now=NOW,
            raw_metadata={"token": "x"},
        )

    with pytest.raises(ValueError, match="secret-like"):
        build_licensing_warning_projection(
            principal_id="operator-reader-1",
            license_status="active",
            acting_available=True,
            license_id=" ".join(("-----BEGIN", "PRIVATE KEY-----")),
            observed_at=NOW,
            now=NOW,
        )

    with pytest.raises(ValueError, match="token or key material"):
        LicensingWarningProjection(
            principal_id="operator-reader-1",
            state=LicensingWarningState.NORMAL,
            license_status="active",
            watermark_notice="none",
            acting_available=True,
            proactive_warning=False,
            license_id="eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.c2lnbmF0dXJlX2J5dGVzX2hlcmU",
            observed_at=NOW,
            reason_code="entitlement_active",
        )

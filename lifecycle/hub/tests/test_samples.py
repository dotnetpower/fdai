"""The README walkthrough uses `samples/`, so those files must keep producing its results."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fdai_lifecycle_hub.catalog import load_catalog
from fdai_lifecycle_hub.domain import Issued, UpToDate
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.schemas import installation_json, reported_state_json
from fdai_lifecycle_hub.signing import HubSigningKey

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_samples_issue_then_report_up_to_date(key: HubSigningKey, now: datetime) -> None:
    catalog = load_catalog(SAMPLES / "catalog")
    installation = installation_json.validate_json((SAMPLES / "installation.json").read_bytes())
    upgraded = reported_state_json.validate_json((SAMPLES / "state-1.6.0.json").read_bytes())

    first = plan_next(installation, now, catalog=catalog, key=key)
    after = plan_next(installation.with_reported(upgraded), now, catalog=catalog, key=key)

    assert isinstance(first, Issued)
    assert first.plan.target_release_id == "1.6.0"
    assert after == UpToDate()

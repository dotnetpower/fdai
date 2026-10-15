from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from scripts.deployment.azure.verify_canary_audit import (
    CanaryAuditVerificationError,
    DatabaseConfig,
    capture_canary_audit,
    verify_canary_audit,
)

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = (ROOT / ".github/workflows/deploy-dev.yml").read_text(encoding="utf-8")
RUNNER = (ROOT / "scripts/deployment/azure/run-canary-smoke.sh").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
SLOT = "deploy-100-2"


def _entry(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "event_id": str(uuid5(NAMESPACE_URL, f"fdai.canary://{SLOT}")),
        "correlation_id": f"canary:{SLOT}",
        "idempotency_key": f"canary:{SLOT}",
        "actor": "fdai.canary-job",
        "action_kind": "control_loop.canary",
        "mode": "shadow",
        "tier": "canary",
        "decision": "no-op",
        "outcome": "success",
        "latency_ms": 4200,
        "recorded_at": (NOW - timedelta(seconds=1)).isoformat(),
    }
    values.update(overrides)
    return values


def _config() -> DatabaseConfig:
    return DatabaseConfig(
        host="postgres.example.com",
        database="fdai",
        user="deployment-reader",
        password="not-a-real-secret",
    )


def test_valid_consumed_audit_produces_authority_free_receipt() -> None:
    receipt = verify_canary_audit(
        _entry(),
        slot=SLOT,
        latency_budget_ms=30_000,
        verified_at=NOW,
    )

    assert receipt["evidence_kind"] == "control_loop_canary_consumed_audit"
    assert receipt["latency_ms"] == 4200
    assert receipt["within_budget"] is True
    assert receipt["execution_authority"] is False
    assert "password" not in receipt


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"actor": "publisher-job"}, "actor does not match"),
        ({"outcome": "published"}, "outcome does not match"),
        ({"mode": "enforce"}, "mode does not match"),
        ({"latency_ms": True}, "latency_ms MUST be"),
        ({"latency_ms": 30_001}, "exceeded the latency budget"),
        ({"recorded_at": (NOW + timedelta(seconds=1)).isoformat()}, "from the future"),
    ),
)
def test_malformed_or_unsettled_audit_fails_closed(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(CanaryAuditVerificationError, match=message):
        verify_canary_audit(
            _entry(**overrides),
            slot=SLOT,
            latency_budget_ms=30_000,
            verified_at=NOW,
        )


def test_capture_waits_for_one_row_and_rejects_ambiguous_rows() -> None:
    reads = iter(((), (_entry(),)))
    sleeps: list[float] = []
    ticks = iter((0.0, 0.0, 1.0))

    receipt = capture_canary_audit(
        config=_config(),
        slot=SLOT,
        latency_budget_ms=30_000,
        timeout_seconds=5,
        poll_interval_seconds=1,
        reader=lambda *_args, **_kwargs: next(reads),
        monotonic=lambda: next(ticks),
        sleeper=sleeps.append,
        clock=lambda: NOW,
    )

    assert receipt["correlation_id"] == f"canary:{SLOT}"
    assert sleeps == [1]

    with pytest.raises(CanaryAuditVerificationError, match="ambiguous"):
        capture_canary_audit(
            config=_config(),
            slot=SLOT,
            latency_budget_ms=30_000,
            timeout_seconds=5,
            poll_interval_seconds=1,
            reader=lambda *_args, **_kwargs: (_entry(), _entry()),
            monotonic=lambda: 0,
            clock=lambda: NOW,
        )


def test_database_config_reports_names_without_secret_values() -> None:
    with pytest.raises(CanaryAuditVerificationError, match="database, password") as error:
        DatabaseConfig.from_env(
            {
                "FDAI_CANARY_POSTGRES_HOST": "postgres.example.com",
                "FDAI_CANARY_POSTGRES_DATABASE": "",
                "TF_VAR_postgres_admin_login": "deployment-reader",
                "TF_VAR_postgres_admin_password": "",
            }
        )

    assert "deployment-reader" not in str(error.value)


def test_deploy_workflow_uses_deterministic_slot_and_consumed_audit_verifier() -> None:
    block = WORKFLOW.split("- name: Run canary publisher smoke", maxsplit=1)[1].split(
        "      - name:", maxsplit=1
    )[0]

    assert "bash ../scripts/deployment/azure/run-canary-smoke.sh" in block
    assert 'slot="deploy-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"' in RUNNER
    assert '--env-vars "FDAI_CANARY_SLOT=$slot"' in RUNNER
    assert "--query name -o tsv" in RUNNER
    assert "containerapp job execution list" not in RUNNER
    assert 'FDAI_CANARY_POSTGRES_HOST="$(terraform output -raw postgres_fqdn)"' in RUNNER
    assert 'FDAI_CANARY_POSTGRES_DATABASE="$(terraform output -raw postgres_database)"' in RUNNER
    assert "verify_canary_audit.py" in RUNNER
    assert "--latency-budget-ms 30000" in RUNNER
    assert "--timeout-seconds 60" in RUNNER
    assert "POSTGRES_ADMIN_PASSWORD" not in RUNNER

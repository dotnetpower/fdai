#!/usr/bin/env python3
"""Run the shared Cost Analytics schedule with the operator's Azure CLI identity."""

from __future__ import annotations

import os
import subprocess
import sys

from fdai_cost_governance.job_cli import analytics_main, run_analytics_from_environment


def _configure_local_environment() -> None:
    os.environ.setdefault("FDAI_EXECUTION_VENUE", "local")
    state_dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
    if state_dsn:
        os.environ.setdefault("FDAI_COST_STORE_DSN", state_dsn)
    if os.environ.get("FDAI_COST_SCOPE_ID", "").strip():
        return
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
    if not subscription_id:
        result = subprocess.run(
            ["az", "account", "show", "--query", "id", "--output", "tsv"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        subscription_id = result.stdout.strip()
    if not subscription_id:
        raise RuntimeError("Azure CLI returned no active subscription")
    os.environ.setdefault("FDAI_COST_SCOPE_ID", f"subscriptions/{subscription_id}")


async def collect(days: int) -> dict[str, object]:
    """Retain the original one-shot API while using the shared implementation."""

    _configure_local_environment()
    result = await run_analytics_from_environment(os.environ, days=days)
    receipt = result.receipt
    status = receipt.status.value
    if status in {"complete", "partial"}:
        status = "stored" if result.snapshot_stored else "already-stored"
    return {
        "status": status,
        "run_id": receipt.run_id,
        "trend_points": receipt.trend_point_count,
        "budgets": receipt.budget_count,
        "recommendations": receipt.recommendation_count,
        "utilization_samples": receipt.utilization_count,
        "observations": receipt.observation_count,
        "published": result.published,
        "complete": receipt.status.value == "complete",
        "limitations": list(receipt.limitations),
        "failure_reason": receipt.failure_reason,
    }


def main() -> None:
    """Delegate local and deployed behavior to one package-owned command."""

    if not {"-h", "--help"} & set(sys.argv[1:]):
        _configure_local_environment()
    analytics_main()


if __name__ == "__main__":
    main()

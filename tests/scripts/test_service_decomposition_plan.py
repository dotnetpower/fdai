from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "config/service-decomposition.json"
TRACKER_PATH = REPO_ROOT / "docs/roadmap/architecture/service-decomposition-execution-plan.md"

EXPECTED_SERVICES = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)
EXPECTED_WORK_PACKAGES = tuple(f"SD-{index:02d}" for index in range(10))


def _load_plan() -> dict[str, object]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def test_service_decomposition_target_is_exactly_five_services() -> None:
    plan = _load_plan()
    services = plan["services"]

    assert isinstance(services, list)
    assert plan["target_service_count"] == 5
    assert tuple(service["id"] for service in services) == EXPECTED_SERVICES
    assert services[-1]["target_state"] == "deployed-sole-executor-identity"


def test_service_decomposition_work_package_graph_is_acyclic() -> None:
    plan = _load_plan()
    work_packages = plan["work_packages"]

    assert isinstance(work_packages, list)
    by_id = {item["id"]: item for item in work_packages}
    assert tuple(by_id) == EXPECTED_WORK_PACKAGES

    remaining = set(by_id)
    completed: set[str] = set()
    while remaining:
        ready = {
            work_package_id
            for work_package_id in remaining
            if set(by_id[work_package_id]["dependencies"]) <= completed
        }
        assert ready, f"cyclic work-package dependencies: {sorted(remaining)}"
        completed.update(ready)
        remaining.difference_update(ready)


def test_service_decomposition_baseline_receipt_is_explicit() -> None:
    receipt = _load_plan()["baseline_receipt"]

    assert receipt["accepted"] is True
    assert receipt["revision"] == "95bd58718"
    assert sum(check["passed"] for check in receipt["checks"]) == 918
    assert sum(check["skipped"] for check in receipt["checks"]) == 2
    assert receipt["open_live_evidence"] == []

    live_receipts = _load_plan()["live_receipts"]
    assert live_receipts["sd03"]["effective_access"] == "passed"
    assert live_receipts["sd03"]["rollback_rehearsal_seconds"] < 900
    assert live_receipts["sd07"]["healthy_runtime_services"] == 5
    assert live_receipts["sd07"]["effect_authority"] is False
    assert live_receipts["sd07"]["timed_authority_cutover_rollback"] == "pending-sd08"


def test_service_decomposition_tracker_matches_machine_status() -> None:
    plan = _load_plan()
    tracker = TRACKER_PATH.read_text(encoding="utf-8")
    work_packages = plan["work_packages"]
    counts = Counter(item["status"] for item in work_packages)

    for item in work_packages:
        checkbox = "[x]" if item["status"] == "completed" else "[ ]"
        assert f"| {checkbox} | {item['id']} |" in tracker

    assert f"| Completed | {counts['completed']} |" in tracker
    assert f"| In progress | {counts['in_progress']} |" in tracker
    assert f"| Planned | {counts['planned']} |" in tracker
    assert f"| Blocked | {counts['blocked']} |" in tracker

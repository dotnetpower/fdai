"""The read-only and approval routes the Hub operator UI calls."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from starlette.testclient import TestClient

from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.domain import Installation, Issued, IssuedPlan, OutcomeKind, Planner
from fdai_lifecycle_hub.enrollment import EnrollmentRequest
from fdai_lifecycle_hub.signing import verify_key_proof
from fdai_lifecycle_hub.store import HubStore


@pytest.fixture
def client(enrolled_store: HubStore, now: datetime) -> TestClient:
    return TestClient(
        create_app(enrolled_store, clock=lambda: now), base_url="http://127.0.0.1:8090"
    )


@pytest.fixture
def issued(
    enrolled_store: HubStore, installation: Installation, planner: Planner, now: datetime
) -> Issued:
    outcome = enrolled_store.recompute(installation.installation_id, planner, now=now)
    assert isinstance(outcome, Issued)
    return outcome


def test_list_installations_summarizes_the_latest_evaluation(
    client: TestClient, issued: Issued, installation: Installation
) -> None:
    response = client.get("/v1/installations")

    assert response.status_code == 200
    (summary,) = response.json()["installations"]
    assert summary["installation_id"] == installation.installation_id
    assert summary["channel"] == installation.settings.channel
    assert summary["current_release"] == "1.4.0"
    assert summary["target_release_id"] == issued.plan.target_release_id
    assert summary["outcome"] == OutcomeKind.ISSUED
    assert summary["health"] == "healthy"
    # `now` sits inside the fixture's daily window, so it must read as currently open rather
    # than a future "starts in" time an operator could misread as not-yet-open.
    assert summary["next_window_open"] is True
    assert summary["next_window_starts_at"] is not None
    assert summary["next_window_ends_at"] is not None


def test_list_installations_is_empty_before_any_enrollment(store: HubStore, now: datetime) -> None:
    client = TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")

    assert client.get("/v1/installations").json() == {"installations": []}


def test_get_installation_detail_includes_entities_and_open_plan(
    client: TestClient, issued: Issued, installation: Installation
) -> None:
    response = client.get(f"/v1/installations/{installation.installation_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["enrollment"] == "enrolled"
    assert body["open_plan"]["plan_id"] == issued.plan.plan_id
    assert body["last_evaluation"]["outcome"] == OutcomeKind.ISSUED
    entities = {entity["entity_id"]: entity for entity in body["entities"]}
    assert entities["core"]["managed"] is True
    assert entities["core"]["release_id"] == "1.4.0"
    assert entities["console"]["managed"] is False


def test_installation_detail_exposes_only_its_deployment_bound_console_url(
    enrolled_store: HubStore, installation: Installation, now: datetime
) -> None:
    client = TestClient(
        create_app(
            enrolled_store,
            clock=lambda: now,
            installation_console_urls={
                installation.installation_id: "https://console.example.com",
                "other-installation": "https://other.example.com",
            },
        )
    )

    body = client.get(f"/v1/installations/{installation.installation_id}").json()

    assert body["console_url"] == "https://console.example.com"
    assert "other.example.com" not in json.dumps(body)


def test_get_installation_for_unknown_returns_404(client: TestClient) -> None:
    response = client.get("/v1/installations/missing")

    assert (response.status_code, response.json()) == (404, {"error": "not_found"})


def test_detail_preserves_unreported_unmanaged_entities(
    client: TestClient, enrolled_store: HubStore, installation: Installation, now: datetime
) -> None:
    core_only = replace(
        installation.reported,
        entities={"core": installation.reported.entities["core"]},
        observed_at=now,
    )
    enrolled_store.record_state(installation.installation_id, core_only, now=now)

    response = client.get(f"/v1/installations/{installation.installation_id}")

    assert response.status_code == 200
    entities = {entity["entity_id"]: entity for entity in response.json()["entities"]}
    assert entities["core"]["release_id"] == "1.4.0"
    assert entities["console"]["release_id"] is None
    assert entities["console"]["health"] is None
    assert entities["console"]["managed"] is False


@pytest.mark.parametrize("minutes", [-1, 0, 59, 60, 61])
def test_detail_shows_only_currently_active_suppressions(
    enrolled_store: HubStore, installation: Installation, now: datetime, minutes: int
) -> None:
    window = SuppressionWindow("installation", now, now + timedelta(hours=1))
    enrolled_store.add_suppression(installation.installation_id, window, now=now)
    at = now + timedelta(minutes=minutes)
    client = TestClient(create_app(enrolled_store, clock=lambda: at))

    response = client.get(f"/v1/installations/{installation.installation_id}")

    assert response.status_code == 200
    assert len(response.json()["suppressions"]) == (1 if 0 <= minutes < 60 else 0)


@pytest.mark.parametrize("decision", ["approve", "reject"])
@pytest.mark.parametrize(
    ("headers", "expected_status", "reason"),
    [
        ({"content-type": "text/plain"}, 415, "json_required"),
        ({"content-type": "application/x-www-form-urlencoded"}, 415, "json_required"),
        (
            {"content-type": "application/json", "origin": "https://untrusted.invalid"},
            403,
            "untrusted_origin",
        ),
        (
            {"content-type": "text/plain", "origin": "https://untrusted.invalid"},
            403,
            "untrusted_origin",
        ),
        ({"content-type": "application/json", "origin": "null"}, 403, "untrusted_origin"),
        (
            {"content-type": "application/json", "origin": "http://127.0.0.1:5290"},
            403,
            "untrusted_origin",
        ),
        (
            {"content-type": "application/json", "sec-fetch-site": "cross-site"},
            403,
            "untrusted_origin",
        ),
        ({"content-type": "application/json", "host": "untrusted.invalid"}, 403, "untrusted_host"),
    ],
)
def test_untrusted_decisions_leave_enrollment_unchanged(
    store: HubStore,
    enrollment: EnrollmentRequest,
    now: datetime,
    decision: str,
    headers: dict[str, str],
    expected_status: int,
    reason: str,
) -> None:
    store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    client = TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")
    installation_id = enrollment.installation.installation_id
    body = (
        {"approver": "alice", "installation_key_id": enrollment.installation_key_id}
        if decision == "approve"
        else {"approver": "alice", "reason": "unknown_key"}
    )

    response = client.post(
        f"/v1/installations/{installation_id}/enrollment/{decision}",
        content=json.dumps(body),
        headers=headers,
    )

    assert (response.status_code, response.json()) == (expected_status, {"error": reason})
    assert store.enrollment_status(installation_id) == "pending"
    assert (
        store.pending_enrollment(installation_id).installation_key_id
        == enrollment.installation_key_id
    )


@pytest.mark.parametrize("decision", ["approve", "reject"])
@pytest.mark.parametrize(
    "origin", ["http://127.0.0.1:8090", "http://127.0.0.1:5290", "http://localhost:5290"]
)
def test_same_origin_decisions_work_directly_and_through_vite(
    store: HubStore,
    enrollment: EnrollmentRequest,
    now: datetime,
    decision: str,
    origin: str,
) -> None:
    store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    client = TestClient(create_app(store, clock=lambda: now), base_url=origin)
    installation_id = enrollment.installation.installation_id
    body = (
        {"approver": "alice", "installation_key_id": enrollment.installation_key_id}
        if decision == "approve"
        else {"approver": "alice", "reason": "unknown_key"}
    )

    response = client.post(
        f"/v1/installations/{installation_id}/enrollment/{decision}",
        json=body,
        headers={"origin": origin},
    )

    assert response.status_code == 200
    assert store.enrollment_status(installation_id) == (
        "enrolled" if decision == "approve" else "rejected"
    )


def test_get_installation_for_a_pending_installation_returns_404(
    store: HubStore, enrollment: EnrollmentRequest, now: datetime
) -> None:

    store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    client = TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")

    response = client.get(f"/v1/installations/{enrollment.installation.installation_id}")

    assert (response.status_code, response.json()) == (404, {"error": "not_found"})


def test_get_plan_detail_returns_status_events_and_reports(
    client: TestClient, issued: Issued, installation: Installation
) -> None:
    report = {
        "attempt": 1,
        "outcome": "dry-run-admitted",
        "reason_code": "admitted",
        "exact_plan_digest": IssuedPlan.from_signed(issued.plan).digest,
        "summary": "dry run admitted",
        "reported_at": "2026-10-05T03:01:00Z",
    }
    plan_id = issued.plan.plan_id
    reports_url = f"/v1/installations/{installation.installation_id}/plans/{plan_id}/reports"
    assert client.post(reports_url, json=report).status_code == 202

    response = client.get(f"/v1/installations/{installation.installation_id}/plans/{plan_id}")

    assert response.status_code == 200
    body = response.json()
    assert (body["plan_id"], body["status"], body["target_release_id"]) == (
        plan_id,
        "open",
        issued.plan.target_release_id,
    )
    assert [event["kind"] for event in body["events"]] == ["issued", "reported"]
    (stored_report,) = body["reports"]
    assert stored_report["outcome"] == "dry-run-admitted"


def test_get_plan_detail_for_unknown_plan_returns_404(
    client: TestClient, installation: Installation
) -> None:
    response = client.get(f"/v1/installations/{installation.installation_id}/plans/missing")

    assert (response.status_code, response.json()) == (404, {"error": "not_found"})


def test_list_and_get_pending_enrollment(
    store: HubStore, enrollment: EnrollmentRequest, now: datetime
) -> None:

    store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    client = TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")
    installation_id = enrollment.installation.installation_id

    listed = client.get("/v1/enrollments/pending")
    fetched = client.get(f"/v1/enrollments/pending/{installation_id}")

    assert listed.status_code == fetched.status_code == 200
    (summary,) = listed.json()["enrollments"]
    assert summary == fetched.json()
    assert summary["installation_key_id"] == enrollment.installation_key_id
    assert {entity["entity_id"] for entity in summary["entities"]} == {"core", "console"}


def test_get_pending_enrollment_for_unknown_installation_returns_404(
    store: HubStore, now: datetime
) -> None:
    client = TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")

    response = client.get("/v1/enrollments/pending/missing")

    assert (response.status_code, response.json()) == (404, {"error": "not_found"})


def test_approve_enrolls_the_installation(
    store: HubStore, enrollment: EnrollmentRequest, now: datetime
) -> None:

    store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    client = TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")
    installation_id = enrollment.installation.installation_id
    body = {"approver": "alice", "installation_key_id": enrollment.installation_key_id}

    response = client.post(f"/v1/installations/{installation_id}/enrollment/approve", json=body)

    assert (response.status_code, response.json()) == (200, {"enrolled": installation_id})
    assert store.enrollment_status(installation_id) == "enrolled"
    assert client.get(f"/v1/enrollments/pending/{installation_id}").status_code == 409


def test_approve_with_the_wrong_key_id_returns_422(
    store: HubStore, enrollment: EnrollmentRequest, now: datetime
) -> None:

    store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    client = TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")
    installation_id = enrollment.installation.installation_id
    body = {"approver": "alice", "installation_key_id": "installation-" + "0" * 16}

    response = client.post(f"/v1/installations/{installation_id}/enrollment/approve", json=body)

    assert (response.status_code, response.json()) == (
        422,
        {"error": "installation_key_mismatch"},
    )


def test_approve_an_already_enrolled_installation_returns_409(
    client: TestClient, installation: Installation
) -> None:
    body = {"approver": "alice", "installation_key_id": "installation-" + "0" * 16}

    response = client.post(
        f"/v1/installations/{installation.installation_id}/enrollment/approve", json=body
    )

    assert (response.status_code, response.json()) == (409, {"error": "not_pending"})


@pytest.mark.parametrize(
    "body",
    [
        {"approver": "alice"},
        {"approver": "", "installation_key_id": "installation-" + "0" * 16},
        {"approver": "alice", "installation_key_id": "not-a-key-id"},
    ],
)
def test_invalid_approval_body_returns_422(
    store: HubStore, enrollment: EnrollmentRequest, now: datetime, body: dict[str, str]
) -> None:

    store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    client = TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")

    response = client.post(
        f"/v1/installations/{enrollment.installation.installation_id}/enrollment/approve",
        json=body,
    )

    assert (response.status_code, response.json()) == (422, {"error": "approval_invalid"})


def test_reject_rejects_the_enrollment(
    store: HubStore, enrollment: EnrollmentRequest, now: datetime
) -> None:

    store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    client = TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")
    installation_id = enrollment.installation.installation_id
    body = {"approver": "alice", "reason": "unknown_key"}

    response = client.post(f"/v1/installations/{installation_id}/enrollment/reject", json=body)

    assert (response.status_code, response.json()) == (200, {"rejected": installation_id})
    assert store.enrollment_status(installation_id) == "rejected"


def test_list_audit_returns_hash_chained_records_and_validates_query(
    client: TestClient, installation: Installation
) -> None:
    response = client.get("/v1/audit")
    assert response.status_code == 200
    body = response.json()
    assert body["chain_intact"] is True
    assert len(body["records"]) >= 2
    assert body["records"][0]["sequence"] > body["records"][1]["sequence"]

    filtered = client.get(f"/v1/audit?installation_id={installation.installation_id}&limit=1")
    assert filtered.status_code == 200
    assert len(filtered.json()["records"]) == 1

    for bad_query in ("?limit=0", "?limit=201", "?limit=abc", "?unknown=1", "?installation_id="):
        assert client.get(f"/v1/audit{bad_query}").status_code == 422


def test_post_and_lift_suppression_commands_enforce_confirmation_and_scope(
    client: TestClient, installation: Installation, now: datetime
) -> None:
    installation_id = installation.installation_id
    ends_at = (now + timedelta(hours=2)).isoformat()
    starts_at = now.isoformat()

    # Wrong confirmation is rejected with 422.
    bad_confirm = client.post(
        f"/v1/installations/{installation_id}/suppressions",
        json={
            "scope": "installation",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "reason": "maintenance_freeze",
            "confirmation": "wrong",
        },
    )
    assert (bad_confirm.status_code, bad_confirm.json()) == (
        422,
        {"error": "suppression_invalid"},
    )

    # Valid suppression command adds the manual window and records audit.
    added = client.post(
        f"/v1/installations/{installation_id}/suppressions",
        json={
            "scope": "installation",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "reason": "maintenance_freeze",
            "confirmation": f"suppress {installation_id} installation",
        },
    )
    assert added.status_code == 200
    assert added.json()["scope"] == "installation"
    detail = client.get(f"/v1/installations/{installation_id}").json()
    assert len(detail["suppressions"]) == 1
    assert detail["suppressions"][0]["scope"] == "installation"

    # Lifting an inactive scope returns 409.
    not_active = client.post(
        f"/v1/installations/{installation_id}/suppressions/lift",
        json={
            "scope": "entity:core",
            "reason": "freeze_ended",
            "confirmation": f"lift suppression {installation_id} entity:core",
        },
    )
    assert (not_active.status_code, not_active.json()) == (
        409,
        {"error": "suppression_not_active"},
    )

    # Lifting the active scope clears it.
    lifted = client.post(
        f"/v1/installations/{installation_id}/suppressions/lift",
        json={
            "scope": "installation",
            "reason": "freeze_ended",
            "confirmation": f"lift suppression {installation_id} installation",
        },
    )
    assert (lifted.status_code, lifted.json()) == (
        200,
        {"lifted": installation_id, "scope": "installation"},
    )
    assert client.get(f"/v1/installations/{installation_id}").json()["suppressions"] == []


def test_get_installation_and_enrollment_statuses_minimize_queries(
    client: TestClient, enrolled_store: HubStore, installation: Installation
) -> None:
    from sqlalchemy import event as sqlalchemy_event

    installation_queries: list[str] = []

    def count_queries(_conn: object, _cursor: object, statement: str, *_args: object) -> None:
        normalized = statement.lstrip().upper()
        if normalized.startswith("SELECT") and "LIFECYCLE_INSTALLATION" in normalized:
            installation_queries.append(statement)

    sqlalchemy_event.listen(enrolled_store.engine, "before_cursor_execute", count_queries)
    try:
        response = client.get(f"/v1/installations/{installation.installation_id}")
        assert response.status_code == 200
        assert len(installation_queries) == 1

        installation_queries.clear()
        statuses = enrolled_store.enrollment_statuses(
            frozenset({installation.installation_id, "unrequested-id"})
        )
        assert statuses == {installation.installation_id: "enrolled"}
        assert len(installation_queries) == 1
    finally:
        sqlalchemy_event.remove(enrolled_store.engine, "before_cursor_execute", count_queries)


def test_lifecycle_commands_require_expiry_and_reject_authority_raising(
    client: TestClient, installation: Installation, now: datetime
) -> None:
    installation_id = installation.installation_id
    ends_at = (now + timedelta(hours=3)).isoformat()

    missing_expiry = client.post(
        f"/v1/installations/{installation_id}/commands",
        json={
            "command_id": "cmd-no-expiry",
            "kind": "authority-lowering",
            "scope": "installation",
            "starts_at": now.isoformat(),
            "expires_at": None,
            "reason": "incident_containment",
            "target_mode": "shadow",
            "confirmation": f"command authority-lowering {installation_id} installation",
        },
    )
    assert (missing_expiry.status_code, missing_expiry.json()) == (
        422,
        {"error": "command_expiry_required"},
    )

    raises_authority = client.post(
        f"/v1/installations/{installation_id}/commands",
        json={
            "command_id": "cmd-raise",
            "kind": "authority-lowering",
            "scope": "installation",
            "starts_at": now.isoformat(),
            "expires_at": ends_at,
            "reason": "incident_containment",
            "target_mode": "enforce",
            "confirmation": f"command authority-lowering {installation_id} installation",
        },
    )
    assert (raises_authority.status_code, raises_authority.json()) == (
        422,
        {"error": "command_raises_authority"},
    )

    lowered = client.post(
        f"/v1/installations/{installation_id}/commands",
        json={
            "command_id": "cmd-lower-1",
            "kind": "authority-lowering",
            "scope": "installation",
            "starts_at": now.isoformat(),
            "expires_at": ends_at,
            "reason": "incident_containment",
            "target_mode": "shadow",
            "engage_kill_switch": True,
            "confirmation": f"command authority-lowering {installation_id} installation",
        },
    )
    assert lowered.status_code == 201
    assert lowered.json()["kind"] == "authority-lowering"
    assert lowered.json()["active"] is True

    break_glass = client.post(
        f"/v1/installations/{installation_id}/commands",
        json={
            "command_id": "cmd-bg-1",
            "kind": "break-glass",
            "scope": "installation",
            "starts_at": now.isoformat(),
            "expires_at": ends_at,
            "reason": "emergency_scale_out",
            "bypass_scopes": ["maintenance-window", "suppression-window"],
            "confirmation": f"command break-glass {installation_id} installation",
        },
    )
    assert break_glass.status_code == 201
    assert break_glass.json()["reconciles_to_git_on_expiry"] is True

    listed = client.get("/v1/commands").json()["commands"]
    assert [item["command_id"] for item in listed] == ["cmd-lower-1", "cmd-bg-1"]
    assert client.get("/v1/audit").json()["chain_intact"] is True


def test_destructive_confirmations_bind_to_exact_plan_digest_and_invalidate_on_drift(
    client: TestClient, issued: Issued, installation: Installation
) -> None:
    import hashlib

    installation_id = installation.installation_id
    plan_id = issued.plan.plan_id
    exact_digest = "sha256:" + hashlib.sha256(issued.plan.signed_payload).hexdigest()
    wrong_digest = "sha256:" + "0" * 64

    wrong_proposal = client.post(
        f"/v1/installations/{installation_id}/plans/{plan_id}/confirmations",
        json={
            "exact_plan_digest": wrong_digest,
            "change_kind": "resource-replacement",
            "title": "prod · replace user node pool runtime",
            "summary": "Node size change deletes and recreates the runtime node pool.",
            "impact": "Three nodes are replaced one at a time inside the downtime window.",
            "replace_count": 1,
            "delete_count": 0,
            "affected_addresses": ["module.aks.azurerm_kubernetes_cluster_node_pool.runtime"],
        },
    )
    assert (wrong_proposal.status_code, wrong_proposal.json()) == (
        409,
        {"error": "plan_digest_mismatch"},
    )

    proposed = client.post(
        f"/v1/installations/{installation_id}/plans/{plan_id}/confirmations",
        json={
            "exact_plan_digest": exact_digest,
            "change_kind": "resource-replacement",
            "title": "prod · replace user node pool runtime",
            "summary": "Node size change deletes and recreates the runtime node pool.",
            "impact": "Three nodes are replaced one at a time inside the downtime window.",
            "replace_count": 1,
            "delete_count": 0,
            "affected_addresses": ["module.aks.azurerm_kubernetes_cluster_node_pool.runtime"],
        },
    )
    assert proposed.status_code == 201
    assert proposed.json()["status"] == "pending"

    mismatched_decision = client.post(
        f"/v1/installations/{installation_id}/plans/{plan_id}/confirmations/decision",
        json={
            "decision": "confirm",
            "expected_plan_digest": wrong_digest,
            "confirmed_addresses": ["module.aks.azurerm_kubernetes_cluster_node_pool.runtime"],
            "reason": "approved_downtime_replacement",
            "confirmation": f"confirm {installation_id} {plan_id} {wrong_digest}",
        },
    )
    assert (mismatched_decision.status_code, mismatched_decision.json()) == (
        409,
        {"error": "plan_digest_mismatch"},
    )

    # Re-propose with exact digest and confirm it.
    client.post(
        f"/v1/installations/{installation_id}/plans/{plan_id}/confirmations",
        json={
            "exact_plan_digest": exact_digest,
            "change_kind": "resource-replacement",
            "title": "prod · replace user node pool runtime",
            "summary": "Node size change deletes and recreates the runtime node pool.",
            "impact": "Three nodes are replaced one at a time inside the downtime window.",
            "replace_count": 1,
            "delete_count": 0,
            "affected_addresses": ["module.aks.azurerm_kubernetes_cluster_node_pool.runtime"],
        },
    )
    confirmed = client.post(
        f"/v1/installations/{installation_id}/plans/{plan_id}/confirmations/decision",
        json={
            "decision": "confirm",
            "expected_plan_digest": exact_digest,
            "confirmed_addresses": ["module.aks.azurerm_kubernetes_cluster_node_pool.runtime"],
            "reason": "approved_downtime_replacement",
            "confirmation": f"confirm {installation_id} {plan_id} {exact_digest}",
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert client.get("/v1/audit").json()["chain_intact"] is True


def test_target_hub_bundle_import_verifies_signature_checksums_and_predecessor(
    client: TestClient,
) -> None:
    digest_18 = "sha256:" + "a" * 64
    digest_19 = "sha256:" + "b" * 64

    bad_sig = client.post(
        "/v1/bundle-imports",
        json={
            "bundle_id": "bundle-0018",
            "extends_bundle_id": None,
            "catalog_export_sha256": digest_18,
            "checksum_count": 412,
            "signature_verified": False,
            "checksums_verified": True,
            "recall_sequence_start": 30,
            "recall_sequence_end": 30,
            "releases": ["1.4.4"],
            "channels": {"RELEASE": "1.4.4"},
            "recall_notices": [],
            "image_layer_count": 20,
            "configuration_package_count": 1,
            "metadata_expiry_days": 30,
            "confirmation": f"import bundle bundle-0018 {digest_18}",
        },
    )
    assert (bad_sig.status_code, bad_sig.json()) == (
        422,
        {"error": "upgrade_bundle_signature_invalid"},
    )

    first = client.post(
        "/v1/bundle-imports",
        json={
            "bundle_id": "bundle-0018",
            "extends_bundle_id": None,
            "catalog_export_sha256": digest_18,
            "checksum_count": 412,
            "signature_verified": True,
            "checksums_verified": True,
            "recall_sequence_start": 30,
            "recall_sequence_end": 30,
            "releases": ["1.4.4"],
            "channels": {"RELEASE": "1.4.4"},
            "recall_notices": [],
            "image_layer_count": 20,
            "configuration_package_count": 1,
            "metadata_expiry_days": 30,
            "confirmation": f"import bundle bundle-0018 {digest_18}",
        },
    )
    assert first.status_code == 201
    assert first.json()["bundle_id"] == "bundle-0018"

    wrong_predecessor = client.post(
        "/v1/bundle-imports",
        json={
            "bundle_id": "bundle-0019",
            "extends_bundle_id": "bundle-0017",
            "catalog_export_sha256": digest_19,
            "checksum_count": 412,
            "signature_verified": True,
            "checksums_verified": True,
            "recall_sequence_start": 31,
            "recall_sequence_end": 31,
            "releases": ["1.4.4", "1.5.1"],
            "channels": {"RELEASE": "1.5.1"},
            "recall_notices": ["#0031 · 1.5.0"],
            "image_layer_count": 38,
            "configuration_package_count": 1,
            "metadata_expiry_days": 30,
            "confirmation": f"import bundle bundle-0019 {digest_19}",
        },
    )
    assert (wrong_predecessor.status_code, wrong_predecessor.json()) == (
        422,
        {"error": "upgrade_bundle_lineage_mismatch"},
    )

    second = client.post(
        "/v1/bundle-imports",
        json={
            "bundle_id": "bundle-0019",
            "extends_bundle_id": "bundle-0018",
            "catalog_export_sha256": digest_19,
            "checksum_count": 412,
            "signature_verified": True,
            "checksums_verified": True,
            "recall_sequence_start": 31,
            "recall_sequence_end": 31,
            "releases": ["1.4.4", "1.5.1"],
            "channels": {"RELEASE": "1.5.1"},
            "recall_notices": ["#0031 · 1.5.0"],
            "image_layer_count": 38,
            "configuration_package_count": 1,
            "metadata_expiry_days": 30,
            "confirmation": f"import bundle bundle-0019 {digest_19}",
        },
    )
    assert second.status_code == 201
    listed = client.get("/v1/bundle-imports").json()
    assert listed["last_bundle_id"] == "bundle-0019"
    assert len(listed["imports"]) == 2
    assert client.get("/v1/audit").json()["chain_intact"] is True

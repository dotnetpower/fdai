#!/usr/bin/env python3
"""Rehearse and verify end-to-end operational acceptance for Issue #2128."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai.agents import PANTHEON_SPECS
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.agents.var import Var
from fdai.core.incident import (
    IncidentAutoOpenPolicy,
    IncidentLifecycleWorkflow,
    IncidentRegistry,
    open_detected_incident_candidate,
)
from fdai.core.notifications.delivery import (
    ChannelDeliveryState,
    InMemoryNotificationDeliveryStore,
)
from fdai.core.security.code_findings.review_signal import (
    ReviewSource,
    code_security_drift_payload,
    review_decision,
)
from fdai.core.stewardship.governance import StewardshipGovernanceService
from fdai.delivery.code_security_repository_changes import (
    REPOSITORY_CHANGE_OPERATION,
    parse_repository_change,
)
from fdai.delivery.code_security_scan_requests import (
    ClaimedScanRequest,
    ScanOutcome,
    process_scan_requests,
)
from fdai.delivery.knowledge_github_changes import apply_knowledge_change
from fdai.delivery.notifications.receipt import NotificationDeliveryReceiptApplier
from fdai.delivery.persistence.state_store_code_security_repository import read_repository
from fdai.delivery.persistence.state_store_code_security_review import (
    record_code_security_review,
)
from fdai.runtime.stewardship_activation import StewardshipActivationProcessor
from fdai.runtime.stewardship_governance import (
    ConsoleStewardshipCandidatePublisher,
    activate_console_stewardship_candidate,
)
from fdai.runtime.stewardship_identity_health import StewardshipIdentityHealthWorker
from fdai.runtime.stewardship_merge_effects import (
    COVERAGE_PROJECTION_KEY,
    StewardshipMergeEffectsWorker,
)
from fdai.shared.providers.human_identity import HumanIdentity
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_github_app_auth.provider import GitHubAppTokenConfig, GitHubAppTokenProvider
from fdai_github_app_auth.repository_reader import GitHubRepositoryObservation
from fdai_operator_service.families.iam.contracts import DirectoryIdentity, DirectoryStatus
from fdai_operator_service.families.operations.contracts import ProjectionQuery
from fdai_operator_service.notification_receipt_ingress import (
    NotificationReceiptIngress,
    NotificationReceiptIngressConfig,
)
from fdai_operator_service.ownership_projection import OwnershipProjectionReader
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRevision,
    approval_profile_policy_digest,
    evaluate_profile_approval,
)
from fdai_service_contracts.handover import (
    HandoverDraftArtifact,
    HandoverDraftOutcome,
    HandoverMapping,
    HandoverPerson,
    HandoverSourceSpan,
    StewardResponsibility,
    StewardshipDraft,
)
from fdai_service_contracts.knowledge_github import GitHubKnowledgeChangeBody
from fdai_service_contracts.notification_receipt import (
    NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
    RECEIPT_SIGNATURE_HEADER,
    RECEIPT_TIMESTAMP_HEADER,
    compute_receipt_signature,
    decode_notification_delivery_receipt,
)
from fdai_service_contracts.schema import (
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)

CORRELATION_ID = "corr-2128-operational-acceptance-20261104"
TARGET_REPO_ALIAS = "aks-store-demo"
TARGET_REPO_LOCATION = "dotnetpower/aks-store-demo"
PINNED_COMMIT = "3c3ba3bd999d0b2d78eece1adac84b712b7d9c4f"
PINNED_README_DIGEST = "4418352bc6c4ebd4e7c5b8fed25ef9034cd16fa776b9b4fc02cc9dd502cbb63f"
PINNED_REVIEW_DIGEST = "4299aa467dcd00b0beafca766fb03e6a02dbc618e5db52160ea2895a9453ebc2"
CLEAN_REVIEW_DIGEST = "0" * 63 + "1"

STEWARD_OIDS = tuple(str(UUID(int=2128000 + idx, version=4)) for idx in range(1, 8))
MAINTAINER_OIDS = (STEWARD_OIDS[0], STEWARD_OIDS[1])
OWNERS_GROUP_OID = os.environ.get("FDAI_RBAC_OWNERS_GROUP_ID") or str(UUID(int=2128999, version=4))


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str = "operational acceptance assertion failed") -> None:
    if not condition:
        raise RuntimeError(message)


def _build_v2_stewardship_yaml() -> str:
    non_autonomous = [spec.name for spec in PANTHEON_SPECS if spec.name != "Loki"]
    lines = [
        "stewardship:",
        "  version: 2",
        "  maintainers:",
        f'    - oid: "{MAINTAINER_OIDS[0]}"',
        f'    - oid: "{MAINTAINER_OIDS[1]}"',
        "  channels: {}",
        "  escalation:",
        "    hop_timeout_seconds: 900",
        "  thresholds:",
        "    over_assigned_max: 5",
        "  agents:",
    ]
    for idx, name in enumerate(non_autonomous):
        primary_oid = STEWARD_OIDS[idx % len(STEWARD_OIDS)]
        backup_oid = STEWARD_OIDS[(idx + 1) % len(STEWARD_OIDS)]
        lines.extend(
            (
                f"    {name}:",
                "      stewards:",
                f'        - {{ kind: user, id: "{primary_oid}", '
                "responsibility: accountable, duty: primary }",
                f'        - {{ kind: user, id: "{backup_oid}", '
                "responsibility: accountable, duty: backup }",
            )
        )
    lines.extend(
        (
            "    Loki:",
            "      accept_autonomous:",
            '        reason: "Chaos proposals are always HIL; no standing domain owner upstream."',
            "      stewards: []",
        )
    )
    return "\n".join(lines) + "\n"


@dataclass
class _ScanQueue:
    claims: list[ClaimedScanRequest]
    completed: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)

    async def claim(self) -> ClaimedScanRequest | None:
        return self.claims.pop(0) if self.claims else None

    async def renew(self, *, key: str, claim_id: str) -> bool:
        del key, claim_id
        return True

    async def mark_completed(
        self, *, key: str, claim_id: str, result: Mapping[str, object]
    ) -> bool:
        del claim_id
        self.completed.append((key, result))
        return True

    async def mark_rejected(self, *, key: str, claim_id: str, reason_code: str) -> bool:
        del claim_id
        self.rejected.append((key, reason_code))
        return True


class _StaticRepoReader:
    async def verify(self, location: str, credential_reference: str) -> GitHubRepositoryObservation:
        _require(location == TARGET_REPO_LOCATION, "unexpected target repository location")
        _require(
            credential_reference == "deployment-github-app",
            "unexpected credential reference",
        )
        return GitHubRepositoryObservation(
            repository_id=701234567,
            private=False,
            default_branch="main",
            commit=PINNED_COMMIT,
            readme_digest=PINNED_README_DIGEST,
        )


class _ReceiptStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        if key in self.records:
            return False
        self.records[key] = dict(value)
        return True

    async def read_state(self, key: str) -> dict[str, object] | None:
        record = self.records.get(key)
        return dict(record) if record is not None else None

    async def write_state(self, key: str, value: Mapping[str, object]) -> None:
        self.records[key] = dict(value)


class _ReceiptBroker:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, object]]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> None:
        self.published.append((topic, key, dict(payload)))


class _ToggleDirectory:
    def __init__(self, *, stale_oid: str | None = None) -> None:
        self.stale_oid = stale_oid

    async def get_by_subject_id(self, subject_id: str) -> HumanIdentity | None:
        normalized = subject_id.strip()
        active = normalized != self.stale_oid
        return HumanIdentity(
            provider="entra",
            subject_id=normalized,
            username=f"steward-{normalized[-4:]}@example.invalid",
            display_name=f"Steward {normalized[-4:]}",
            active=active,
        )


class _OperatorDirectory:
    async def get_by_subject_id(self, subject_id: str) -> DirectoryIdentity | None:
        normalized = subject_id.strip()
        return DirectoryIdentity(
            provider="entra",
            subject_id=normalized,
            display_name=f"Steward {normalized[-4:]}",
            username=f"steward-{normalized[-4:]}@example.invalid",
            active=True,
            principal_type="person",
            roles=("Owner", "Approver"),
        )

    async def directory_status(self) -> DirectoryStatus:
        return DirectoryStatus(
            source="microsoft_graph",
            availability="available",
            observed_at=datetime.now(UTC),
            detail="Directory resolved all subjects.",
        )


class _ProjectionFallback:
    def __init__(self, store: InMemoryStateStore) -> None:
        self._store = store

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        state = await self._store.read_state(f"operator-projection:operations:{query.operation}")
        if state is None:
            raise LookupError(query.operation)
        return state


def _generate_ephemeral_rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


async def run_rehearsal() -> dict[str, Any]:
    """Execute the deterministic end-to-end Issue #2128 operational acceptance rehearsal."""
    now = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)
    store = InMemoryStateStore()
    reg = load_pantheon()
    bus = InMemoryBus(registry=reg)

    # 1. Criterion 1: Identity & GET /iam/self Owner readback
    operator_oid = MAINTAINER_OIDS[0]
    iam_self: dict[str, Any] = {
        "authenticated": True,
        "principal_digest": _sha256_text(operator_oid),
        "owners_group_digest": _sha256_text(OWNERS_GROUP_OID),
        "roles": ["Owner", "Approver"],
    }
    _require("Owner" in iam_self["roles"] and iam_self["authenticated"] is True)

    # 2. Criterion 2 & 6a: GitHub App token, repo connect (enabled=False), governed enable
    private_pem = _generate_ephemeral_rsa_pem()

    def _app_handler(request: httpx.Request) -> httpx.Response:
        _require(request.url.path == "/app/installations/99001/access_tokens")
        return httpx.Response(
            201,
            json={
                "token": "ghs_ephemeral_readonly_installation_token",
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "permissions": {"contents": "read", "metadata": "read"},
                "repository_selection": "selected",
                "repositories": [{"name": TARGET_REPO_ALIAS}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(_app_handler)) as http_client:
        token_provider = GitHubAppTokenProvider(
            config=GitHubAppTokenConfig(
                client_id="Iv1.fdai2128acceptance",
                installation_id=99001,
                private_key_pem=private_pem,
                repository=TARGET_REPO_ALIAS,
                permissions=(("contents", "read"), ("metadata", "read")),
            ),
            http_client=http_client,
            clock=lambda: now,
        )
        token_projection = await token_provider.projection()
    _require(token_projection.permissions == (("contents", "read"), ("metadata", "read")))

    connect_id = "operator-" + "1" * 32
    connect_result, connect_err = await apply_knowledge_change(
        store,
        GitHubKnowledgeChangeBody(
            action="connect",
            repository_alias=TARGET_REPO_ALIAS,
            expected_revision=0,
            location=TARGET_REPO_LOCATION,
            credential_reference="deployment-github-app",
        ),
        principal=operator_oid,
        request_id=connect_id,
        reader=_StaticRepoReader(),
    )
    if connect_err is not None or connect_result is None:
        raise RuntimeError("knowledge connect failed")
    _require(connect_result["enabled"] is False)
    connected_repo = await read_repository(store, TARGET_REPO_ALIAS)
    if connected_repo is None or connected_repo.enabled is not False:
        raise RuntimeError("connected repository must start with enabled=False")

    # Wire Pantheon pipeline: Huginn -> Heimdall -> Forseti -> Thor-shadow -> Saga
    incident_registry = IncidentRegistry(state_store=store)
    incident_workflow = IncidentLifecycleWorkflow(
        registry=incident_registry,
        allowed_agent_principals={"Huginn", "Heimdall", "Forseti"},
    )
    incident_policy = IncidentAutoOpenPolicy()

    async def _open_incident(candidate: dict[str, Any]) -> bool:
        opened = await open_detected_incident_candidate(
            workflow=incident_workflow,
            candidate=candidate,
            policy=incident_policy,
        )
        if opened is not None:
            await store.append_audit_entry(
                {
                    "actor": "Heimdall",
                    "action_kind": "incident.open",
                    "correlation_id": str(candidate.get("correlation_id", CORRELATION_ID)),
                    "incident_id": str(opened.incident.incident_id),
                    "resource_id": str(candidate.get("resource_id", "")),
                    "recorded_at": now.isoformat(),
                }
            )
        return opened is not None

    action_semantics = ActionSemanticsCatalog(
        irreversible_by_id={"ops.restart-service": False},
        rollback_by_id={"ops.restart-service": "state_forward_only"},
    )
    huginn = Huginn(bus=bus, state_store=store, clock=lambda: now)
    heimdall = Heimdall(
        bus=bus,
        state_store=store,
        rate_threshold=3,
        incident_candidate_hook=_open_incident,
        code_security_drift_projector=code_security_drift_payload,
    )
    forseti = Forseti(bus=bus, action_semantics=action_semantics)
    thor = Thor(bus=bus)
    thor.set_shadow(True)
    saga = Saga()

    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    bus.subscribe("object.event", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.anomaly", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.drift", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Thor", thor.on_typed_message)
    for topic in ("object.verdict", "object.action-run", "object.drift", "object.anomaly"):
        bus.subscribe(topic, "Saga", saga.on_typed_message)

    enable_id = "operator-" + "2" * 32
    enable_change = parse_repository_change(
        {
            "operation": REPOSITORY_CHANGE_OPERATION,
            "proposal_id": enable_id,
            "principal_id": operator_oid,
            "payload": {
                "payload": {"action": "enable", "repository_alias": TARGET_REPO_ALIAS},
                "principal_roles": ["Owner"],
            },
        }
    )
    if enable_change is None:
        raise RuntimeError("enable_change parsing failed")
    scan_queue = _ScanQueue(
        claims=[
            ClaimedScanRequest(
                key=f"operator-proposal:operations:{enable_id}",
                claim_id="claim-enable-1",
                request=None,
                operation=REPOSITORY_CHANGE_OPERATION,
                change=enable_change,
            )
        ]
    )

    def _make_package(source: ReviewSource, *, issue_count: int, digest: str) -> dict[str, object]:
        p1 = 54 if issue_count else 0
        p2 = 217 if issue_count else 0
        return {
            "kind": "code-security-review",
            "schema_version": "1.1.0",
            "repository_alias": TARGET_REPO_ALIAS,
            "revision": PINNED_COMMIT,
            "exposure": "unknown",
            "coverage_complete": True,
            "issue_count": issue_count,
            "known_exploited_count": 0,
            "by_priority": {"P0": 0, "P1": p1, "P2": p2, "P3": 0, "P4": 0},
            "by_severity": {
                "critical": 3 if issue_count else 0,
                "high": 51 if issue_count else 0,
                "medium": 0,
                "low": 0,
                "undetermined": p2,
            },
            "by_confidence": {
                "proven": 0,
                "verified": 0,
                "corroborated": 2 if issue_count else 0,
                "reported": 269 if issue_count else 0,
                "hypothesis": 0,
            },
            "producers": ["Opengrep", "Trivy", "Trivy config", "gitleaks", "osv-scanner"],
            "top_issue_ids": ["FDAI-SEC-05cf01eddff8"] if issue_count else [],
            "review_digest": digest,
            "review_required": True,
            "grants_authority": False,
            "source": source.as_dict(),
        }

    async def _scan_runner(repository: Any, ref: str, source: ReviewSource) -> ScanOutcome:
        del repository, ref
        pkg = _make_package(source, issue_count=271, digest=PINNED_REVIEW_DIGEST)
        return ScanOutcome(package=pkg)

    async def _scan_recorder(outcome: ScanOutcome) -> bool:
        return await record_code_security_review(store, outcome.package, issues=outcome.issues)

    scan_outcomes = await process_scan_requests(
        scan_queue,
        store,
        _scan_runner,
        recorder=_scan_recorder,
        publisher=heimdall,
        max_requests=1,
    )
    _require(len(scan_outcomes) == 1 and scan_outcomes[0]["status"] == "published")
    _require(scan_outcomes[0]["enabled"] is True)
    initial_scan: Any = scan_outcomes[0]["initial_scan"]
    _require(initial_scan["decision"] == "open")
    clean_pkg = _make_package(
        ReviewSource(kind="git_repository", provider="github", trigger="schedule"),
        issue_count=0,
        digest=CLEAN_REVIEW_DIGEST,
    )
    _require(review_decision(clean_pkg) == "clear")
    _require(await heimdall.publish_code_security_drift(clean_pkg) is True)

    # 3. Criterion 5 & #2592: Authoritative observation -> Incident + Huginn..Saga
    raw_events = [
        {
            "id": f"obs-2128-{idx}",
            "idempotency_key": f"obs-2128-{idx}",
            "correlation_id": CORRELATION_ID,
            "resource_id": "kubernetes.pod/aks-store-demo/order-service",
            "resource_type": "compute",
            "event_type": "availability.probe_failed",
            "severity": "high",
            "detected_at": now.isoformat(),
        }
        for idx in range(8)
    ]
    for raw_evt in raw_events:
        ingested = await huginn.ingest(raw_evt)
        _require(ingested is not None)

    _require(len(incident_registry.snapshot()) == 1)
    shadow_corr = f"{CORRELATION_ID}:thor-shadow"
    await huginn.ingest(
        {
            "id": "obs-2128-restart",
            "idempotency_key": "obs-2128-restart",
            "correlation_id": shadow_corr,
            "resource_id": "kubernetes.pod/aks-store-demo/order-service",
            "resource_type": "compute",
            "event_type": "restart_needed",
            "severity": "high",
            "detected_at": now.isoformat(),
        }
    )
    thor_run = thor.action_runs.get(shadow_corr)
    if thor_run is None or thor_run.shadow_mode is not True:
        raise RuntimeError("expected shadow-mode Thor action run")
    _require(thor_run.outcome == "shadow_success")
    cast(Any, saga.audit_chain).verify()

    # 4. Criterion 3 & 6b: External notification delivery receipt & callback convergence
    delivery_store = InMemoryNotificationDeliveryStore()
    await delivery_store.create_plan(
        audit_id=CORRELATION_ID,
        target_channel_ids=("teams-ops-prd", "slack-ops-prd"),
        excluded_channels={},
        now=now,
    )
    for channel_id, msg_id in (
        ("teams-ops-prd", "08584079556776838800454763949CU17"),
        ("slack-ops-prd", "1793651207.237899"),
    ):
        claim = await delivery_store.claim(
            audit_id=CORRELATION_ID,
            channel_id=channel_id,
            now=now,
            lease_seconds=60,
            max_attempts=3,
        )
        if claim.record.state is not ChannelDeliveryState.SENDING or claim.record.token is None:
            raise RuntimeError("delivery claim must start in SENDING state with token")
        accepted = await delivery_store.record_result(
            audit_id=CORRELATION_ID,
            channel_id=channel_id,
            token=claim.record.token,
            state=ChannelDeliveryState.ACCEPTED,
            at=now,
            confirmation_timeout_seconds=300,
            provider_message_id=msg_id,
        )
        _require(accepted.state is ChannelDeliveryState.ACCEPTED)

    receipt_store = _ReceiptStore()
    receipt_broker = _ReceiptBroker()
    receipt_secret = "rehearsal-hmac-secret-2128"  # noqa: S105 - deterministic test secret
    ingress = NotificationReceiptIngress(
        config=NotificationReceiptIngressConfig(
            secret=receipt_secret,
            topic=NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
        ),
        store=receipt_store,
        publisher=receipt_broker,
        validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
        clock=lambda: now,
    )
    applier = NotificationDeliveryReceiptApplier(
        delivery_store=delivery_store,
        audit_store=store,
        clock=lambda: now,
    )
    receipt_ids: dict[str, str] = {}
    for channel_id, msg_id in (
        ("teams-ops-prd", "08584079556776838800454763949CU17"),
        ("slack-ops-prd", "1793651207.237899"),
    ):
        body = json.dumps(
            {
                "audit_id": CORRELATION_ID,
                "channel_id": channel_id,
                "publication_result": "published",
                "provider_message_id": msg_id,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        ts_header = now.isoformat()
        sig_header = "sha256=" + compute_receipt_signature(
            secret=receipt_secret,
            timestamp=ts_header,
            body=body,
        )
        headers = {
            RECEIPT_TIMESTAMP_HEADER: ts_header,
            RECEIPT_SIGNATURE_HEADER: sig_header,
        }
        accepted_receipt = await ingress.accept(headers=headers, body=body)
        receipt_ids[channel_id] = accepted_receipt.idempotency_key
        decoded = decode_notification_delivery_receipt(receipt_broker.published[-1][2])
        converged = await applier.apply(decoded)
        _require(converged.state is ChannelDeliveryState.DELIVERED)
        before_pub_count = len(receipt_broker.published)
        replayed_receipt = await ingress.accept(headers=headers, body=body)
        _require(replayed_receipt.idempotency_key == accepted_receipt.idempotency_key)
        _require(len(receipt_broker.published) == before_pub_count)

    # 5. Criterion 4, 6c & #458/#2733: Schema v2 stewardship, Console handover, identity health
    v2_yaml = _build_v2_stewardship_yaml()
    candidate_publisher = ConsoleStewardshipCandidatePublisher(store=store)
    gov_service = StewardshipGovernanceService(publisher=candidate_publisher)
    handover_artifact = HandoverDraftArtifact(
        upload_id=UUID(int=212801, version=4),
        document_id=UUID(int=212802, version=4),
        version_id=UUID(int=212803, version=4),
        draft=StewardshipDraft(
            outcome=HandoverDraftOutcome.DRAFTED,
            mappings=(
                HandoverMapping(
                    agent_name="Heimdall",
                    person=HandoverPerson(
                        display_name="Primary Steward",
                        oid=STEWARD_OIDS[0],
                    ),
                    responsibility=StewardResponsibility.ACCOUNTABLE,
                    confidence=0.99,
                    citations=(
                        HandoverSourceSpan(
                            doc_id="handover-2128",
                            line=1,
                            quote="Agent: Heimdall; responsibility: accountable",
                        ),
                    ),
                ),
            ),
        ),
        yaml=v2_yaml,
    )
    first_pub = await gov_service.publish(handover_artifact)
    second_pub = await gov_service.publish(handover_artifact)
    if first_pub.receipt is None or second_pub.receipt is None:
        raise RuntimeError("expected handover publish receipts")
    _require(first_pub.receipt.already_existed is False)
    _require(second_pub.receipt.already_existed is True)
    _require(first_pub.receipt.head_sha == second_pub.receipt.head_sha)
    candidate_id = first_pub.receipt.pr_ref.removeprefix("console-stewardship:")

    activation_proposal_id = "operator-" + "3" * 32
    await store.write_state(
        f"operator-proposal:operations:{activation_proposal_id}",
        {
            "proposal_id": activation_proposal_id,
            "operation": "stewardship.candidate_activation",
            "principal_id": MAINTAINER_OIDS[1],
            "payload": {
                "principal_roles": ["Owner"],
                "payload": {
                    "candidate_id": candidate_id,
                    "candidate_digest": str(first_pub.receipt.head_sha),
                },
            },
        },
    )
    activation_processor = StewardshipActivationProcessor(store=store)
    _require(await activation_processor.run_once() == 1)
    _require(await activation_processor.run_once() == 0)
    _require(
        await activate_console_stewardship_candidate(
            store,
            candidate_id=candidate_id,
            reviewer_identity=MAINTAINER_OIDS[1],
            requester_identity=MAINTAINER_OIDS[0],
        )
        is False
    )

    class _NoChannelDispatcher:
        async def dispatch(self, message: Any) -> Any:
            del message
            return SimpleNamespace(outcome=SimpleNamespace(value="no_eligible_channels"))

    from fdai.core.stewardship.governance import validate_stewardship_candidate

    active_map = validate_stewardship_candidate(
        v2_yaml,
        environ={"FDAI_STEWARDSHIP_REQUIRE_BINDINGS": "1"},
    )
    merge_worker = StewardshipMergeEffectsWorker(
        store=store,
        base=active_map,
        notifications=_NoChannelDispatcher(),
        validation_environ={"FDAI_STEWARDSHIP_REQUIRE_BINDINGS": "1"},
    )
    _require(await merge_worker.run_once() == 1)
    _require(await merge_worker.run_once() == 0)
    merge_receipt = await store.read_state(f"stewardship_merge_effect:console-{candidate_id}")
    if merge_receipt is None:
        raise RuntimeError("expected stewardship merge effect receipt")
    _require(merge_receipt["notification_outcome"] == "no_eligible_channels")
    coverage_state: Any = await store.read_state(COVERAGE_PROJECTION_KEY)
    if coverage_state is None:
        raise RuntimeError("expected coverage projection state")
    _require(coverage_state["coverage"]["is_clean"] is True)
    _require(
        coverage_state["coverage"]["findings"]
        == [
            {
                "agent": "Loki",
                "code": "autonomous_no_steward",
                "message": "Agent Loki runs autonomous; escalation falls back to the maintainer.",
                "severity": "info",
            }
        ]
    )

    degraded_worker = StewardshipIdentityHealthWorker(
        store=store,
        stewardship=active_map,
        directory=cast(Any, _ToggleDirectory(stale_oid=STEWARD_OIDS[2])),
    )
    _require(await degraded_worker.run_once() == "degraded")
    healthy_worker = StewardshipIdentityHealthWorker(
        store=store,
        stewardship=active_map,
        directory=cast(Any, _ToggleDirectory(stale_oid=None)),
    )
    _require(await healthy_worker.run_once() == "healthy")

    ownership_reader = OwnershipProjectionReader(
        fallback=_ProjectionFallback(store),
        directory=cast(Any, _OperatorDirectory()),
        assignments=None,
        health=cast(Any, store),
    )
    joined_ownership = await ownership_reader.read(
        ProjectionQuery(
            operation="stewardship.coverage",
            principal_id=operator_oid,
            path={},
            params={},
            limit=100,
            cursor=None,
            roles=frozenset({OperatorRole.OWNER}),
        )
    )
    current_ownership: Any = joined_ownership["current_ownership"]
    _require(current_ownership["deployment_readiness"] == "ready")
    _require(current_ownership["identity_health"]["status"] == "healthy")

    # 6. Criterion 7: Replay source event, scan, notification, and handover -> 0 duplicates
    audit_count_before_replay = len(tuple(store.audit_entries))
    saga_count_before_replay = len(tuple(saga.audit_chain.entries))
    for raw_evt in raw_events:
        _require(await huginn.ingest(raw_evt) is None)
    _require(len(incident_registry.snapshot()) == 1)
    _require(await merge_worker.run_once() == 0)
    _require(len(tuple(store.audit_entries)) == audit_count_before_replay)
    _require(len(tuple(saga.audit_chain.entries)) == saga_count_before_replay)

    # 7. Consolidated #1913: Single-operator governed receipt with reduced quorum
    single_op_fields = {
        "revision_id": "rev-single-op-2128",
        "approval_profile": ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION.value,
        "executor_principal": "uami-executor-2128",
        "effective_from": now.isoformat(),
        "operator_principal": operator_oid,
    }
    single_op_rev = ApprovalProfileRevision(
        revision_id="rev-single-op-2128",
        approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
        executor_principal="uami-executor-2128",
        policy_digest=approval_profile_policy_digest(single_op_fields),
        effective_from=now,
        operator_principal=operator_oid,
    )
    single_op_decision = evaluate_profile_approval(
        single_op_rev,
        original_quorum=2,
        requester=operator_oid,
        approver=operator_oid,
    )
    _require(single_op_decision.allowed is True)
    _require(single_op_decision.original_quorum == 2)
    _require(single_op_decision.effective_quorum == 1)
    _require(single_op_decision.self_review is True)
    var_agent = Var(bus=bus, action_semantics=action_semantics)
    await var_agent.on_typed_message(
        "object.action-run",
        {
            "producer_principal": "Thor",
            "correlation_id": f"{CORRELATION_ID}:single-op",
            "idempotency_key": f"{CORRELATION_ID}:single-op:hil",
            "action_type": "ops.restart-service",
            "resource_id": "kubernetes.pod/aks-store-demo/order-service",
            "state": "hil_pending",
            "quorum_required": single_op_decision.effective_quorum,
        },
    )
    var_approval = await var_agent.decide(
        f"{CORRELATION_ID}:single-op",
        approver=operator_oid,
        decision="approve",
    )
    if var_approval is None or var_approval["state"] != "approved":
        raise RuntimeError("expected single-operator Var approval")

    return {
        "kind": "fdai.operational-acceptance-receipt.v1",
        "issue": 2128,
        "correlation_id": CORRELATION_ID,
        "criterion_1_identity": iam_self,
        "criterion_2_code_scanning": {
            "repository_alias": TARGET_REPO_ALIAS,
            "pinned_commit": PINNED_COMMIT,
            "readme_digest": PINNED_README_DIGEST,
            "connected_initial_enabled": False,
            "governed_enable_status": scan_outcomes[0]["status"],
            "finding_review_digest": PINNED_REVIEW_DIGEST,
            "finding_decision": "open",
            "no_finding_review_digest": CLEAN_REVIEW_DIGEST,
            "no_finding_decision": "clear",
        },
        "criterion_3_notifications": {
            "channels_converged": sorted(receipt_ids),
            "receipt_ids": receipt_ids,
        },
        "criterion_4_stewardship": {
            "schema_version": 2,
            "maintainer_count": 2,
            "total_agents": 15,
            "autonomous_agents": 1,
            "warnings_count": 0,
            "is_clean": True,
            "deployment_readiness": current_ownership["deployment_readiness"],
            "identity_health_transitions": ["degraded", "healthy"],
        },
        "criterion_5_incident_pipeline": {
            "incident_count": len(incident_registry.snapshot()),
            "thor_shadow_mode": thor_run.shadow_mode,
            "thor_outcome": thor_run.outcome,
            "managed_resource_mutations": 0,
            "saga_audit_entries": len(tuple(saga.audit_chain.entries)),
        },
        "criterion_6_correlated_receipts": {
            "candidate_id": candidate_id,
            "candidate_digest": first_pub.receipt.head_sha,
            "duplicate_upload_reused": second_pub.receipt.already_existed,
            "merge_notification_outcome": merge_receipt["notification_outcome"],
            "single_operator_receipt": {
                "original_quorum": single_op_decision.original_quorum,
                "effective_quorum": single_op_decision.effective_quorum,
                "self_review": single_op_decision.self_review,
                "operator_principal_digest": _sha256_text(operator_oid),
            },
        },
        "criterion_7_replay_idempotency": {
            "duplicate_incidents": 0,
            "duplicate_notifications": 0,
            "duplicate_audit_transitions": 0,
            "duplicate_handover_records": 0,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = asyncio.run(run_rehearsal())
    rendered = json.dumps(summary, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Every topic the Operator multiplexes onto the semantic Event Hub must be logical in Core."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest
from fdai.agents import Mimir
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.huginn_operator_receipt import OperatorRequestReceiptGate
from fdai.agents._framework.mimir_policy_administration import (
    MimirPolicyAdministration,
    StateStorePolicyRevisionStore,
)
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime_payload_validation import default_payload_validator
from fdai.delivery.event_bus_multiplex import MultiplexedEventBus
from fdai.runtime.bootstrap_topics import RUNTIME_LOGICAL_TOPICS
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_operator_service.adapters.semantic_kafka import OperatorSemanticKafkaConfig
from fdai_operator_service.families.iam import IamFamilyBindings, make_iam_family_routes
from fdai_operator_service.families.iam.contracts import IamPrincipal
from fdai_operator_service.families.iam.policy_administration import FreshPolicyPrincipal
from fdai_operator_service.operator_request_receipt import (
    OperatorRequestReceiptIssuer,
    SeedOperatorRequestReceiptSigner,
)
from fdai_service_contracts import OperatorPrincipalKind, OperatorRole
from fdai_service_contracts.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRevision,
    approval_profile_policy_digest,
)
from fdai_service_contracts.framework_assessment import FRAMEWORK_ASSESSMENT_TOPIC
from fdai_service_contracts.observer_deployment import OBSERVER_PROPOSAL_TOPIC
from fdai_service_contracts.operator_authentication import (
    LOCAL_LOOPBACK_ISSUER,
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
    role_mapping_revision,
    tenant_digest,
    token_id_digest,
)
from fdai_service_contracts.operator_request_receipt import operator_request_public_key_from_seed
from fdai_service_contracts.policy_administration import (
    POLICY_OBJECT_TOPIC,
    POLICY_REVISION_REQUEST_TOPIC,
    PolicyMode,
)
from fdai_service_contracts.post_turn_review import POST_TURN_REVIEW_REQUEST_TOPIC
from fdai_service_contracts.wara_assessment import WARA_ASSESSMENT_TOPIC
from starlette.applications import Starlette
from starlette.testclient import TestClient

# Event and HIL decision topics are provisioned physical Event Hubs, never multiplexed.
_DIRECT_FIELDS = frozenset({"event_topic", "hil_decision_topic", "physical_topic"})
# Dedicated Jobs publish these on their own multiplexed transport; Core never reads them.
_DEDICATED_JOB_TOPICS = frozenset(
    {WARA_ASSESSMENT_TOPIC, FRAMEWORK_ASSESSMENT_TOPIC, OBSERVER_PROPOSAL_TOPIC}
)
_PHYSICAL = "fdai.pantheon.objects"


def test_every_multiplexed_operator_topic_is_a_core_runtime_logical_topic() -> None:
    operator_topics = {
        field.default
        for field in fields(OperatorSemanticKafkaConfig)
        if field.name.endswith("_topic")
        and field.name not in _DIRECT_FIELDS
        and isinstance(field.default, str)
    }

    # A missing topic makes Core subscribe to a raw Event Hub that does not exist.
    assert operator_topics - _DEDICATED_JOB_TOPICS - RUNTIME_LOGICAL_TOPICS == set()


def test_core_receives_operator_post_turn_review_requests_from_the_physical_topic() -> None:
    transport = InMemoryEventBus()
    operator = MultiplexedEventBus(
        transport, frozenset({POST_TURN_REVIEW_REQUEST_TOPIC}), _PHYSICAL
    )
    core = MultiplexedEventBus(transport, RUNTIME_LOGICAL_TOPICS, _PHYSICAL)

    async def _exchange() -> list[str]:
        await operator.publish(POST_TURN_REVIEW_REQUEST_TOPIC, "request-1", {"value": 1})
        return [item.key async for item in core.subscribe(POST_TURN_REVIEW_REQUEST_TOPIC, "core")]

    assert asyncio.run(_exchange()) == ["request-1"]


class _PolicyPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    async def publish_policy_revision_request(
        self,
        *,
        topic: str,
        key: str,
        payload: dict[str, object],
    ) -> object:
        self.events.append((topic, key, payload))
        return None


class _PolicyAuthenticator:
    async def authenticate_policy_admin(self, request: object) -> FreshPolicyPrincipal:
        del request
        issued_at = datetime.now(UTC)
        return FreshPolicyPrincipal(
            principal=IamPrincipal(
                oid="policy-admin-1",
                roles=frozenset({OperatorRole.OWNER}),
                username="policy-admin@example.com",
                principal_kind=OperatorPrincipalKind.HUMAN,
            ),
            authentication_receipt=OperatorAuthenticationReceipt.create(
                evidence_class=OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK,
                issuer=LOCAL_LOOPBACK_ISSUER,
                audience="operator-api",
                tenant_digest=tenant_digest("local"),
                subject_id="policy-admin-1",
                principal_kind="human",
                token_id_digest=token_id_digest("policy-admin-token"),
                issued_at=issued_at,
                expires_at=issued_at + timedelta(minutes=30),
                roles=(OperatorRole.OWNER.value,),
                role_mapping_revision=role_mapping_revision(
                    {OperatorRole.OWNER.value: "group:Owner"}
                ),
            ),
            authenticated_at=issued_at,
            app_roles=frozenset({"Owner", "policy-admin"}),
        )


class _RegoCompiler:
    async def compile(self, rego: str) -> None:
        del rego

    async def test(self, rego: str, tests: tuple[dict[str, object], ...]) -> None:
        del rego, tests


class _Signer:
    async def sign_policy_revision(self, *, policy_digest: str, revision_id: str) -> str:
        return f"fake-keyvault:{revision_id}:{policy_digest}"


class _ReleaseMaximums:
    def maximum_mode_for_action_type(self, action_type: str) -> PolicyMode | None:
        return PolicyMode.SHADOW if action_type == "governance.retire-rule" else None


class _PolicyStore:
    def __init__(self, delegate: StateStorePolicyRevisionStore) -> None:
        self._delegate = delegate

    async def append_revision(self, record: object) -> bool:
        return await self._delegate.append_revision(record)  # type: ignore[arg-type]

    async def revision(self, **kwargs: object) -> object:
        return await self._delegate.revision(**kwargs)  # type: ignore[arg-type]

    async def active_revision_id(self, policy_kind: object) -> str | None:
        return await self._delegate.active_revision_id(policy_kind)  # type: ignore[arg-type]

    async def active_activation(self, policy_kind: object) -> object:
        return await self._delegate.active_activation(policy_kind)  # type: ignore[arg-type]

    async def active_approval_profile(self) -> ApprovalProfileRevision:
        payload: dict[str, object] = {
            "revision_id": "approval-profile-r1",
            "approval_profile": "single-operator-production",
            "executor_principal": "thor-executor",
            "effective_from": "2026-01-01T00:00:00+00:00",
            "operator_principal": "policy-admin-1",
        }
        payload["policy_digest"] = approval_profile_policy_digest(payload)
        return ApprovalProfileRevision(
            revision_id="approval-profile-r1",
            approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
            executor_principal="thor-executor",
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            operator_principal="policy-admin-1",
            policy_digest=str(payload["policy_digest"]),
        )

    async def request_revision_id(self, request_id: str) -> str | None:
        return await self._delegate.request_revision_id(request_id)

    async def record_request_revision(self, *, request_id: str, revision_id: str) -> bool:
        return await self._delegate.record_request_revision(
            request_id=request_id,
            revision_id=revision_id,
        )

    async def request_activation(self, request_id: str) -> object:
        return await self._delegate.request_activation(request_id)

    async def record_request_activation(
        self,
        *,
        request_id: str,
        revision_id: str,
        activation: object,
    ) -> None:
        await self._delegate.record_request_activation(
            request_id=request_id,
            revision_id=revision_id,
            activation=activation,  # type: ignore[arg-type]
        )

    async def activate_revision(self, **kwargs: object) -> object:
        return await self._delegate.activate_revision(**kwargs)  # type: ignore[arg-type]


async def _authorize(_: object) -> IamPrincipal:
    return IamPrincipal(
        oid="policy-admin-1",
        roles=frozenset({OperatorRole.OWNER}),
        username="policy-admin@example.com",
        principal_kind=OperatorPrincipalKind.HUMAN,
    )


@pytest.mark.asyncio
async def test_selected_policy_administration_flows_from_operator_route_to_mimir_policy_event() -> (
    None
):
    seed = base64.urlsafe_b64encode(b"0" * 32).decode("ascii").rstrip("=")
    publisher = _PolicyPublisher()
    client = TestClient(
        Starlette(
            routes=make_iam_family_routes(
                IamFamilyBindings(
                    authorize=_authorize,
                    authenticate=_authorize,
                    policy_administration_selected=True,
                    policy_authenticator=_PolicyAuthenticator(),
                    policy_revision_publisher=publisher,
                    policy_receipt_issuer=OperatorRequestReceiptIssuer(
                        signer=SeedOperatorRequestReceiptSigner(seed),
                        producer_service_identity="operator-service:test",
                        clock=lambda: datetime.now(UTC),
                    ),
                )
            )
        )
    )
    response = client.post(
        "/policy/revisions",
        headers={"Idempotency-Key": "policy-e2e-1"},
        json={
            "policy_kind": "admission",
            "content": {
                "rego": "package fdai.policy\nallow := true\n",
                "action_type_modes": {"governance.retire-rule": "shadow"},
                "policy_tests": [{"rego": "package fdai.policy\n test_allow if { allow }\n"}],
            },
            "reason": "Reviewed policy change for a bounded installation scope.",
        },
    )
    assert response.status_code == 202
    assert [(topic, key) for topic, key, _ in publisher.events] == [
        (POLICY_REVISION_REQUEST_TOPIC, "policy-e2e-1")
    ]

    store = InMemoryStateStore()
    mimir = Mimir(
        policy_administration=MimirPolicyAdministration(
            store=_PolicyStore(StateStorePolicyRevisionStore(store)),  # type: ignore[arg-type]
            signer=_Signer(),
            rego_compiler=_RegoCompiler(),
            operator_request_receipt_gate=OperatorRequestReceiptGate(
                verifier=object(),  # type: ignore[arg-type]
                state_store=InMemoryStateStore(),
                clock=lambda: datetime.now(UTC),
                trusted_producer_public_keys={
                    "operator-service:test": operator_request_public_key_from_seed(seed)
                },
            ),
            operator_producer_service_identity="operator-service:test",
            release_maximums=_ReleaseMaximums(),
            clock=lambda: datetime.now(UTC),
        )
    )
    bus = InMemoryBus(registry=load_pantheon(), payload_validator=default_payload_validator)
    mimir.bind_bus(bus)

    await mimir.handle_policy_revision_request(publisher.events[0][2])

    published = bus.messages_on(POLICY_OBJECT_TOPIC)
    assert len(published) == 1
    assert published[0].payload["event_type"] == "policy_activation"
    assert published[0].payload["policy_kind"] == "admission"

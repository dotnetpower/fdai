"""Mimir policy-administration validation and activation tests."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta

import pytest
from fdai.agents import Mimir
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.huginn_operator_receipt import OperatorRequestReceiptGate
from fdai.agents._framework.mimir_policy_administration import (
    MimirPolicyAdministration,
    OpaRegoPolicyCompiler,
    PolicyRevisionRejectedError,
    StateStorePolicyRevisionStore,
)
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.runtime_payload_validation import default_payload_validator
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRevision,
    approval_profile_policy_digest,
)
from fdai_service_contracts.operator_authentication import (
    LOCAL_LOOPBACK_ISSUER,
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
    role_mapping_revision,
    tenant_digest,
    token_id_digest,
)
from fdai_service_contracts.operator_request_receipt import (
    OperatorRequestReceipt,
    OperatorRequestReceiptBody,
    operator_request_receipt_body_from_event,
    operator_request_receipt_signing_bytes,
)
from fdai_service_contracts.policy_administration import (
    AdmissionPolicyContent,
    ApprovalPolicyContent,
    PolicyKind,
    PolicyMode,
    PolicyRevisionRecord,
    PolicyRevisionRequestBody,
    PolicyRevisionRequestEvent,
    PolicyValidationResult,
    policy_content_digest,
    policy_validation_digest,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
CAPABILITIES = "rule-catalog/schema/policy_admin_opa_capabilities.json"


class FakeSigner:
    async def sign_policy_revision(self, *, policy_digest: str, revision_id: str) -> str:
        return f"fake-keyvault-signature:{revision_id}:{policy_digest}"


def test_policy_admin_capabilities_pin_rego_v1_and_remove_unsafe_builtins() -> None:
    capabilities = json.loads(open(CAPABILITIES, encoding="utf-8").read())
    names = {item["name"] for item in capabilities["builtins"]}
    assert capabilities["allow_net"] == []
    assert "rego_v1" in capabilities["features"]
    for name in {
        "json.match_schema",
        "json.verify_schema",
        "io.jwt.decode_verify",
        "io.jwt.encode_sign",
        "crypto.x509.parse_and_verify_certificates",
        "http.send",
        "time.now_ns",
        "rand.intn",
        "opa.runtime",
    }:
        assert name not in names
    assert not any(name.startswith("net.") for name in names)


def test_policy_administration_requires_receipt_gate() -> None:
    with pytest.raises(ValueError, match="OperatorRequestReceiptGate"):
        MimirPolicyAdministration(
            store=RecordingPolicyStore(StateStorePolicyRevisionStore(InMemoryStateStore()), None),
            signer=FakeSigner(),
            rego_compiler=FakeRegoCompiler(),
            operator_request_receipt_gate=None,  # type: ignore[arg-type]
            operator_producer_service_identity="operator-service:test",
            clock=lambda: NOW,
        )


class FakeRegoCompiler:
    def __init__(self) -> None:
        self.compiled: list[str] = []

    async def compile(self, rego: str) -> None:
        if "http.send" in rego:
            raise PolicyRevisionRejectedError("rego_builtin_denied")
        self.compiled.append(rego)

    async def test(self, rego: str, tests: tuple[dict[str, object], ...]) -> None:
        if tests and "fail" in str(tests[0].get("rego", "")):
            raise PolicyRevisionRejectedError("policy_test_failed")
        return None


class FakeMaximums:
    def __init__(self, values: dict[str, PolicyMode]) -> None:
        self._values = values

    def maximum_mode_for_action_type(self, action_type: str) -> PolicyMode | None:
        return self._values.get(action_type)


class RecordingPolicyStore:
    def __init__(
        self,
        delegate: StateStorePolicyRevisionStore,
        profile: ApprovalProfileRevision | None,
    ) -> None:
        self._delegate = delegate
        self._profile = profile

    async def append_revision(self, record):
        return await self._delegate.append_revision(record)

    async def revision(self, *, policy_kind, revision_id):
        return await self._delegate.revision(policy_kind=policy_kind, revision_id=revision_id)

    async def active_revision_id(self, policy_kind):
        return await self._delegate.active_revision_id(policy_kind)

    async def active_activation(self, policy_kind):
        return await self._delegate.active_activation(policy_kind)

    async def active_approval_profile(self):
        return self._profile

    async def request_revision_id(self, request_id):
        return await self._delegate.request_revision_id(request_id)

    async def record_request_revision(self, *, request_id, revision_id):
        return await self._delegate.record_request_revision(
            request_id=request_id,
            revision_id=revision_id,
        )

    async def request_activation(self, request_id):
        return await self._delegate.request_activation(request_id)

    async def record_request_activation(self, *, request_id, revision_id, activation):
        await self._delegate.record_request_activation(
            request_id=request_id,
            revision_id=revision_id,
            activation=activation,
        )

    async def activate_revision(self, **kwargs):
        return await self._delegate.activate_revision(**kwargs)


class SwitchablePolicyStore(RecordingPolicyStore):
    def set_profile(self, profile: ApprovalProfileRevision | None) -> None:
        self._profile = profile


class FailingOutcomePolicyStore(RecordingPolicyStore):
    def __init__(
        self,
        delegate: StateStorePolicyRevisionStore,
        profile: ApprovalProfileRevision | None,
    ) -> None:
        super().__init__(delegate, profile)
        self.failures_remaining = 1
        self.recorded_outcomes = 0

    async def record_request_activation(self, *, request_id, revision_id, activation):
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise ConnectionError("transient outcome write failure")
        self.recorded_outcomes += 1
        await super().record_request_activation(
            request_id=request_id,
            revision_id=revision_id,
            activation=activation,
        )


class PostgresSemanticsStateStore(InMemoryStateStore):
    async def compare_and_set_state_with_audit(self, key, value, *, expected_revision, audit_entry):
        if await self.read_state(key) is None:
            return False
        return await super().compare_and_set_state_with_audit(
            key,
            value,
            expected_revision=expected_revision,
            audit_entry=audit_entry,
        )


class FakeReceiptVerifier:
    def verify_operator_request_receipt(
        self,
        *,
        receipt: OperatorRequestReceipt,
        signing_bytes: bytes,
    ) -> bool:
        return receipt.signature_bytes().startswith(b"sig:") and bool(signing_bytes)


@pytest.mark.asyncio
async def test_mimir_validates_stores_activates_and_publishes_policy() -> None:
    store = InMemoryStateStore()
    compiler = FakeRegoCompiler()
    mimir = Mimir(
        policy_administration=MimirPolicyAdministration(
            store=RecordingPolicyStore(StateStorePolicyRevisionStore(store), _single_profile()),
            signer=FakeSigner(),
            rego_compiler=compiler,
            release_maximums=FakeMaximums({"governance.retire-rule": PolicyMode.SHADOW}),
            operator_request_receipt_gate=OperatorRequestReceiptGate(
                verifier=FakeReceiptVerifier(),
                state_store=InMemoryStateStore(),
                clock=lambda: NOW,
            ),
            operator_producer_service_identity="operator-service:test",
            clock=lambda: NOW,
        )
    )
    bus = InMemoryBus(registry=load_pantheon(), payload_validator=default_payload_validator)
    mimir.bind_bus(bus)

    event = await mimir.handle_policy_revision_request(
        _request({"governance.retire-rule": "shadow"}).model_dump(mode="json")
    )

    assert event["event_type"] == "policy_activation"
    assert event["kind"] == "policy_activation"
    assert event["policy_id"]
    assert event["policy_kind"] == "admission"
    assert len(compiler.compiled) == 1
    assert await store.read_state(f"policy_activation:{PolicyKind.ADMISSION.value}") is not None
    assert len(bus.messages_on("object.policy")) == 1
    assert bus.messages_on("object.policy")[0].payload["revision_id"] == event["revision_id"]


@pytest.mark.asyncio
async def test_mimir_rejects_malformed_schema() -> None:
    admin = _admin()

    with pytest.raises(PolicyRevisionRejectedError, match="malformed_schema"):
        await admin.handle_request({"event_type": "policy_revision_request"})


@pytest.mark.asyncio
async def test_mimir_rejects_unrestricted_rego() -> None:
    admin = _admin(rego_compiler=FakeRegoCompiler())

    with pytest.raises(PolicyRevisionRejectedError, match="rego_builtin_denied"):
        await admin.handle_request(
            _request({}, rego="package fdai.policy\nx := http.send({})\n").model_dump(mode="json")
        )


@pytest.mark.asyncio
async def test_mimir_rejects_revision_above_release_maximum() -> None:
    admin = _admin(maximums=FakeMaximums({"governance.retire-rule": PolicyMode.SHADOW}))

    with pytest.raises(PolicyRevisionRejectedError, match="release_maximum_exceeded"):
        await admin.handle_request(
            _request({"governance.retire-rule": "enforce"}).model_dump(mode="json")
        )


@pytest.mark.asyncio
async def test_mimir_rejects_admission_without_policy_tests() -> None:
    admin = _admin()
    event = _request({})
    content = event.content
    assert isinstance(content, AdmissionPolicyContent)
    body = PolicyRevisionRequestBody(
        policy_kind=PolicyKind.ADMISSION,
        content=AdmissionPolicyContent(rego=content.rego, action_type_modes={}),
        parent_revision_id=None,
        reason=event.reason,
    )
    no_tests = PolicyRevisionRequestEvent.create(
        body=body,
        request_id="request-no-tests",
        correlation_id="policy-revision:request-no-tests",
        idempotency_key="policy-request-no-tests",
        author_principal="policy-admin-1",
        requested_at=NOW,
        authentication_receipt=_receipt(),
        operator_request_receipt=_operator_request_receipt(
            body,
            request_id="request-no-tests",
            correlation_id="policy-revision:request-no-tests",
            idempotency_key="policy-request-no-tests",
            app_roles=frozenset({"Owner", "policy-admin"}),
            author_principal="policy-admin-1",
            authenticated_at=NOW - timedelta(minutes=1),
        ),
    )
    with pytest.raises(PolicyRevisionRejectedError, match="policy_tests_missing"):
        await admin.handle_request(no_tests.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_mimir_rejects_malformed_and_relaxing_approval_policy() -> None:
    admin = _admin(profile=None)
    with pytest.raises(PolicyRevisionRejectedError, match="approval_policy_invalid"):
        await admin.handle_request(
            _approval_request(
                {
                    "approval_profile": "single-operator-production",
                    "operator_principal": "policy-admin-1",
                    "quorum": 0,
                }
            ).model_dump(mode="json")
        )
    with pytest.raises(PolicyRevisionRejectedError, match="approval_policy_requires_quorum"):
        await admin.handle_request(
            _approval_request(_single_operator_document()).model_dump(mode="json")
        )


@pytest.mark.asyncio
async def test_mimir_rejects_missing_wrong_role_subject_and_stale_receipts() -> None:
    admin = _admin()
    with pytest.raises(PolicyRevisionRejectedError, match="operator_request_receipt_missing"):
        await admin.handle_request(
            _request({}, include_operator_receipt=False).model_dump(mode="json")
        )
    with pytest.raises(PolicyRevisionRejectedError, match="policy_admin_role_missing"):
        await admin.handle_request(
            _request({}, app_roles=frozenset({"Owner"})).model_dump(mode="json")
        )
    with pytest.raises(PolicyRevisionRejectedError, match="author_principal_mismatch"):
        await admin.handle_request(
            _request({}, receipt_author="other-admin").model_dump(mode="json")
        )
    with pytest.raises(PolicyRevisionRejectedError, match="auth_time_stale"):
        await admin.handle_request(
            _request({}, authenticated_at=NOW - timedelta(minutes=30)).model_dump(mode="json")
        )


@pytest.mark.asyncio
async def test_mimir_rejects_unnamed_admission_author_under_single_operator() -> None:
    admin = _admin()

    with pytest.raises(PolicyRevisionRejectedError, match="approval_policy_author_not_operator"):
        await admin.handle_request(
            _request({}, author_principal="admin-b", receipt_author="admin-b").model_dump(
                mode="json"
            )
        )


@pytest.mark.asyncio
async def test_mimir_replay_returns_this_request_outcome_without_reactivation() -> None:
    store = InMemoryStateStore()
    admin = _admin(store=store)
    payload = _request({}).model_dump(mode="json")

    first = await admin.handle_request(payload)
    pointer = await store.read_state("policy_activation:admission")
    assert pointer is not None
    second = await admin.handle_request(payload)

    assert second == first
    assert await store.read_state("policy_activation:admission") == pointer


@pytest.mark.asyncio
async def test_mimir_redelivery_records_outcome_and_publishes_once_after_transient_failure() -> (
    None
):
    state = InMemoryStateStore()
    store = FailingOutcomePolicyStore(StateStorePolicyRevisionStore(state), _single_profile())
    mimir = Mimir(
        policy_administration=MimirPolicyAdministration(
            store=store,
            signer=FakeSigner(),
            rego_compiler=FakeRegoCompiler(),
            release_maximums=None,
            operator_request_receipt_gate=OperatorRequestReceiptGate(
                verifier=FakeReceiptVerifier(),
                state_store=InMemoryStateStore(),
                clock=lambda: NOW,
            ),
            operator_producer_service_identity="operator-service:test",
            clock=lambda: NOW,
        )
    )
    provider = InMemoryEventBus()
    bridge = EventBusBridge(
        provider=provider,
        registry=load_pantheon(),
        payload_validator=default_payload_validator,
    )
    mimir.bind_bus(bridge)
    payload = _request({}).model_dump(mode="json")

    with pytest.raises(ConnectionError):
        await mimir.handle_policy_revision_request(payload)
    await bridge._deliver("operator.policy-revision.requests", mimir.on_typed_message, payload)

    assert store.recorded_outcomes == 1
    assert len(provider._records.get("object.policy", ())) == 1


@pytest.mark.asyncio
async def test_mimir_first_activation_uses_insert_for_postgres_semantics() -> None:
    store = PostgresSemanticsStateStore()
    admin = _admin(store=store)

    event = await admin.handle_request(_request({}).model_dump(mode="json"))

    assert event.policy_kind is PolicyKind.ADMISSION
    assert await store.read_state("policy_activation:admission") is not None


@pytest.mark.asyncio
async def test_mimir_replay_rechecks_current_profile_before_activation() -> None:
    state = InMemoryStateStore()
    store = SwitchablePolicyStore(StateStorePolicyRevisionStore(state), _single_profile())
    admin = MimirPolicyAdministration(
        store=store,
        signer=FakeSigner(),
        rego_compiler=FakeRegoCompiler(),
        operator_request_receipt_gate=OperatorRequestReceiptGate(
            verifier=FakeReceiptVerifier(),
            state_store=InMemoryStateStore(),
            clock=lambda: NOW,
        ),
        operator_producer_service_identity="operator-service:test",
        clock=lambda: NOW,
    )
    payload = _request({}).model_dump(mode="json")
    event = PolicyRevisionRequestEvent.model_validate(payload)
    content_digest = policy_content_digest(event.content)
    revision_id = _expected_revision_id(content_digest)
    record = _revision_record(event, revision_id, content_digest)
    assert await store.append_revision(record) is True
    assert await store.record_request_revision(request_id=event.request_id, revision_id=revision_id)
    store.set_profile(None)

    with pytest.raises(
        PolicyRevisionRejectedError,
        match="admission_policy_requires_single_operator",
    ):
        await admin.handle_request(payload)


@pytest.mark.asyncio
async def test_mimir_replay_rejects_same_key_different_body() -> None:
    state = InMemoryStateStore()
    store = SwitchablePolicyStore(StateStorePolicyRevisionStore(state), _single_profile())
    admin = MimirPolicyAdministration(
        store=store,
        signer=FakeSigner(),
        rego_compiler=FakeRegoCompiler(),
        operator_request_receipt_gate=OperatorRequestReceiptGate(
            verifier=FakeReceiptVerifier(),
            state_store=InMemoryStateStore(),
            clock=lambda: NOW,
        ),
        operator_producer_service_identity="operator-service:test",
        clock=lambda: NOW,
    )
    event = _request({})
    content_digest = policy_content_digest(event.content)
    revision_id = _expected_revision_id(content_digest)
    assert await store.append_revision(_revision_record(event, revision_id, content_digest)) is True
    assert await store.record_request_revision(request_id=event.request_id, revision_id=revision_id)

    with pytest.raises(PolicyRevisionRejectedError, match="request_replay_content_mismatch"):
        await admin.handle_request(
            _request({}, rego="package fdai.policy\nallow := false\n").model_dump(mode="json")
        )


@pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary is not installed")
@pytest.mark.parametrize(
    "rego",
    [
        'package fdai.policy\nx := http["send"]({})\n',
        'package fdai.policy\nx := net["lookup_ip_addr"]("example.com")\n',
        'package fdai.policy\nx := opa["runtime"]()\n',
        "package fdai.policy\nx := time.now_ns()\n",
        "package fdai.policy\nx := rand.intn(5)\n",
        'package fdai.policy\nx := uuid.rfc4122("x")\n',
        'package fdai.policy\nx := print("x")\n',
        'package fdai.policy\nx := json.match_schema({}, {"$ref": "http://127.0.0.1/schema.json"})\n',
        'package fdai.policy\nx := json.verify_schema({"$ref": "file:///tmp/schema.json"})\n',
        'package fdai.policy\nx := io.jwt.decode_verify("x", {"cert": "y"})\n',
        'package fdai.policy\nx := io.jwt.encode_sign({"alg":"ES256"}, {}, "k")\n',
        'package fdai.policy\nx := crypto.x509.parse_and_verify_certificates("", [])\n',
    ],
)
@pytest.mark.asyncio
async def test_opa_capabilities_reject_unavailable_builtins(rego: str) -> None:
    with pytest.raises(PolicyRevisionRejectedError):
        await OpaRegoPolicyCompiler().compile(rego)


@pytest.mark.skipif(shutil.which("opa") is None, reason="opa binary is not installed")
@pytest.mark.asyncio
async def test_opa_capabilities_allow_comment_only_builtin_mentions() -> None:
    await OpaRegoPolicyCompiler().compile(
        "package fdai.policy\n# http.send is not used\nallow := true\n"
    )


def _admin(
    *,
    rego_compiler: FakeRegoCompiler | None = None,
    maximums: FakeMaximums | None = None,
    profile: ApprovalProfileRevision | None | str = "single",
    store: InMemoryStateStore | None = None,
) -> MimirPolicyAdministration:
    selected_profile = _single_profile() if profile == "single" else profile
    selected_store = store or InMemoryStateStore()
    return MimirPolicyAdministration(
        store=RecordingPolicyStore(StateStorePolicyRevisionStore(selected_store), selected_profile),
        signer=FakeSigner(),
        rego_compiler=rego_compiler or FakeRegoCompiler(),
        release_maximums=maximums,
        operator_request_receipt_gate=OperatorRequestReceiptGate(
            verifier=FakeReceiptVerifier(),
            state_store=InMemoryStateStore(),
            clock=lambda: NOW,
        ),
        operator_producer_service_identity="operator-service:test",
        clock=lambda: NOW,
    )


def _request(
    modes: dict[str, str],
    *,
    rego: str = "package fdai.policy\nallow := true\n",
    app_roles: frozenset[str] = frozenset({"Owner", "policy-admin"}),
    author_principal: str = "policy-admin-1",
    receipt_author: str = "policy-admin-1",
    authenticated_at: datetime = NOW - timedelta(minutes=1),
    include_operator_receipt: bool = True,
) -> PolicyRevisionRequestEvent:
    body = PolicyRevisionRequestBody(
        policy_kind=PolicyKind.ADMISSION,
        content=AdmissionPolicyContent(
            rego=rego,
            action_type_modes={key: PolicyMode(value) for key, value in sorted(modes.items())},
            policy_tests=({"rego": "package fdai.policy\n test_allow if { true }\n"},),
        ),
        parent_revision_id=None,
        reason="Reviewed policy change for a bounded installation scope.",
    )
    return PolicyRevisionRequestEvent.create(
        body=body,
        request_id="request-1",
        correlation_id="policy-revision:request-1",
        idempotency_key="policy-request-1",
        author_principal=author_principal,
        requested_at=NOW,
        authentication_receipt=_receipt(),
        operator_request_receipt=(
            _operator_request_receipt(
                body,
                request_id="request-1",
                correlation_id="policy-revision:request-1",
                idempotency_key="policy-request-1",
                app_roles=app_roles,
                author_principal=receipt_author,
                authenticated_at=authenticated_at,
            )
            if include_operator_receipt
            else None
        ),
    )


def _approval_request(document: dict[str, object]) -> PolicyRevisionRequestEvent:
    body = PolicyRevisionRequestBody(
        policy_kind=PolicyKind.APPROVAL,
        content=ApprovalPolicyContent(document=document, action_type_modes={}),
        parent_revision_id=None,
        reason="Reviewed approval policy change for a bounded installation scope.",
    )
    return PolicyRevisionRequestEvent.create(
        body=body,
        request_id="approval-request-1",
        correlation_id="policy-revision:approval-request-1",
        idempotency_key="policy-approval-request-1",
        author_principal="policy-admin-1",
        requested_at=NOW,
        authentication_receipt=_receipt(),
        operator_request_receipt=_operator_request_receipt(
            body,
            request_id="approval-request-1",
            correlation_id="policy-revision:approval-request-1",
            idempotency_key="policy-approval-request-1",
            app_roles=frozenset({"Owner", "policy-admin"}),
            author_principal="policy-admin-1",
            authenticated_at=NOW - timedelta(minutes=1),
        ),
    )


def _single_operator_document() -> dict[str, object]:
    value: dict[str, object] = {
        "revision_id": "approval-profile-r1",
        "approval_profile": "single-operator-production",
        "executor_principal": "executor-1",
        "effective_from": NOW.isoformat(),
        "operator_principal": "policy-admin-1",
    }
    value["policy_digest"] = approval_profile_policy_digest(value)
    return value


def _single_profile() -> ApprovalProfileRevision:
    document = _single_operator_document()
    return ApprovalProfileRevision(
        revision_id=str(document["revision_id"]),
        approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
        executor_principal=str(document["executor_principal"]),
        policy_digest=str(document["policy_digest"]),
        effective_from=NOW,
        operator_principal=str(document["operator_principal"]),
    )


def _expected_revision_id(content_digest: str) -> str:
    seed = f"admission\0{content_digest}\0"
    return "admission:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _revision_record(
    event: PolicyRevisionRequestEvent,
    revision_id: str,
    content_digest: str,
) -> PolicyRevisionRecord:
    validation = PolicyValidationResult(
        rego_valid=True,
        release_maximums_valid=True,
        policy_tests_valid=True,
        validation_digest=policy_validation_digest(
            {
                "schema_valid": True,
                "rego_valid": True,
                "release_maximums_valid": True,
                "policy_tests_valid": True,
                "request_digest": event.request_digest,
                "content_digest": content_digest,
            }
        ),
        details=("schema", "restricted-rego", "policy-tests", "release-maximums"),
    )
    return PolicyRevisionRecord(
        revision_id=revision_id,
        policy_kind=event.policy_kind,
        content_digest=content_digest,
        content=event.content,
        signature_ref="fake-signature",
        parent_revision_id=event.parent_revision_id,
        author_principal=event.author_principal,
        reason=event.reason,
        created_at=NOW,
        activated_at=None,
        validation=validation,
        diff_digest="sha256:" + "d" * 64,
    )


def _receipt() -> OperatorAuthenticationReceipt:
    return OperatorAuthenticationReceipt.create(
        evidence_class=OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK,
        issuer=LOCAL_LOOPBACK_ISSUER,
        audience="operator-api",
        tenant_digest=tenant_digest("local"),
        subject_id="policy-admin-1",
        principal_kind="human",
        token_id_digest=token_id_digest("policy-token"),
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=29),
        roles=("Owner",),
        role_mapping_revision=role_mapping_revision({"Owner": "group:owners"}),
    )


def _operator_request_receipt(
    body: PolicyRevisionRequestBody,
    *,
    request_id: str,
    correlation_id: str,
    idempotency_key: str,
    app_roles: frozenset[str],
    author_principal: str,
    authenticated_at: datetime,
) -> OperatorRequestReceipt:
    raw = PolicyRevisionRequestEvent.operator_receipt_event(
        body=body,
        request_id=request_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        author_principal=author_principal,
        authenticated_at=authenticated_at,
        app_roles=app_roles,
    )
    receipt_body = operator_request_receipt_body_from_event(
        raw,
        producer_service_identity="operator-service:test",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=14),
    )
    return OperatorRequestReceipt.create(
        body=OperatorRequestReceiptBody.model_validate(receipt_body.model_dump(mode="json")),
        signature=b"sig:" + operator_request_receipt_signing_bytes(receipt_body)[:16],
    )

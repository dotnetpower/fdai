"""Mimir-owned policy revision validation, signing, storage, and activation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from fdai_service_contracts.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRevision,
    evaluate_profile_approval,
    profile_transition_quorum,
)
from fdai_service_contracts.policy_administration import (
    POLICY_OBJECT_TOPIC,
    AdmissionPolicyContent,
    ApprovalPolicyContent,
    PolicyActivationEvent,
    PolicyKind,
    PolicyMode,
    PolicyRevisionRecord,
    PolicyRevisionRequestEvent,
    PolicyValidationResult,
    ReleaseCapabilityMaximums,
    policy_content_digest,
    policy_validation_digest,
)
from pydantic import ValidationError

from fdai.agents._framework.huginn_operator_receipt import OperatorRequestReceiptGate
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.delivery.repo_assets import repo_asset_root
from fdai.shared.providers.state_store import StateStore

_MAX_CONTENT_BYTES = 250_000
_CAPABILITIES_RELATIVE = "rule-catalog/schema/policy_admin_opa_capabilities.json"


class PolicyRevisionRejectedError(ValueError):
    """Raised when Mimir rejects a policy revision before activation."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PolicyRevisionSigner(Protocol):
    """Sign one content digest with the installation policy key."""

    async def sign_policy_revision(self, *, policy_digest: str, revision_id: str) -> str: ...


class PolicyRevisionStore(Protocol):
    """Append immutable revisions and move one activation pointer with CAS."""

    async def append_revision(self, record: PolicyRevisionRecord) -> bool: ...

    async def revision(
        self,
        *,
        policy_kind: PolicyKind,
        revision_id: str,
    ) -> PolicyRevisionRecord | None: ...

    async def active_revision_id(self, policy_kind: PolicyKind) -> str | None: ...

    async def active_activation(self, policy_kind: PolicyKind) -> PolicyActivationEvent | None: ...

    async def active_approval_profile(self) -> ApprovalProfileRevision | None: ...

    async def request_revision_id(self, request_id: str) -> str | None: ...

    async def record_request_revision(self, *, request_id: str, revision_id: str) -> bool: ...

    async def request_activation(self, request_id: str) -> PolicyActivationEvent | None: ...

    async def record_request_activation(
        self,
        *,
        request_id: str,
        revision_id: str,
        activation: PolicyActivationEvent,
    ) -> None: ...

    async def activate_revision(
        self,
        *,
        policy_kind: PolicyKind,
        revision_id: str,
        policy_digest: str,
        author_principal: str,
        activated_at: datetime,
        validation_digest: str,
        expected_parent_revision_id: str | None,
    ) -> PolicyActivationEvent: ...


class RegoPolicyCompiler(Protocol):
    """Compile or evaluate Rego under a bounded, fail-closed profile."""

    async def compile(self, rego: str) -> None: ...

    async def test(self, rego: str, tests: tuple[dict[str, object], ...]) -> None: ...


@dataclass(frozen=True, slots=True)
class OpaRegoPolicyCompiler:
    """Compile policy-admin Rego through the OPA binary with a local timeout."""

    opa_binary: str = "opa"
    timeout_seconds: float = 5.0
    capabilities_file: Path | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.timeout_seconds > 30:
            raise ValueError("OPA policy compiler timeout MUST be in (0, 30]")
        if shutil.which(self.opa_binary) is None:
            raise PolicyRevisionRejectedError("opa_binary_unavailable")
        capabilities = self.capabilities_file or repo_asset_root() / _CAPABILITIES_RELATIVE
        object.__setattr__(self, "capabilities_file", capabilities)
        if not capabilities.is_file():
            raise PolicyRevisionRejectedError("opa_capabilities_unavailable")

    async def compile(self, rego: str) -> None:
        with tempfile.TemporaryDirectory(prefix="fdai-policy-admin-") as directory:
            policy_path = Path(directory) / "policy.rego"
            policy_path.write_text(rego, encoding="utf-8")
            returncode = await _run_opa(
                self.timeout_seconds,
                self.opa_binary,
                "check",
                "--strict",
                "--capabilities",
                str(self.capabilities_file),
                str(policy_path),
            )
        if returncode != 0:
            raise PolicyRevisionRejectedError("rego_compile_failed")

    async def test(self, rego: str, tests: tuple[dict[str, object], ...]) -> None:
        if not tests:
            raise PolicyRevisionRejectedError("policy_tests_missing")
        with tempfile.TemporaryDirectory(prefix="fdai-policy-admin-test-") as directory:
            root = Path(directory)
            (root / "policy.rego").write_text(rego, encoding="utf-8")
            for index, item in enumerate(tests):
                test_rego = item.get("rego")
                if not isinstance(test_rego, str) or not test_rego.strip():
                    raise PolicyRevisionRejectedError("policy_test_malformed")
                (root / f"policy_test_{index}.rego").write_text(test_rego, encoding="utf-8")
            returncode = await _run_opa(
                self.timeout_seconds,
                self.opa_binary,
                "test",
                "--capabilities",
                str(self.capabilities_file),
                str(root),
            )
        if returncode != 0:
            raise PolicyRevisionRejectedError("policy_test_failed")


@dataclass(frozen=True, slots=True)
class StateStorePolicyRevisionStore:
    """Persist Mimir policy revisions through the existing StateStore seam."""

    store: StateStore

    async def append_revision(self, record: PolicyRevisionRecord) -> bool:
        key = _revision_key(record.policy_kind, record.revision_id)
        return await self.store.write_state_with_audit_if_absent(
            key,
            record.model_dump(mode="json"),
            {
                "event_type": "policy_revision_recorded",
                "actor": "Mimir",
                "policy_kind": record.policy_kind.value,
                "revision_id": record.revision_id,
                "policy_digest": record.content_digest,
                "author_principal": record.author_principal,
                "validation_digest": record.validation.validation_digest,
            },
        )

    async def revision(
        self,
        *,
        policy_kind: PolicyKind,
        revision_id: str,
    ) -> PolicyRevisionRecord | None:
        stored = await self.store.read_state(_revision_key(policy_kind, revision_id))
        if stored is None:
            return None
        return PolicyRevisionRecord.model_validate(stored)

    async def active_revision_id(self, policy_kind: PolicyKind) -> str | None:
        stored = await self.store.read_state(_activation_key(policy_kind))
        revision_id = stored.get("revision_id") if stored is not None else None
        return revision_id if isinstance(revision_id, str) and revision_id else None

    async def active_activation(self, policy_kind: PolicyKind) -> PolicyActivationEvent | None:
        stored = await self.store.read_state(_activation_key(policy_kind))
        if stored is None:
            return None
        return PolicyActivationEvent.model_validate(
            {key: value for key, value in stored.items() if key != "revision"}
        )

    async def active_approval_profile(self) -> ApprovalProfileRevision | None:
        active = await self.active_revision_id(PolicyKind.APPROVAL)
        if active is None:
            return None
        revision = await self.revision(policy_kind=PolicyKind.APPROVAL, revision_id=active)
        if revision is None or not isinstance(revision.content, ApprovalPolicyContent):
            return None
        return _approval_profile_from_document(revision.content.document)

    async def request_revision_id(self, request_id: str) -> str | None:
        stored = await self.store.read_state(_request_key(request_id))
        revision_id = stored.get("revision_id") if stored is not None else None
        return revision_id if isinstance(revision_id, str) and revision_id else None

    async def record_request_revision(self, *, request_id: str, revision_id: str) -> bool:
        return await self.store.write_state_if_absent(
            _request_key(request_id),
            {
                "kind": "policy_revision_request",
                "request_id": request_id,
                "revision_id": revision_id,
                "state": "pending",
            },
        )

    async def request_activation(self, request_id: str) -> PolicyActivationEvent | None:
        stored = await self.store.read_state(_request_key(request_id))
        activation = stored.get("activation") if stored is not None else None
        if not isinstance(activation, Mapping):
            return None
        return PolicyActivationEvent.model_validate(activation)

    async def record_request_activation(
        self,
        *,
        request_id: str,
        revision_id: str,
        activation: PolicyActivationEvent,
    ) -> None:
        await self.store.write_state(
            _request_key(request_id),
            {
                "kind": "policy_revision_request",
                "request_id": request_id,
                "revision_id": revision_id,
                "state": "activated",
                "activation": activation.model_dump(mode="json"),
            },
        )

    async def activate_revision(
        self,
        *,
        policy_kind: PolicyKind,
        revision_id: str,
        policy_digest: str,
        author_principal: str,
        activated_at: datetime,
        validation_digest: str,
        expected_parent_revision_id: str | None,
    ) -> PolicyActivationEvent:
        key = _activation_key(policy_kind)
        existing = await self.store.read_state(key)
        revision = int(existing.get("revision", 0)) if existing is not None else 0
        active_revision_id = existing.get("revision_id") if existing is not None else None
        if active_revision_id != expected_parent_revision_id:
            raise PolicyRevisionRejectedError("stale_parent_revision")
        event = PolicyActivationEvent(
            kind="policy_activation",
            policy_id=f"{policy_kind.value}:{revision_id}",
            policy_kind=policy_kind,
            revision_id=revision_id,
            policy_digest=policy_digest,
            activated_at=activated_at,
            author_principal=author_principal,
            validation_digest=validation_digest,
            correlation_id=f"policy-activation:{policy_kind.value}:{revision_id}",
            idempotency_key=stable_idempotency_key(
                "policy-activation",
                policy_kind.value,
                revision_id,
                policy_digest,
            ),
        )
        updated = {
            **event.model_dump(mode="json"),
            "revision": revision + 1,
        }
        audit_entry = {
            "event_type": "policy_activation_recorded",
            "actor": "Mimir",
            "policy_kind": policy_kind.value,
            "revision_id": revision_id,
            "policy_digest": policy_digest,
            "author_principal": author_principal,
            "validation_digest": validation_digest,
        }
        if existing is None:
            if not await self.store.write_state_with_audit_if_absent(key, updated, audit_entry):
                raise PolicyRevisionRejectedError("policy_activation_conflict")
        elif not await self.store.compare_and_set_state_with_audit(
            key,
            updated,
            expected_revision=revision,
            audit_entry=audit_entry,
        ):
            raise PolicyRevisionRejectedError("policy_activation_conflict")
        return event


@dataclass(frozen=True, slots=True)
class MimirPolicyAdministration:
    """Validate a typed request and activate it as Mimir's Policy object."""

    store: PolicyRevisionStore
    signer: PolicyRevisionSigner
    rego_compiler: RegoPolicyCompiler
    operator_request_receipt_gate: OperatorRequestReceiptGate
    operator_producer_service_identity: str
    release_maximums: ReleaseCapabilityMaximums | None = None
    governance_quorum: int = 2
    clock: object | None = None

    def __post_init__(self) -> None:
        if self.operator_request_receipt_gate is None:
            raise ValueError("policy administration requires an OperatorRequestReceiptGate")

    async def handle_request(self, payload: Mapping[str, object]) -> PolicyActivationEvent:
        try:
            request = PolicyRevisionRequestEvent.model_validate(dict(payload))
        except ValidationError as exc:
            raise PolicyRevisionRejectedError("malformed_schema") from exc
        await self._verify_request_authority(request)
        replayed_revision_id = await self.store.request_revision_id(request.request_id)
        if replayed_revision_id is not None:
            activation = await self.store.request_activation(request.request_id)
            if activation is not None:
                return activation
            existing = await self.store.revision(
                policy_kind=request.policy_kind,
                revision_id=replayed_revision_id,
            )
            if existing is None:
                raise PolicyRevisionRejectedError("request_replay_missing_revision")
            if policy_content_digest(request.content) != existing.content_digest:
                raise PolicyRevisionRejectedError("request_replay_content_mismatch")
            active_activation = await self.store.active_activation(request.policy_kind)
            if (
                active_activation is not None
                and active_activation.revision_id == existing.revision_id
            ):
                await self.store.record_request_activation(
                    request_id=request.request_id,
                    revision_id=existing.revision_id,
                    activation=active_activation,
                )
                return active_activation
            await self._validate_current_authority_for_content(
                request=request,
                content=existing.content,
            )
            activation = await self.store.activate_revision(
                policy_kind=existing.policy_kind,
                revision_id=existing.revision_id,
                policy_digest=existing.content_digest,
                author_principal=existing.author_principal,
                activated_at=_now(self.clock),
                validation_digest=existing.validation.validation_digest,
                expected_parent_revision_id=existing.parent_revision_id,
            )
            await self.store.record_request_activation(
                request_id=request.request_id,
                revision_id=existing.revision_id,
                activation=activation,
            )
            return activation
        active_parent = await self.store.active_revision_id(request.policy_kind)
        if request.parent_revision_id != active_parent:
            raise PolicyRevisionRejectedError("stale_parent_revision")
        created_at = _now(self.clock)
        content = request.content
        _validate_content_size(content.model_dump(mode="json"))
        await self._validate_current_authority_for_content(
            request=request,
            content=content,
        )
        if isinstance(content, AdmissionPolicyContent):
            if not content.policy_tests:
                raise PolicyRevisionRejectedError("policy_tests_missing")
            await self.rego_compiler.compile(content.rego)
            await self.rego_compiler.test(content.rego, content.policy_tests)
        self._validate_release_maximums(content.action_type_modes)
        content_digest = policy_content_digest(content)
        validation = PolicyValidationResult(
            rego_valid=isinstance(content, AdmissionPolicyContent),
            release_maximums_valid=True,
            policy_tests_valid=(
                not isinstance(content, AdmissionPolicyContent) or bool(content.policy_tests)
            ),
            validation_digest="sha256:" + "0" * 64,
            details=(
                "schema",
                "restricted-rego"
                if isinstance(content, AdmissionPolicyContent)
                else "approval-profile",
                "policy-tests"
                if isinstance(content, AdmissionPolicyContent) and content.policy_tests
                else "policy-tests-not-present",
                "release-maximums",
            ),
        )
        validation_payload = validation.model_dump(mode="json", exclude={"validation_digest"}) | {
            "request_digest": request.request_digest,
            "content_digest": content_digest,
        }
        validation = PolicyValidationResult.model_validate(
            {
                **validation.model_dump(mode="json"),
                "validation_digest": policy_validation_digest(validation_payload),
            }
        )
        revision_id = _revision_id(request.policy_kind, content_digest, request.parent_revision_id)
        signature_ref = await self.signer.sign_policy_revision(
            policy_digest=content_digest,
            revision_id=revision_id,
        )
        record = PolicyRevisionRecord(
            revision_id=revision_id,
            policy_kind=request.policy_kind,
            content_digest=content_digest,
            content=content,
            signature_ref=signature_ref,
            parent_revision_id=request.parent_revision_id,
            author_principal=request.author_principal,
            reason=request.reason,
            created_at=created_at,
            activated_at=None,
            validation=validation,
            diff_digest=_diff_digest(
                parent_revision_id=request.parent_revision_id,
                content_digest=content_digest,
            ),
        )
        if not await self.store.append_revision(record):
            existing = await self.store.revision(
                policy_kind=record.policy_kind,
                revision_id=record.revision_id,
            )
            if existing is None or existing.content_digest != record.content_digest:
                raise PolicyRevisionRejectedError("duplicate_revision")
        if not await self.store.record_request_revision(
            request_id=request.request_id,
            revision_id=record.revision_id,
        ):
            raise PolicyRevisionRejectedError("request_id_conflict")
        activation = await self.store.activate_revision(
            policy_kind=request.policy_kind,
            revision_id=record.revision_id,
            policy_digest=record.content_digest,
            author_principal=record.author_principal,
            activated_at=created_at,
            validation_digest=record.validation.validation_digest,
            expected_parent_revision_id=request.parent_revision_id,
        )
        await self.store.record_request_activation(
            request_id=request.request_id,
            revision_id=record.revision_id,
            activation=activation,
        )
        return activation

    def _validate_release_maximums(self, requested: Mapping[str, PolicyMode]) -> None:
        for action_type, mode in requested.items():
            maximum = (
                self.release_maximums.maximum_mode_for_action_type(action_type)
                if self.release_maximums is not None
                else None
            )
            if maximum is None:
                if mode is not PolicyMode.SHADOW:
                    raise PolicyRevisionRejectedError("release_maximum_unavailable")
                continue
            if _mode_rank(mode) > _mode_rank(maximum):
                raise PolicyRevisionRejectedError("release_maximum_exceeded")

    async def _validate_current_authority_for_content(
        self,
        *,
        request: PolicyRevisionRequestEvent,
        content: AdmissionPolicyContent | ApprovalPolicyContent,
    ) -> ApprovalProfileRevision | None:
        active_profile = await self.store.active_approval_profile()
        if active_profile is not None and active_profile.is_single_operator:
            self._validate_profile_author(active_profile, request.author_principal)
        if request.policy_kind is PolicyKind.ADMISSION and (
            active_profile is None or not active_profile.is_single_operator
        ):
            raise PolicyRevisionRejectedError("admission_policy_requires_single_operator")
        if isinstance(content, ApprovalPolicyContent):
            self._validate_approval_policy(content, active_profile, request.author_principal)
        return active_profile

    async def _verify_request_authority(self, request: PolicyRevisionRequestEvent) -> None:
        receipt = request.operator_request_receipt
        if receipt is None:
            raise PolicyRevisionRejectedError("operator_request_receipt_missing")
        if receipt.schema_version != "1.2.0":
            raise PolicyRevisionRejectedError("operator_request_receipt_version")
        if receipt.producer_service_identity != self.operator_producer_service_identity:
            raise PolicyRevisionRejectedError("operator_request_receipt_producer")
        raw = PolicyRevisionRequestEvent.operator_receipt_event(
            body=request,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            idempotency_key=request.idempotency_key,
            author_principal=receipt.initiator_principal,
            authenticated_at=receipt.authenticated_at or _now(self.clock),
            app_roles=frozenset(receipt.principal_roles),
        )
        raw["operator_request_receipt"] = receipt.model_dump(mode="json")
        try:
            await self.operator_request_receipt_gate.verify_or_committed(raw)
        except ValueError as exc:
            raise PolicyRevisionRejectedError("operator_request_receipt_invalid") from exc
        if "policy-admin" not in receipt.principal_roles:
            raise PolicyRevisionRejectedError("policy_admin_role_missing")
        if receipt.initiator_principal != request.author_principal:
            raise PolicyRevisionRejectedError("author_principal_mismatch")
        if receipt.authenticated_at is None:
            raise PolicyRevisionRejectedError("auth_time_missing")
        if receipt.max_auth_age_seconds is None:
            raise PolicyRevisionRejectedError("auth_time_bound_missing")
        if _now(self.clock) > receipt.authenticated_at + timedelta(
            seconds=receipt.max_auth_age_seconds
        ):
            raise PolicyRevisionRejectedError("auth_time_stale")

    def _validate_approval_policy(
        self,
        content: ApprovalPolicyContent,
        active_profile: ApprovalProfileRevision | None,
        author_principal: str,
    ) -> None:
        try:
            proposed = _approval_profile_from_document(content.document)
        except (TypeError, ValueError) as exc:
            raise PolicyRevisionRejectedError("approval_policy_invalid") from exc
        required_quorum = profile_transition_quorum(
            active_profile,
            proposed,
            governance_quorum=self.governance_quorum,
        )
        if required_quorum > 1 and (
            active_profile is None or not active_profile.is_single_operator
        ):
            raise PolicyRevisionRejectedError("approval_policy_requires_quorum")
        if active_profile is not None and active_profile.is_single_operator:
            self._validate_profile_author(active_profile, author_principal)

    def _validate_profile_author(
        self,
        active_profile: ApprovalProfileRevision,
        author_principal: str,
    ) -> None:
        decision = evaluate_profile_approval(
            active_profile,
            approver=author_principal,
            requester=author_principal,
            original_quorum=1,
        )
        if not decision.allowed:
            raise PolicyRevisionRejectedError("approval_policy_author_not_operator")


def _validate_content_size(content: Mapping[str, object]) -> None:
    size = len(json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if size > _MAX_CONTENT_BYTES:
        raise PolicyRevisionRejectedError("policy_content_too_large")


def _approval_profile_from_document(document: Mapping[str, object]) -> ApprovalProfileRevision:
    normalized = dict(document)
    effective_from = normalized.get("effective_from")
    if isinstance(effective_from, str):
        parsed_effective_from = datetime.fromisoformat(effective_from.replace("Z", "+00:00"))
    elif isinstance(effective_from, datetime):
        parsed_effective_from = effective_from
    else:
        raise ValueError("approval profile effective_from is invalid")
    approval_profile = normalized.get("approval_profile")
    if isinstance(approval_profile, str):
        parsed_profile = ApprovalProfileKind(approval_profile)
    elif isinstance(approval_profile, ApprovalProfileKind):
        parsed_profile = approval_profile
    else:
        raise ValueError("approval profile kind is invalid")
    return ApprovalProfileRevision(
        revision_id=str(normalized.get("revision_id") or ""),
        approval_profile=parsed_profile,
        executor_principal=str(normalized.get("executor_principal") or ""),
        policy_digest=str(normalized.get("policy_digest") or ""),
        effective_from=parsed_effective_from,
        operator_principal=(
            str(normalized["operator_principal"])
            if normalized.get("operator_principal") is not None
            else None
        ),
    )


async def _run_opa(timeout_seconds: float, *argv: str) -> int:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise PolicyRevisionRejectedError("opa_timeout") from exc
    return int(proc.returncode if proc.returncode is not None else 1)


def _mode_rank(mode: PolicyMode) -> int:
    return 0 if mode is PolicyMode.SHADOW else 1


def _revision_key(policy_kind: PolicyKind, revision_id: str) -> str:
    return f"policy_revision:{policy_kind.value}:{revision_id}"


def _activation_key(policy_kind: PolicyKind) -> str:
    return f"policy_activation:{policy_kind.value}"


def _request_key(request_id: str) -> str:
    return f"policy_request:{request_id}"


def _revision_id(
    policy_kind: PolicyKind,
    content_digest: str,
    parent_revision_id: str | None,
) -> str:
    seed = f"{policy_kind.value}\0{content_digest}\0{parent_revision_id or ''}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{policy_kind.value}:{digest[:32]}"


def _diff_digest(*, parent_revision_id: str | None, content_digest: str) -> str:
    raw = json.dumps(
        {"parent_revision_id": parent_revision_id, "content_digest": content_digest},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now(clock: object | None) -> datetime:
    candidate = clock() if callable(clock) else datetime.now(UTC)
    if candidate.tzinfo is None or candidate.utcoffset() is None:
        raise ValueError("policy administration clock MUST return timezone-aware datetimes")
    return candidate.astimezone(UTC)


__all__ = [
    "MimirPolicyAdministration",
    "OpaRegoPolicyCompiler",
    "POLICY_OBJECT_TOPIC",
    "PolicyRevisionRejectedError",
    "PolicyRevisionSigner",
    "PolicyRevisionStore",
    "RegoPolicyCompiler",
    "StateStorePolicyRevisionStore",
]

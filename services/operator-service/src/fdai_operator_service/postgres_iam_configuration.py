"""PostgreSQL persistence for IAM-backed runtime and model configuration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, cast

from fdai_service_contracts import DocumentOcrPolicy, ModelBindingPolicy
from pydantic import ValidationError

from fdai_operator_service.families.iam.contracts import (
    ConfigurationReviewCommand,
    DocumentOcrPlanCommand,
    DocumentOcrPolicyCommand,
    JsonMapping,
    ModelBindingDraftCommand,
    ModelBindingRequestCommand,
    ModelCatalogReader,
    ModelPreferenceCommand,
    RuntimeSettingsCommand,
    TeamsA1OnboardingPlanCommand,
    WebSearchSettingsCommand,
)
from fdai_operator_service.families.iam.errors import (
    IamConflictError,
    IamFamilyError,
    IamNotFoundError,
    IamUnavailableError,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProposalConflict,
    StoredProposal,
)
from fdai_operator_service.postgres_iam_configuration_projection import (
    binding_policy_projection,
    binding_receipt,
    document_ocr_projection,
    document_ocr_receipt,
    runtime_settings_projection,
    runtime_settings_state,
    state_revision,
    stored_binding_policy,
    stored_document_ocr_policy,
    teams_a1_onboarding_projection,
)

_MODEL_BINDING_POLICY_KEY = "operator-model-binding-policy:current"
_DOCUMENT_OCR_POLICY_KEY = "operator-document-ocr-policy:current"
_DOCUMENT_OCR_PLAN_KEY = "operator-document-ocr-plan:current"
_RUNTIME_SETTINGS_POLICY_KEY = "runtime-settings:policy"
_TEAMS_A1_ONBOARDING_PLAN_KEY = "operator-teams-a1-onboarding-plan:current"


class PostgresIamConfigurationMixin:
    """Provide inert configuration projections and proposal-only persistence."""

    store: PostgresFamilyStore
    model_catalog: ModelCatalogReader | None

    async def _projection(self, operation: str) -> dict[str, object]:
        raise NotImplementedError

    async def _state(self, key: str) -> dict[str, object] | None:
        raise NotImplementedError

    async def _proposal(
        self,
        operation: str,
        command: object,
        idempotency_key: str,
    ) -> StoredProposal:
        raise NotImplementedError

    async def projection(
        self,
        principal_id: str | None = None,
        *,
        can_manage_web_search: bool = False,
        can_manage_model_bindings: bool = False,
        refresh_model_catalog: bool = False,
        can_manage: bool = False,
    ) -> JsonMapping:
        """Read model or runtime settings without mutating their policy source."""
        operation = "model-settings" if principal_id is not None else "runtime-settings"
        payload = await self._projection(operation)
        if principal_id is not None:
            if self.model_catalog is not None:
                payload = {
                    **payload,
                    "model_catalog": await self.model_catalog.read(refresh=refresh_model_catalog),
                }
            web_search = payload.get("web_search")
            if not isinstance(web_search, Mapping):
                raise IamUnavailableError("model settings projection has no web_search object")
            binding_policy = await self._state(_MODEL_BINDING_POLICY_KEY)
            document_ocr_policy = await self._state(_DOCUMENT_OCR_POLICY_KEY)
            document_ocr_plan = await self._state(_DOCUMENT_OCR_PLAN_KEY)
            environment = str(payload.get("environment") or "unspecified")
            if binding_policy is not None and binding_policy.get("environment") != environment:
                raise IamUnavailableError(
                    "model binding policy environment does not match the Settings projection"
                )
            return {
                **payload,
                "web_search": {**web_search, "can_manage": can_manage_web_search},
                "binding_policy": (
                    binding_policy_projection(
                        binding_policy,
                        can_manage=can_manage_model_bindings,
                    )
                    if binding_policy is not None
                    else {
                        "environment": environment,
                        "revision": 0,
                        "state": "not-configured",
                        "policy": None,
                        "policy_digest": None,
                        "can_manage": can_manage_model_bindings,
                        "execution_authority": False,
                    }
                ),
                "document_ocr": document_ocr_projection(
                    payload.get("document_ocr"),
                    document_ocr_policy,
                    document_ocr_plan,
                    can_manage=can_manage_model_bindings,
                ),
            }
        runtime_policy = await self._state(_RUNTIME_SETTINGS_POLICY_KEY)
        teams_a1_plan = await self._state(_TEAMS_A1_ONBOARDING_PLAN_KEY)
        runtime_projection = runtime_settings_projection(payload, runtime_policy)
        return {
            **runtime_projection,
            "can_manage": can_manage,
            "teams_a1_onboarding": teams_a1_onboarding_projection(
                runtime_projection,
                teams_a1_plan,
                can_manage=can_manage,
            ),
        }

    async def set_preference(self, command: ModelPreferenceCommand) -> None:
        await self._proposal("model-settings.preference", command, _idempotency_key(command))

    async def set_web_search_settings(self, command: WebSearchSettingsCommand) -> None:
        await self._proposal("model-settings.web-search", command, _idempotency_key(command))

    async def save_binding_policy(self, command: ModelBindingDraftCommand) -> JsonMapping:
        try:
            policy = ModelBindingPolicy.model_validate(command.policy)
        except ValidationError as exc:
            raise IamConflictError("model binding policy is invalid") from exc
        if policy.digest() != command.policy_digest:
            raise IamConflictError("model binding policy digest does not match its content")
        if policy.revision != command.expected_revision + 1:
            raise IamConflictError("model binding policy revision conflict")
        projection = await self._projection("model-settings")
        deployment_environment = projection.get("environment")
        if not isinstance(deployment_environment, str) or not deployment_environment:
            raise IamUnavailableError("model Settings projection has no deployment environment")
        if policy.environment != deployment_environment:
            raise IamConflictError(
                "model binding policy environment does not match this deployment"
            )
        state: dict[str, object] = {
            "environment": policy.environment,
            "revision": policy.revision,
            "state": "draft",
            "policy": policy.model_dump(mode="json", exclude_none=True),
            "policy_digest": policy.digest(),
            "execution_authority": False,
            "activation_boundary": "protected-plan-only",
        }
        try:
            stored = await self.store.append_revisioned_proposal(
                family="iam",
                operation="model-settings.binding-policy.draft",
                principal_id=command.actor_id,
                idempotency_key=command.idempotency_key,
                payload=_command_payload(command),
                state_key=_MODEL_BINDING_POLICY_KEY,
                state_value=state,
                expected_revision=command.expected_revision,
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc
        return binding_receipt(stored, state="draft", command=command)

    async def request_binding_assessment(self, command: ModelBindingRequestCommand) -> JsonMapping:
        return await self._request_binding_operation(command, operation="assessment")

    async def request_binding_plan(self, command: ModelBindingRequestCommand) -> JsonMapping:
        return await self._request_binding_operation(command, operation="plan")

    async def save_document_ocr_policy(self, command: DocumentOcrPolicyCommand) -> JsonMapping:
        try:
            policy = DocumentOcrPolicy.model_validate(command.policy)
        except ValidationError as exc:
            raise IamConflictError("document OCR policy is invalid") from exc
        if policy.digest() != command.policy_digest:
            raise IamConflictError("document OCR policy digest does not match its content")
        if policy.revision != command.expected_revision + 1:
            raise IamConflictError("document OCR policy revision conflict")
        projection = await self._projection("model-settings")
        if policy.environment != projection.get("environment"):
            raise IamConflictError("document OCR policy environment does not match this deployment")
        state: dict[str, object] = {
            "environment": policy.environment,
            "revision": policy.revision,
            "state": "plan-required",
            "policy": policy.model_dump(mode="json"),
            "policy_digest": policy.digest(),
            "execution_authority": False,
            "activation_boundary": "protected-plan-only",
        }
        try:
            stored = await self.store.append_revisioned_proposal(
                family="iam",
                operation="model-settings.document-ocr.policy",
                principal_id=command.actor_id,
                idempotency_key=command.idempotency_key,
                payload=_command_payload(command),
                state_key=_DOCUMENT_OCR_POLICY_KEY,
                state_value=state,
                expected_revision=command.expected_revision,
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc
        return document_ocr_receipt(stored, state="plan-required", policy=policy)

    async def request_document_ocr_plan(self, command: DocumentOcrPlanCommand) -> JsonMapping:
        state = await self._state(_DOCUMENT_OCR_POLICY_KEY)
        policy = stored_document_ocr_policy(state)
        if (
            policy.environment != command.environment
            or policy.revision != command.policy_revision
            or policy.digest() != command.policy_digest
        ):
            raise IamConflictError("document OCR plan does not match the current policy")
        current_plan = await self._state(_DOCUMENT_OCR_PLAN_KEY)
        current_plan_revision = state_revision(current_plan, label="document OCR plan")
        next_state: dict[str, object] = {
            "revision": current_plan_revision + 1,
            "state": "plan-requested",
            "environment": policy.environment,
            "policy_revision": policy.revision,
            "policy_digest": policy.digest(),
            "execution_authority": False,
            "activation_boundary": "protected-plan-only",
        }
        try:
            stored = await self.store.append_revisioned_proposal(
                family="iam",
                operation="model-settings.document-ocr.plan",
                principal_id=command.actor_id,
                idempotency_key=command.idempotency_key,
                payload=_command_payload(command),
                state_key=_DOCUMENT_OCR_PLAN_KEY,
                state_value=next_state,
                expected_revision=current_plan_revision,
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc
        return document_ocr_receipt(stored, state="plan-requested", policy=policy)

    async def _request_binding_operation(
        self,
        command: ModelBindingRequestCommand,
        *,
        operation: str,
    ) -> JsonMapping:
        state = await self._state(_MODEL_BINDING_POLICY_KEY)
        if state is None:
            raise IamNotFoundError("model binding policy draft does not exist")
        if (
            state.get("environment") != command.environment
            or state.get("revision") != command.policy_revision
            or state.get("policy_digest") != command.policy_digest
        ):
            raise IamConflictError("model binding policy request does not match the current draft")
        policy = stored_binding_policy(state)
        if operation == "plan" and policy.expected_active_digest is None:
            raise IamConflictError(
                "model binding plan requires an expected active resolved-models digest"
            )
        if operation == "plan":
            projection = await self._projection("model-settings")
            resolved_metadata = projection.get("resolved_metadata")
            active_digest = (
                resolved_metadata.get("digest") if isinstance(resolved_metadata, Mapping) else None
            )
            if not isinstance(active_digest, str):
                raise IamUnavailableError(
                    "model Settings projection has no active resolved-models digest"
                )
            if policy.expected_active_digest != active_digest:
                raise IamConflictError(
                    "model binding plan does not match the active resolved-models digest"
                )
        stored = await self._proposal(
            f"model-settings.binding-policy.{operation}",
            command,
            command.idempotency_key,
        )
        return binding_receipt(stored, state=f"{operation}-requested", command=command)

    async def update(self, command: RuntimeSettingsCommand) -> None:
        projection = await self._projection("runtime-settings")
        current = await self._state(_RUNTIME_SETTINGS_POLICY_KEY)
        try:
            state = runtime_settings_state(projection, current, command)
            await self.store.append_revisioned_proposal(
                family="iam",
                operation="runtime-settings.update",
                principal_id=command.actor_id,
                idempotency_key=_idempotency_key(command),
                payload=_command_payload(command),
                state_key=_RUNTIME_SETTINGS_POLICY_KEY,
                state_value=state,
                expected_revision=command.expected_revision,
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc
        except ValueError as exc:
            raise IamFamilyError(str(exc)) from exc

    async def request_teams_a1_plan(self, command: TeamsA1OnboardingPlanCommand) -> JsonMapping:
        projection = await self._projection("runtime-settings")
        runtime = projection.get("runtime")
        environment = runtime.get("environment") if isinstance(runtime, Mapping) else None
        if command.environment not in {"dev", "staging", "prod"}:
            raise IamFamilyError("Teams A1 onboarding environment is invalid")
        if environment != command.environment:
            raise IamConflictError("Teams A1 onboarding environment does not match this deployment")
        current = await self._state(_TEAMS_A1_ONBOARDING_PLAN_KEY)
        revision = state_revision(current, label="Teams A1 onboarding plan")
        state: dict[str, object] = {
            "revision": revision + 1,
            "state": "plan-requested",
            "environment": command.environment,
            "execution_authority": False,
            "activation_boundary": "protected-plan-only",
        }
        try:
            stored = await self.store.append_revisioned_proposal(
                family="iam",
                operation="runtime-settings.teams-a1.plan",
                principal_id=command.actor_id,
                idempotency_key=command.idempotency_key,
                payload=_command_payload(command),
                state_key=_TEAMS_A1_ONBOARDING_PLAN_KEY,
                state_value=state,
                expected_revision=revision,
            )
        except PostgresProposalConflict as exc:
            raise IamConflictError(str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise IamUnavailableError(str(exc)) from exc
        return {
            "proposal_id": stored.proposal_id,
            "accepted_at": stored.accepted_at,
            "duplicate": stored.duplicate,
            **state,
        }

    async def run(self, command: ConfigurationReviewCommand) -> JsonMapping:
        stored = await self._proposal("configuration-review.run", command, command.run_id)
        return {"campaign_id": stored.proposal_id, "state": "pending"}

    async def resume(self, *, principal_id: str) -> JsonMapping:
        stored = await self._proposal(
            "configuration-review.resume",
            {"principal_id": principal_id},
            f"resume:{principal_id}",
        )
        return {"campaign_id": stored.proposal_id, "state": "pending"}


def _idempotency_key(command: object) -> str:
    for name in ("idempotency_key", "request_id", "run_id"):
        value = getattr(command, name, None)
        if isinstance(value, str) and value:
            return value
    payload = _command_payload(command)
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )


def _command_payload(command: object) -> dict[str, object]:
    normalized = json.loads(json.dumps(asdict(cast(Any, command)), default=_json_default))
    if not isinstance(normalized, dict):
        raise ValueError("IAM adapter payload MUST serialize to a JSON object")
    return cast(dict[str, object], normalized)


def _json_default(value: object) -> object:
    if isinstance(value, set | frozenset):
        return sorted(str(item) for item in value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


__all__ = ["PostgresIamConfigurationMixin"]

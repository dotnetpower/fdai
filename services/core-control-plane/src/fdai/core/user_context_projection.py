"""Project private user-context metadata into the typed ontology graph."""

from __future__ import annotations

import hashlib

from fdai.shared.providers.briefing import (
    BriefingRun,
    BriefingSubscription,
    ConversationPolicyRecord,
)
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.user_context import (
    ConversationRecord,
    ConversationTurnRecord,
    UserMemoryFact,
    UserPreferenceRecord,
)
from fdai.shared.providers.workflow_definition import (
    WorkflowBindingRecord,
    WorkflowDefinitionRecord,
)


class UserContextOntologyProjector:
    """Write metadata-only projections; private bodies stay in source stores."""

    def __init__(self, *, store: OntologyInstanceStore) -> None:
        self._store = store

    async def project_conversation(self, record: ConversationRecord) -> str:
        principal = await self._principal(record.principal_id)
        object_id = _id("conversation", record.principal_id, record.conversation_id)
        await self._store.upsert_object(
            OntologyObjectRecord(
                id=object_id,
                object_type="Conversation",
                properties={
                    "id": object_id,
                    "user_id": principal,
                    "started_at": record.started_at.isoformat(),
                    "last_active": record.last_active.isoformat(),
                },
            )
        )
        await self._link("conversation_belongs_to", object_id, principal)
        return object_id

    async def project_turn_exchange(
        self,
        *,
        conversation: ConversationRecord,
        operator: ConversationTurnRecord,
        assistant: ConversationTurnRecord,
        primary_agent: str = "Bragi",
    ) -> str:
        conversation_id = await self.project_conversation(conversation)
        object_id = _id("turn", operator.principal_id, operator.turn_id)
        await self._store.upsert_object(
            OntologyObjectRecord(
                id=object_id,
                object_type="Turn",
                properties={
                    "id": object_id,
                    "session_id": conversation_id,
                    "turn_index": operator.turn_index // 2,
                    "question_ref": _turn_ref(operator),
                    "question_sha256": _content_hash(operator.content),
                    "primary_agent": primary_agent,
                    "answer_ref": _turn_ref(assistant),
                    "answer_sha256": _content_hash(assistant.content),
                    "contributors": [],
                    "trace_ref": assistant.metadata.get("correlation_id", ""),
                },
            )
        )
        await self._link("has_turn", conversation_id, object_id)
        return object_id

    async def project_preference(self, record: UserPreferenceRecord) -> str:
        principal = await self._principal(record.principal_id)
        object_id = _id("preference", record.principal_id)
        properties: dict[str, object] = {
            "id": object_id,
            "locale": record.locale,
            "verbosity": record.verbosity,
            "answer_detail": record.answer_detail,
            "answer_format": record.answer_format,
            "answer_preferences_enabled": record.answer_preferences_enabled,
            "answer_intent_detail": dict(record.answer_intent_detail),
            "answer_intent_format": dict(record.answer_intent_format),
            "share_with_learner": record.share_with_learner,
        }
        if record.updated_at is not None:
            properties["updated_at"] = record.updated_at.isoformat()
        await self._store.upsert_object(
            OntologyObjectRecord(id=object_id, object_type="UserPreference", properties=properties)
        )
        await self._link("preference_of", object_id, principal)
        return object_id

    async def project_memory(self, record: UserMemoryFact) -> str:
        principal = await self._principal(record.principal_id)
        object_id = _id("memory", record.principal_id, record.memory_id)
        properties: dict[str, object] = {
            "id": object_id,
            "principal_ref": principal,
            "category": record.category.value,
            "source_turn_id": _id("turn", record.principal_id, record.source_turn_id),
            "consented_at": record.consented_at,
            "created_at": record.created_at,
        }
        if record.expires_at is not None:
            properties["expires_at"] = record.expires_at
        if record.superseded_by is not None:
            properties["superseded_by"] = _id("memory", record.principal_id, record.superseded_by)
        await self._store.upsert_object(
            OntologyObjectRecord(id=object_id, object_type="UserMemoryFact", properties=properties)
        )
        await self._link("memory_of", object_id, principal)
        source_turn = properties["source_turn_id"]
        if isinstance(source_turn, str) and await self._store.get_object(source_turn):
            await self._link("derived_from_turn", object_id, source_turn)
        return object_id

    async def project_policy(self, record: ConversationPolicyRecord) -> str:
        principal = await self._principal(record.principal_id)
        object_id = _id("policy", record.principal_id, record.policy_id)
        policy_shape: dict[str, object] = dict(record.response_defaults)
        if record.briefing_spec is not None:
            policy_shape = {
                "kind": record.briefing_spec.kind.value,
                "lookback_seconds": record.briefing_spec.lookback_seconds,
                "minimum_severity": record.briefing_spec.minimum_severity,
                "max_items": record.briefing_spec.max_items,
            }
        await self._store.upsert_object(
            OntologyObjectRecord(
                id=object_id,
                object_type="ConversationPolicy",
                properties={
                    "id": object_id,
                    "principal_ref": principal,
                    "kind": record.kind.value,
                    "enabled": record.enabled,
                    "revision": record.revision,
                    "confirmed_at": record.confirmed_at,
                    "source_turn_id": _id("turn", record.principal_id, record.source_turn_id),
                    "policy_shape": policy_shape,
                },
            )
        )
        await self._link("has_conversation_policy", principal, object_id)
        return object_id

    async def project_subscription(self, record: BriefingSubscription) -> str:
        principal = await self._principal(record.principal_id)
        object_id = _id("briefing-subscription", record.principal_id, record.subscription_id)
        await self._store.upsert_object(
            OntologyObjectRecord(
                id=object_id,
                object_type="BriefingSubscription",
                properties={
                    "id": object_id,
                    "principal_ref": principal,
                    "name": record.name,
                    "briefing_kind": record.spec.kind.value,
                    "cron_expression": record.cron_expression,
                    "timezone": record.timezone,
                    "delivery_modes": [mode.value for mode in record.delivery_modes],
                    "enabled": record.enabled,
                    "next_run_at": record.next_run_at,
                    "revision": record.revision,
                },
            )
        )
        await self._link("subscribed_to_briefing", principal, object_id)
        return object_id

    async def project_briefing_run(self, record: BriefingRun) -> str:
        principal = await self._principal(record.principal_id)
        object_id = _id("briefing-run", record.principal_id, record.run_id)
        properties: dict[str, object] = {
            "id": object_id,
            "principal_ref": principal,
            "scheduled_for": record.scheduled_for,
            "started_at": record.started_at,
            "status": record.status.value,
            "item_count": record.item_count,
            "evidence_refs": list(record.evidence_refs),
            "source_error_count": len(record.source_errors),
        }
        if record.subscription_id is not None:
            properties["subscription_ref"] = _id(
                "briefing-subscription", record.principal_id, record.subscription_id
            )
        if record.conversation_id is not None:
            properties["conversation_ref"] = _id(
                "conversation", record.principal_id, record.conversation_id
            )
        await self._store.upsert_object(
            OntologyObjectRecord(id=object_id, object_type="BriefingRun", properties=properties)
        )
        subscription_ref = properties.get("subscription_ref")
        if isinstance(subscription_ref, str) and await self._store.get_object(subscription_ref):
            await self._link("produced_briefing", subscription_ref, object_id)
        conversation_ref = properties.get("conversation_ref")
        if isinstance(conversation_ref, str) and await self._store.get_object(conversation_ref):
            await self._link("received_briefing", conversation_ref, object_id)
        return object_id

    async def project_workflow_definition(self, record: WorkflowDefinitionRecord) -> str:
        object_id = record.definition_id
        properties: dict[str, object] = {
            "id": object_id,
            "workflow_name": record.workflow_name,
            "workflow_version": record.workflow_version,
            "definition_hash": record.definition_hash,
            "action_catalog_digest": record.action_catalog_digest,
            "action_type_refs": sorted(record.resolved_action_versions),
            "origin": record.origin.value,
            "visibility": record.visibility.value,
            "lifecycle": record.lifecycle.value,
            "created_at": record.created_at,
        }
        if record.owner_ref is not None:
            properties["owner_ref"] = record.owner_ref
        if record.derived_from is not None:
            properties["derived_from"] = record.derived_from
        await self._store.upsert_object(
            OntologyObjectRecord(
                id=object_id, object_type="WorkflowDefinition", properties=properties
            )
        )
        if record.derived_from and await self._store.get_object(record.derived_from):
            await self._link("derived_from_workflow", object_id, record.derived_from)
        return object_id

    async def project_workflow_binding(self, record: WorkflowBindingRecord) -> str:
        principal = await self._principal(record.principal_id)
        object_id = _id("workflow-binding", record.principal_id, record.binding_id)
        schedule = (
            {"cron_expression": record.cron_expression, "timezone": record.timezone}
            if record.cron_expression and record.timezone
            else None
        )
        properties: dict[str, object] = {
            "id": object_id,
            "principal_ref": principal,
            "definition_ref": record.definition_id,
            "trigger": record.trigger.value,
            "enabled": record.enabled,
            "parameters": dict(record.parameters),
            "revision": record.revision,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
        if record.scope_ref is not None:
            properties["scope_ref"] = record.scope_ref
        if schedule is not None:
            properties["schedule"] = schedule
        await self._store.upsert_object(
            OntologyObjectRecord(id=object_id, object_type="WorkflowBinding", properties=properties)
        )
        await self._link("owns_workflow_binding", principal, object_id)
        if await self._store.get_object(record.definition_id):
            await self._link("binds_workflow_definition", object_id, record.definition_id)
        return object_id

    async def delete(self, object_id: str) -> bool:
        return await self._store.delete_object(object_id)

    async def _principal(self, principal_id: str) -> str:
        object_id = _id("principal", principal_id)
        if await self._store.get_object(object_id) is None:
            await self._store.upsert_object(
                OntologyObjectRecord(
                    id=object_id,
                    object_type="Principal",
                    properties={
                        "id": object_id,
                        "kind": "user",
                        "role": "authenticated",
                        "escalation_ref": "identity-provider",
                    },
                )
            )
        return object_id

    async def _link(self, kind: str, source: str, target: str) -> None:
        await self._store.upsert_link(
            OntologyLinkRecord(link_type=kind, from_id=source, to_id=target)
        )


def _turn_ref(record: ConversationTurnRecord) -> str:
    return f"conversation-turn:{record.conversation_id}:{record.turn_id}"


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _id(kind: str, principal_id: str, record_id: str | None = None) -> str:
    suffix = f":{record_id}" if record_id else ""
    return f"{kind}:{principal_id}{suffix}"


__all__ = ["UserContextOntologyProjector"]

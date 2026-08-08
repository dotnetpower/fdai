"""Production composition boundary for the independent Operator service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai_service_contracts import OperatorReadModel, OperatorTokenVerifier, ReadDataSource

from fdai_operator_service.auth import EntraJwtVerifier, OperatorAuthenticator
from fdai_operator_service.contracts import ReadinessProbe
from fdai_operator_service.environment import OperatorEnvironment
from fdai_operator_service.families.conversation import ConversationFamilyDependencies
from fdai_operator_service.families.iam import HilCallbackConfig, IamFamilyBindings
from fdai_operator_service.family_adapters import (
    PostgresConversationAdapters,
    PostgresOperationsAdapters,
    PostgresWorkflowAdapters,
    UnavailableConversationAdapters,
    UnavailableOperationsAdapters,
    UnavailableWorkflowAdapters,
)
from fdai_operator_service.family_authorization import OperatorFamilyAuthorizer
from fdai_operator_service.postgres import (
    PostgresOperatorReadModel,
    PostgresOperatorReadModelConfig,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    UnavailablePostgresFamilyStore,
)
from fdai_operator_service.postgres_iam import PostgresIamAdapters
from fdai_operator_service.projections import UnavailableOperatorReadModel
from fdai_operator_service.routes import OperatorRouteFamilies
from fdai_operator_service.runtime import OperatorRuntime

HIL_SIGNING_SECRET_ENV = "FDAI_CHATOPS_WEBHOOK_SECRET"  # noqa: S105
WEBHOOK_SIGNING_SECRET_ENV = "FDAI_OPERATOR_WEBHOOK_SECRET"  # noqa: S105


class OperatorComposition(Protocol):
    """Build the complete service-owned runtime from explicit provider seams."""

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> OperatorRuntime: ...


class TokenVerifierFactory(Protocol):
    """Build the process-local token verifier from validated environment state."""

    def __call__(self, environment: OperatorEnvironment) -> OperatorTokenVerifier: ...


def _build_entra_verifier(environment: OperatorEnvironment) -> OperatorTokenVerifier:
    return EntraJwtVerifier.from_environment(environment)


@dataclass(frozen=True, slots=True)
class ProductionOperatorComposition:
    """Bind production identity and read providers without implementation imports."""

    verifier_factory: TokenVerifierFactory = _build_entra_verifier
    read_model: OperatorReadModel | None = None
    readiness_probe: ReadinessProbe | None = None

    def build_runtime(self, environ: Mapping[str, str] | None = None) -> OperatorRuntime:
        """Bind a validated environment snapshot to service-owned HTTP dependencies."""
        environment = OperatorEnvironment.parse(os.environ if environ is None else environ)
        configured_read_model = self.read_model or _postgres_read_model(environment)
        family_store = _postgres_family_store(environment)
        authenticator = OperatorAuthenticator(
            verifier=self.verifier_factory(environment),
            group_ids=environment.group_ids,
        )
        return OperatorRuntime(
            environment=environment,
            authenticator=authenticator,
            read_model=configured_read_model or UnavailableOperatorReadModel(),
            data_sources=_build_data_sources(configured=configured_read_model is not None),
            route_families=_build_route_families(
                environment=environment,
                authenticator=authenticator,
                store=family_store,
            ),
            readiness_probe=self.readiness_probe
            or (family_store.probe_readiness if family_store is not None else _unavailable),
        )


def _postgres_read_model(environment: OperatorEnvironment) -> OperatorReadModel | None:
    if environment.database_url is None:
        return None
    return PostgresOperatorReadModel(
        PostgresOperatorReadModelConfig(
            dsn=environment.database_url,
            statement_timeout_ms=environment.database_statement_timeout_ms,
            connect_timeout_s=environment.database_connect_timeout_s,
        )
    )


def _build_route_families(
    *,
    environment: OperatorEnvironment,
    authenticator: OperatorAuthenticator,
    store: PostgresFamilyStore | None,
) -> OperatorRouteFamilies:
    authorizer = OperatorFamilyAuthorizer(authenticator)
    role_group_ids = {role.value: group_id for role, group_id in environment.group_ids.items()}
    if store is None:
        unavailable_conversation = UnavailableConversationAdapters()
        unavailable_workflow = UnavailableWorkflowAdapters()
        unavailable_operations = UnavailableOperationsAdapters()
        unavailable_iam = PostgresIamAdapters(UnavailablePostgresFamilyStore())
        return OperatorRouteFamilies(
            conversation=ConversationFamilyDependencies(
                authorizer=authorizer,
                projections=unavailable_conversation,
                outbox=unavailable_conversation,
                streams=unavailable_conversation,
            ),
            iam=IamFamilyBindings(
                authorize=authorizer.iam,
                authenticate=authorizer.iam,
                access_grants=unavailable_iam,
                human_access=unavailable_iam,
                directory=unavailable_iam,
                assignments=unavailable_iam,
                handover_goals=unavailable_iam,
                model_settings=unavailable_iam,
                runtime_settings=unavailable_iam,
                kill_switch=unavailable_iam,
                configuration_review=unavailable_iam,
                role_group_ids=role_group_ids,
            ),
            workflow_authorize=authorizer.workflow,
            workflow_read_store=unavailable_workflow,
            workflow_proposal_writer=unavailable_workflow,
            operations_projection_reader=unavailable_operations,
            operations_proposal_writer=unavailable_operations,
            operations_replay_reader=unavailable_operations,
            operations_webhook_verifier=unavailable_operations,
        )

    postgres_conversation = PostgresConversationAdapters(store)
    postgres_workflow = PostgresWorkflowAdapters(store)
    iam = PostgresIamAdapters(store)
    postgres_operations = PostgresOperationsAdapters(
        store,
        webhook_secret=environment.values.get(WEBHOOK_SIGNING_SECRET_ENV, "").strip() or None,
    )
    hil_secret = environment.values.get(HIL_SIGNING_SECRET_ENV, "").strip() or None
    return OperatorRouteFamilies(
        conversation=ConversationFamilyDependencies(
            authorizer=authorizer,
            projections=postgres_conversation,
            outbox=postgres_conversation,
            streams=postgres_conversation,
        ),
        iam=IamFamilyBindings(
            authorize=authorizer.iam,
            authenticate=authorizer.iam,
            access_grants=iam,
            human_access=iam,
            directory=iam,
            assignments=iam,
            handover_goals=iam,
            model_settings=iam,
            runtime_settings=iam,
            kill_switch=iam,
            configuration_review=iam,
            hil_registry=iam if hil_secret is not None else None,
            hil_outbox=iam if hil_secret is not None else None,
            hil_config=HilCallbackConfig(hil_secret) if hil_secret is not None else None,
            role_group_ids=role_group_ids,
        ),
        workflow_authorize=authorizer.workflow,
        workflow_read_store=postgres_workflow,
        workflow_proposal_writer=postgres_workflow,
        operations_projection_reader=postgres_operations,
        operations_proposal_writer=postgres_operations,
        operations_replay_reader=postgres_operations,
        operations_webhook_verifier=postgres_operations,
    )


def _postgres_family_store(environment: OperatorEnvironment) -> PostgresFamilyStore | None:
    if environment.database_url is None:
        return None
    if environment.database_role is None:
        raise RuntimeError("validated Operator database role is missing")
    return PostgresFamilyStore(
        PostgresFamilyStoreConfig(
            dsn=environment.database_url,
            role=environment.database_role,
            statement_timeout_ms=environment.database_statement_timeout_ms,
            connect_timeout_s=environment.database_connect_timeout_s,
        )
    )


def _build_data_sources(*, configured: bool) -> tuple[ReadDataSource, ...]:
    reason = None if configured else "Authoritative service-local projections are not configured."
    return (
        ReadDataSource(
            key="operational-state",
            source="service-local-projection" if configured else "not-configured",
            routes=(
                "/audit",
                "/audit/{correlation_id}/trace",
                "/hil-queue",
                "/incidents",
                "/incidents/stream",
                "/kpi",
                "/rca",
            ),
            availability="unknown" if configured else "unavailable",
            configured=configured,
            reachable=None,
            authoritative=configured,
            durable=True if configured else None,
            reason=reason,
        ),
        ReadDataSource(
            key="notification-template",
            source="operator-service",
            routes=("/notification-templates/incident-opened",),
            availability="available",
            configured=True,
            reachable=True,
            authoritative=True,
            durable=False,
        ),
    )


async def _unavailable() -> bool:
    return False


__all__ = [
    "HIL_SIGNING_SECRET_ENV",
    "OperatorComposition",
    "ProductionOperatorComposition",
    "TokenVerifierFactory",
    "WEBHOOK_SIGNING_SECRET_ENV",
]

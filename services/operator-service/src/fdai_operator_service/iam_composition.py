"""Compose Operator IAM adapters without widening the service composition root."""

from __future__ import annotations

from collections.abc import Mapping

import httpx
from azure.core.exceptions import AzureError
from azure.identity.aio import ManagedIdentityCredential
from fdai_service_contracts.venue import ExecutionVenue, resolve_execution_venue

from fdai_operator_service.adapters import OperatorSemanticKafkaBus
from fdai_operator_service.adapters.azure_cli_token import azure_cli_token
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.environment import (
    OperatorEnvironment,
    OperatorServiceConfigurationError,
)
from fdai_operator_service.families.conversation.channel_edge.environment import (
    TEAMS_JWKS_URL_ENV,
)
from fdai_operator_service.families.conversation.channel_edge.provider_adapters import (
    RemoteJwksConfig,
    RemoteJwksProvider,
)
from fdai_operator_service.families.conversation.channel_edge.teams_auth import (
    TeamsServiceTokenVerifier,
    TeamsTokenConfig,
)
from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError
from fdai_operator_service.families.iam import HilCallbackConfig, IamFamilyBindings
from fdai_operator_service.families.iam.hil_callback_authority import (
    TEAMS_APPLICATION_ID_ENV,
    TEAMS_APPROVAL_CHANNEL_ID_ENV,
    TEAMS_APPROVAL_TEAM_ID_ENV,
    EntraHilCallbackAuthority,
    HilCallbackAuthorityConfig,
)
from fdai_operator_service.families.iam.hil_decision_outbox import (
    DurableHilDecisionOutboxPublisher,
    HilDecisionOutboxBridge,
)
from fdai_operator_service.families.iam.hil_teams_callback import (
    TeamsHilCallbackConfig,
    TeamsHilCallbackNormalizer,
)
from fdai_operator_service.family_authorization import OperatorFamilyAuthorizer
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    UnavailablePostgresFamilyStore,
)
from fdai_operator_service.postgres_iam import PostgresIamAdapters
from fdai_operator_service.slack_webhook_diagnostics import SlackWebhookDiagnosticTester
from fdai_operator_service.teams_workflow_binding import (
    KeyVaultTeamsWorkflowBindingStore,
    LocalEncryptedTeamsWorkflowBindingStore,
    TeamsWorkflowBindingConfig,
    TeamsWorkflowBindingError,
    TeamsWorkflowBindingStore,
)
from fdai_operator_service.teams_workflow_diagnostics import TeamsWorkflowDiagnosticTester

HIL_SIGNING_SECRET_ENV = "FDAI_CHATOPS_WEBHOOK_SECRET"  # noqa: S105
TEAMS_WORKFLOW_VAULT_URL_ENV = "FDAI_TEAMS_WORKFLOW_KEY_VAULT_URL"
TEAMS_WORKFLOW_SECRET_NAME_ENV = "FDAI_TEAMS_WORKFLOW_KEY_VAULT_SECRET_NAME"  # noqa: S105
TEAMS_WORKFLOW_IDENTITY_CLIENT_ID_ENV = "FDAI_TEAMS_WORKFLOW_BINDING_MI_CLIENT_ID"


def build_teams_hil_http_client(environment: OperatorEnvironment) -> httpx.AsyncClient | None:
    """Own one bounded HTTPS client only for a complete Teams approval surface."""
    if not environment.values.get(HIL_SIGNING_SECRET_ENV, "").strip():
        return None
    if not environment.values.get(TEAMS_JWKS_URL_ENV, "").strip():
        return None
    return httpx.AsyncClient(timeout=10.0, follow_redirects=False)


def build_hil_decision_outbox_bridge(
    *,
    environment: OperatorEnvironment,
    store: PostgresFamilyStore | None,
    semantic_bus: OperatorSemanticKafkaBus | None,
) -> HilDecisionOutboxBridge | None:
    """Compose durable HIL decision delivery only when every binding is available."""
    if (
        store is None
        or semantic_bus is None
        or environment.hil_decision_topic is None
        or not environment.values.get(HIL_SIGNING_SECRET_ENV, "").strip()
    ):
        return None
    return HilDecisionOutboxBridge(
        store=store,
        registry=PostgresIamAdapters(store),
        publisher=semantic_bus,
        topic=environment.hil_decision_topic,
    )


def build_teams_workflow_binding_store(
    environment: OperatorEnvironment,
    store: PostgresFamilyStore,
) -> TeamsWorkflowBindingStore | None:
    """Bind the dedicated endpoint secret writer when its full config is present."""

    vault_url = environment.values.get(TEAMS_WORKFLOW_VAULT_URL_ENV, "").strip()
    secret_name = environment.values.get(TEAMS_WORKFLOW_SECRET_NAME_ENV, "").strip()
    venue = resolve_execution_venue(environment.values)
    if not vault_url and not secret_name:
        if venue is ExecutionVenue.LOCAL and environment.database_url is not None:
            return LocalEncryptedTeamsWorkflowBindingStore(
                store=store,
                key_material=environment.database_url,
            )
        return None
    if not vault_url or not secret_name:
        raise OperatorServiceConfigurationError(
            f"{TEAMS_WORKFLOW_VAULT_URL_ENV} and {TEAMS_WORKFLOW_SECRET_NAME_ENV} "
            "MUST be configured together"
        )
    if venue is ExecutionVenue.LOCAL:

        async def local_token_provider(_: str) -> str:
            try:
                return await azure_cli_token("https://vault.azure.net")
            except ConversationBoundaryError as exc:
                raise TeamsWorkflowBindingError(
                    "Teams Workflow binding Azure CLI credential is unavailable"
                ) from exc

        teams_token_provider = local_token_provider
    else:
        client_id = environment.values.get(TEAMS_WORKFLOW_IDENTITY_CLIENT_ID_ENV, "").strip()
        if not client_id:
            raise OperatorServiceConfigurationError(
                f"{TEAMS_WORKFLOW_IDENTITY_CLIENT_ID_ENV} is required in deployed mode"
            )

        async def managed_token_provider(scope: str) -> str:
            try:
                async with ManagedIdentityCredential(client_id=client_id) as credential:
                    token = await credential.get_token(scope)
            except AzureError as exc:
                raise TeamsWorkflowBindingError(
                    "Teams Workflow binding managed identity is unavailable"
                ) from exc
            return str(token.token)

        teams_token_provider = managed_token_provider
    return KeyVaultTeamsWorkflowBindingStore(
        config=TeamsWorkflowBindingConfig(
            vault_url=vault_url,
            secret_name=secret_name,
        ),
        token_provider=teams_token_provider,
    )


def build_unavailable_iam_bindings(
    *,
    authorizer: OperatorFamilyAuthorizer,
    role_group_ids: Mapping[str, str],
) -> IamFamilyBindings:
    """Build fail-closed IAM bindings when the authoritative store is unavailable."""
    unavailable = PostgresIamAdapters(UnavailablePostgresFamilyStore())
    return IamFamilyBindings(
        authorize=authorizer.iam,
        authenticate=authorizer.iam,
        access_grants=unavailable,
        human_access=unavailable,
        directory=unavailable,
        assignments=unavailable,
        handover_goals=unavailable,
        model_settings=unavailable,
        runtime_settings=unavailable,
        kill_switch=unavailable,
        configuration_review=unavailable,
        role_group_ids=dict(role_group_ids),
    )


def build_postgres_iam_bindings(
    *,
    environment: OperatorEnvironment,
    authenticator: OperatorAuthenticator,
    authorizer: OperatorFamilyAuthorizer,
    store: PostgresFamilyStore,
    semantic_bus: OperatorSemanticKafkaBus | None,
    teams_http_client: httpx.AsyncClient | None,
    role_group_ids: Mapping[str, str],
) -> IamFamilyBindings:
    """Compose the durable IAM family without granting execution authority."""
    iam = PostgresIamAdapters(store)
    hil_secret = environment.values.get(HIL_SIGNING_SECRET_ENV, "").strip() or None
    hil_authority = (
        EntraHilCallbackAuthority(
            authenticator=authenticator,
            config=HilCallbackAuthorityConfig.from_environment(
                environment.values,
                group_ids=environment.group_ids,
            ),
        )
        if hil_secret is not None
        else None
    )
    hil_outbox = (
        DurableHilDecisionOutboxPublisher(
            durable=iam,
            publisher=semantic_bus,
            topic=environment.hil_decision_topic,
            ledger=iam,
            registry=iam,
        )
        if hil_secret is not None
        and semantic_bus is not None
        and environment.hil_decision_topic is not None
        else None
    )
    hil_teams_normalizer = (
        _teams_hil_normalizer(environment, teams_http_client)
        if hil_secret is not None and teams_http_client is not None
        else None
    )
    return IamFamilyBindings(
        authorize=authorizer.iam,
        authenticate=authorizer.iam,
        access_grants=iam,
        human_access=iam,
        directory=iam,
        assignments=iam,
        handover_goals=iam,
        model_settings=iam,
        runtime_settings=iam,
        teams_workflow_tester=TeamsWorkflowDiagnosticTester(
            store,
            binding_store=build_teams_workflow_binding_store(environment, store),
        ),
        slack_webhook_tester=SlackWebhookDiagnosticTester(store),
        kill_switch=iam,
        configuration_review=iam,
        hil_registry=iam if hil_secret is not None else None,
        hil_outbox=hil_outbox,
        hil_config=HilCallbackConfig(hil_secret) if hil_secret is not None else None,
        hil_authority=hil_authority,
        hil_audit=iam if hil_secret is not None else None,
        hil_context=iam if hil_secret is not None else None,
        hil_teams_normalizer=hil_teams_normalizer,
        role_group_ids=dict(role_group_ids),
    )


def _teams_hil_normalizer(
    environment: OperatorEnvironment,
    http_client: httpx.AsyncClient,
) -> TeamsHilCallbackNormalizer | None:
    values = environment.values
    jwks_url = values.get(TEAMS_JWKS_URL_ENV, "").strip()
    application_id = values.get(TEAMS_APPLICATION_ID_ENV, "").strip()
    config = TeamsHilCallbackConfig.from_environment(
        values,
        application_id=application_id,
        team_id=values.get(TEAMS_APPROVAL_TEAM_ID_ENV, "").strip(),
        channel_id=values.get(TEAMS_APPROVAL_CHANNEL_ID_ENV, "").strip(),
    )
    if config is None:
        return None
    if not jwks_url:
        raise OperatorServiceConfigurationError(
            f"{TEAMS_JWKS_URL_ENV} is required for the Teams approval callback"
        )
    return TeamsHilCallbackNormalizer(
        config=config,
        tokens=TeamsServiceTokenVerifier(
            config=TeamsTokenConfig(application_id=config.application_id),
            jwks=RemoteJwksProvider(
                config=RemoteJwksConfig(url=jwks_url),
                http_client=http_client,
            ),
        ),
    )


__all__ = [
    "HIL_SIGNING_SECRET_ENV",
    "TEAMS_WORKFLOW_IDENTITY_CLIENT_ID_ENV",
    "TEAMS_WORKFLOW_SECRET_NAME_ENV",
    "TEAMS_WORKFLOW_VAULT_URL_ENV",
    "HilDecisionOutboxBridge",
    "build_hil_decision_outbox_bridge",
    "build_postgres_iam_bindings",
    "build_teams_workflow_binding_store",
    "build_teams_hil_http_client",
    "build_unavailable_iam_bindings",
]

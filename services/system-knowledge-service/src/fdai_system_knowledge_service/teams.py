"""Stable Teams facade for the System Knowledge Service."""

from fdai_system_knowledge_service.teams_auth import (
    JwksProvider,
    PyJwtServiceTokenVerifier,
    RemoteJwksProvider,
    ServiceTokenVerifier,
    TeamsIngressError,
    VerifiedServiceToken,
)
from fdai_system_knowledge_service.teams_ingress import (
    TeamsMentionVerifier,
    VerifiedKnowledgeTurn,
)
from fdai_system_knowledge_service.teams_outgoing_webhook import (
    TeamsOutgoingWebhookVerifier,
)
from fdai_system_knowledge_service.teams_publisher import (
    AzureChannelTokenProvider,
    ChannelAccessToken,
    ChannelTokenProvider,
    TeamsPublisher,
    TeamsPublishError,
)

__all__ = [
    "AzureChannelTokenProvider",
    "ChannelAccessToken",
    "ChannelTokenProvider",
    "JwksProvider",
    "PyJwtServiceTokenVerifier",
    "RemoteJwksProvider",
    "ServiceTokenVerifier",
    "TeamsIngressError",
    "TeamsMentionVerifier",
    "TeamsOutgoingWebhookVerifier",
    "TeamsPublishError",
    "TeamsPublisher",
    "VerifiedKnowledgeTurn",
    "VerifiedServiceToken",
]

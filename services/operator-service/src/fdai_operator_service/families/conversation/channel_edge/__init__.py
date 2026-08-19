"""Operator-owned authenticated channel edge adapters."""

from fdai_operator_service.families.conversation.channel_edge.models import (
    AuthenticatedInboundTurn,
    ChannelAttachment,
    ChannelDeliveryError,
    ChannelDeliveryReceipt,
    ChannelKind,
    InboundChannelTurn,
    RenderedChannelMessage,
)
from fdai_operator_service.families.conversation.channel_edge.pipeline import (
    ChannelDeliveryPipeline,
)
from fdai_operator_service.families.conversation.channel_edge.pipeline_contracts import (
    ChannelDeliveryPipelineConfig,
    ChannelPipelineResult,
    ChannelPrincipalContext,
    ChannelPrincipalResolver,
)
from fdai_operator_service.families.conversation.channel_edge.presentation import (
    normalize_terminal_presentation,
)
from fdai_operator_service.families.conversation.channel_edge.publishers import (
    SlackResponsePublisher,
    TeamsResponsePublisher,
)
from fdai_operator_service.families.conversation.channel_edge.queues import (
    SlackIngressQueue,
    TeamsEndpointRegistry,
    TeamsIngressQueue,
)
from fdai_operator_service.families.conversation.channel_edge.renderers import (
    SlackPresentationRenderer,
    TeamsPresentationRenderer,
)
from fdai_operator_service.families.conversation.channel_edge.worker import (
    ChannelDeliveryWorker,
    ChannelDeliveryWorkerConfig,
)

__all__ = [
    "AuthenticatedInboundTurn",
    "ChannelAttachment",
    "ChannelDeliveryError",
    "ChannelDeliveryPipeline",
    "ChannelDeliveryPipelineConfig",
    "ChannelDeliveryReceipt",
    "ChannelDeliveryWorker",
    "ChannelDeliveryWorkerConfig",
    "ChannelKind",
    "InboundChannelTurn",
    "ChannelPipelineResult",
    "ChannelPrincipalContext",
    "ChannelPrincipalResolver",
    "RenderedChannelMessage",
    "SlackIngressQueue",
    "SlackPresentationRenderer",
    "SlackResponsePublisher",
    "TeamsEndpointRegistry",
    "TeamsIngressQueue",
    "TeamsPresentationRenderer",
    "TeamsResponsePublisher",
    "normalize_terminal_presentation",
]

"""Compatibility facade for conversation preflight contracts and routing."""

from .conversation_preflight_boundary import (
    ConversationPreflightBoundary,
    preflight_selects_general_knowledge,
)
from .conversation_preflight_contracts import (
    DIRECT_SOCIAL_ACTS,
    SOCIAL_NARRATOR_CAPABILITY_IDS,
    ContextDependency,
    ConversationPreflightBinding,
    ConversationPreflightModel,
    ConversationPreflightProposal,
    ConversationPreflightResult,
    GeneralKnowledgeDraft,
    GeneralKnowledgeSignal,
    OperationalPreflightFamily,
    OperationalSignal,
    OperationalWindowMode,
    SocialAct,
    SocialResponseNarratorBinding,
    SocialResponseNarratorModel,
    SocialResponseNarratorResult,
)
from .conversation_preflight_family_validation import preflight_operational_judgment
from .conversation_preflight_targets import (
    named_subscription_requested,
    operational_target_is_exact,
    operational_target_is_generic,
    operational_time_is_past_hour,
)

__all__ = [
    "ContextDependency",
    "ConversationPreflightBinding",
    "ConversationPreflightBoundary",
    "ConversationPreflightModel",
    "ConversationPreflightProposal",
    "ConversationPreflightResult",
    "DIRECT_SOCIAL_ACTS",
    "GeneralKnowledgeDraft",
    "GeneralKnowledgeSignal",
    "OperationalPreflightFamily",
    "OperationalWindowMode",
    "OperationalSignal",
    "SOCIAL_NARRATOR_CAPABILITY_IDS",
    "SocialResponseNarratorBinding",
    "SocialResponseNarratorModel",
    "SocialResponseNarratorResult",
    "SocialAct",
    "named_subscription_requested",
    "operational_target_is_generic",
    "operational_target_is_exact",
    "operational_time_is_past_hour",
    "preflight_selects_general_knowledge",
    "preflight_operational_judgment",
]

"""Evidence-bound presentation projections for Operator conversations.

Responsibility:
Select value-free layouts and compile verified evidence into bounded artifacts.

Boundary:
Accept answer plans and verified request-local evidence; HTTP envelopes, SSE
frames, authentication, cancellation, and terminal delivery stay route-owned.

Authority and state:
Read-only and request-local. Presentation cannot change evidence, grant
authority, persist state, or receive an executor identity.

Dependencies:
Answer-plan contracts, structured completion capability, and pure evidence
projection helpers supplied by the Operator API delivery layer.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""

from fdai.delivery.operator_api.projections.conversation.presentation.artifact import (
    response_presentation_artifact,
)
from fdai.delivery.operator_api.projections.conversation.presentation.contract import (
    PresentationPlacement,
    PresentationPlan,
    PresentationProfile,
    PresentationSlot,
    default_presentation_plan,
    parse_presentation_plan,
    presentation_plan_schema,
)
from fdai.delivery.operator_api.projections.conversation.presentation.planner import (
    PresentationDecision,
    adapt_answer_plan_for_presentation,
    select_answer_presentation,
)
from fdai.delivery.operator_api.projections.conversation.presentation.profiles import (
    presentation_profile,
)

__all__ = [
    "PresentationDecision",
    "PresentationPlan",
    "PresentationPlacement",
    "PresentationProfile",
    "PresentationSlot",
    "adapt_answer_plan_for_presentation",
    "default_presentation_plan",
    "parse_presentation_plan",
    "presentation_plan_schema",
    "presentation_profile",
    "response_presentation_artifact",
    "select_answer_presentation",
]

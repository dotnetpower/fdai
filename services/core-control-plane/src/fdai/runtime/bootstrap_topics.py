"""Assemble the complete logical topic registry for the Core runtime bus."""

from fdai_service_contracts.alert_noise_wire import ALERT_NOISE_RESULT_TOPIC
from fdai_service_contracts.assignment_transport import (
    ASSIGNMENT_PROJECTION_TOPIC,
    ASSIGNMENT_REQUEST_TOPIC,
)
from fdai_service_contracts.background_task_projection import (
    BACKGROUND_TASK_PROJECTION_TOPIC,
)
from fdai_service_contracts.incident_creation import INCIDENT_CREATION_REQUEST_TOPIC
from fdai_service_contracts.incident_intervention import (
    INCIDENT_INTERVENTION_REQUEST_TOPIC,
)
from fdai_service_contracts.notification_receipt import (
    NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
)
from fdai_service_contracts.read_investigation import (
    READ_INVESTIGATION_COMPLETION_TOPIC,
    READ_INVESTIGATION_REQUEST_TOPIC,
)
from fdai_service_contracts.rule_activation_transport import (
    RULE_ACTIVATION_REQUEST_TOPIC,
)
from fdai_service_contracts.semantic_turn import (
    SEMANTIC_PROGRESS_TOPIC,
    SEMANTIC_PROJECTION_TOPIC,
    SEMANTIC_REQUEST_TOPIC,
)

from fdai.agents import OWNED_OBJECT_TOPICS
from fdai.core.readiness.coordinator import _TRANSITION_TOPIC
from fdai.delivery.agent_introspection_bus import AGENT_INTROSPECTION_TOPICS
from fdai.runtime.bootstrap_bindings import RECONCILIATION_TOPICS, RULE_GENERATION_TOPICS
from fdai.shared.providers.operating_model import OPERATING_MODEL_TOPIC

RUNTIME_LOGICAL_TOPICS = (
    OWNED_OBJECT_TOPICS
    | AGENT_INTROSPECTION_TOPICS
    | frozenset(
        {
            _TRANSITION_TOPIC,
            ALERT_NOISE_RESULT_TOPIC,
            ASSIGNMENT_REQUEST_TOPIC,
            ASSIGNMENT_PROJECTION_TOPIC,
            BACKGROUND_TASK_PROJECTION_TOPIC,
            INCIDENT_CREATION_REQUEST_TOPIC,
            INCIDENT_INTERVENTION_REQUEST_TOPIC,
            NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
            OPERATING_MODEL_TOPIC,
            SEMANTIC_REQUEST_TOPIC,
            SEMANTIC_PROJECTION_TOPIC,
            SEMANTIC_PROGRESS_TOPIC,
            READ_INVESTIGATION_REQUEST_TOPIC,
            READ_INVESTIGATION_COMPLETION_TOPIC,
            RULE_ACTIVATION_REQUEST_TOPIC,
        }
    )
    | RECONCILIATION_TOPICS
    | RULE_GENERATION_TOPICS
)

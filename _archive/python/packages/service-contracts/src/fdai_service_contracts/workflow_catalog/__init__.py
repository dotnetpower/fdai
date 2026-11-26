"""Shared Workflow catalog contracts and pure validation loader."""

from fdai_service_contracts.workflow_catalog.base import SemVer, WorkflowCatalogBase
from fdai_service_contracts.workflow_catalog.enums import (
    CEILING_ROLE_RANK,
    CeilingRole,
    Mode,
    WorkflowStepKind,
    WorkflowTriggerKind,
    WorkflowTriggerSignalReferenceKind,
)
from fdai_service_contracts.workflow_catalog.loader import (
    WorkflowCatalogError,
    WorkflowIssue,
    load_workflow_from_mapping,
    workflow_names,
    workflow_to_yaml,
)
from fdai_service_contracts.workflow_catalog.models import (
    PromotionGate,
    Workflow,
    WorkflowStep,
    WorkflowTrigger,
)
from fdai_service_contracts.workflow_catalog.signal_type import (
    SignalDispatchMode,
    SignalTypeEntry,
    SignalTypeRegistry,
)
from fdai_service_contracts.workflow_catalog.validation_context import (
    WORKFLOW_VALIDATION_CONTEXT_PROJECTION_KEY,
    WORKFLOW_VALIDATION_CONTEXT_SCHEMA_VERSION,
    WorkflowValidationContext,
)
from fdai_service_contracts.workflow_catalog.workflow_trigger_event import (
    WorkflowTriggerEventEntry,
    WorkflowTriggerEventRegistry,
    WorkflowTriggerEventSemantics,
)

__all__ = [
    "CEILING_ROLE_RANK",
    "CeilingRole",
    "Mode",
    "PromotionGate",
    "SemVer",
    "SignalDispatchMode",
    "SignalTypeEntry",
    "SignalTypeRegistry",
    "WORKFLOW_VALIDATION_CONTEXT_PROJECTION_KEY",
    "WORKFLOW_VALIDATION_CONTEXT_SCHEMA_VERSION",
    "Workflow",
    "WorkflowCatalogBase",
    "WorkflowCatalogError",
    "WorkflowIssue",
    "WorkflowStep",
    "WorkflowStepKind",
    "WorkflowTrigger",
    "WorkflowTriggerEventEntry",
    "WorkflowTriggerEventRegistry",
    "WorkflowTriggerEventSemantics",
    "WorkflowTriggerKind",
    "WorkflowTriggerSignalReferenceKind",
    "WorkflowValidationContext",
    "load_workflow_from_mapping",
    "workflow_names",
    "workflow_to_yaml",
]

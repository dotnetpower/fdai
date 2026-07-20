"""Composition helper for governed trajectory projection and export."""

from __future__ import annotations

from dataclasses import dataclass, replace

from fdai.composition._helpers import Container
from fdai.core.trajectory import (
    TrajectoryDatasetAdminService,
    TrajectoryJoinService,
    TrajectoryRetentionService,
)
from fdai.delivery.trajectory import (
    ExportQuarantineStore,
    TrajectoryDatasetExportService,
    TrajectoryJsonlExporter,
)
from fdai.shared.providers.trajectory import (
    ApprovalSnapshotProvider,
    AuditSnapshotProvider,
    ConversationSnapshotProvider,
    OutcomeSnapshotProvider,
    ToolSnapshotProvider,
    TrajectoryAccessAuthorizer,
    TrajectoryArtifactDeleter,
    TrajectoryDatasetStore,
)


@dataclass(frozen=True, slots=True)
class TrajectoryRuntime:
    """Bound seams handed to batch export and read-only administration."""

    container: Container
    admin: TrajectoryDatasetAdminService
    exporter: TrajectoryJsonlExporter
    exports: TrajectoryDatasetExportService
    retention: TrajectoryRetentionService


def wire_trajectory_runtime(
    container: Container,
    *,
    authorizer: TrajectoryAccessAuthorizer,
    audit: AuditSnapshotProvider,
    conversation: ConversationSnapshotProvider,
    tool: ToolSnapshotProvider,
    approval: ApprovalSnapshotProvider,
    outcome: OutcomeSnapshotProvider,
    dataset_store: TrajectoryDatasetStore,
    quarantine_store: ExportQuarantineStore,
    artifact_deleter: TrajectoryArtifactDeleter,
) -> TrajectoryRuntime:
    """Return a fully bound runtime without widening the default container."""

    join = TrajectoryJoinService(
        authorizer=authorizer,
        audit=audit,
        conversation=conversation,
        tool=tool,
        approval=approval,
        outcome=outcome,
    )
    bound = replace(
        container,
        trajectory_dataset_store=dataset_store,
        trajectory_join_service=join,
    )
    exporter = TrajectoryJsonlExporter(quarantine=quarantine_store)
    return TrajectoryRuntime(
        container=bound,
        admin=TrajectoryDatasetAdminService(authorizer=authorizer, store=dataset_store),
        exporter=exporter,
        exports=TrajectoryDatasetExportService(exporter=exporter, store=dataset_store),
        retention=TrajectoryRetentionService(store=dataset_store, artifacts=artifact_deleter),
    )


__all__ = ["TrajectoryRuntime", "wire_trajectory_runtime"]

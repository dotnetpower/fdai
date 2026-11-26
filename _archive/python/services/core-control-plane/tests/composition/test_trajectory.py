from fdai.composition import Container, wire_trajectory_runtime
from fdai.core.trajectory import (
    AllowlistTrajectoryAccessAuthorizer,
    InMemoryTrajectoryDatasetStore,
)
from fdai.delivery.trajectory import ExportQuarantineRecord
from fdai.shared.providers.trajectory import ImmutableTrajectorySnapshot


class EmptySnapshots:
    async def snapshot(self, **_: object) -> tuple[ImmutableTrajectorySnapshot, ...]:
        return ()


class MemoryQuarantine:
    def __init__(self) -> None:
        self.records: list[ExportQuarantineRecord] = []

    async def put(self, record: ExportQuarantineRecord) -> None:
        self.records.append(record)


class MemoryArtifacts:
    async def delete(self, storage_ref: str) -> None:
        return None


def test_wire_trajectory_runtime_binds_public_container_seams(container: Container) -> None:
    source = EmptySnapshots()
    store = InMemoryTrajectoryDatasetStore()
    runtime = wire_trajectory_runtime(
        container,
        authorizer=AllowlistTrajectoryAccessAuthorizer(
            {"owner-example": frozenset({("scope-example", "quality-review")})}
        ),
        audit=source,
        conversation=source,
        tool=source,
        approval=source,
        outcome=source,
        dataset_store=store,
        quarantine_store=MemoryQuarantine(),
        artifact_deleter=MemoryArtifacts(),
    )

    assert runtime.container is not container
    assert runtime.container.trajectory_dataset_store is store
    assert runtime.container.trajectory_join_service is not None
    assert runtime.admin is not None
    assert runtime.exporter is not None
    assert runtime.exports is not None
    assert runtime.retention is not None

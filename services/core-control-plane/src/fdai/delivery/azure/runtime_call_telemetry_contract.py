"""Azure Monitor runtime-call query and internal endpoint witness value."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

RUNTIME_CALL_TELEMETRY_KQL = """
ContainerAppConsoleLogs_CL
| extend record = parse_json(Log_s)
| where tostring(record.message) == "runtime_call_endpoint_observed"
| project
    observed_at = TimeGenerated,
    schema_version = tostring(record.schema_version),
    observation_id = tostring(record.observation_id),
    caller_resource_id = tostring(record.caller_resource_id),
    target_resource_id = tostring(record.target_resource_id),
    endpoint_role = tostring(record.endpoint_role),
    platform_resource_id = tostring(_ResourceId),
    platform_name = tostring(ContainerAppName_s),
    platform_revision_name = tostring(RevisionName_s),
    platform_replica_name = tostring(ContainerGroupName_s),
    source_container_name = tostring(ContainerName_s),
    execution_authority = tobool(record.execution_authority),
    mutation_authority = tobool(record.mutation_authority),
    source_container_group_id = tostring(ContainerGroupId_g),
    source_container_id = tostring(ContainerId_g),
    source_platform_timestamp = tostring(_timestamp_d),
    table_name = "ContainerAppConsoleLogs_CL"
| order by observed_at asc, observation_id asc, source_container_id asc
""".strip()


@dataclass(frozen=True, slots=True)
class RuntimeCallEndpointWitness:
    """Retain one parsed platform endpoint witness."""

    observation_id: str
    endpoint_role: str
    caller_arm_id: str
    target_arm_id: str
    platform_revision_name: str
    platform_replica_name: str
    source_container_name: str
    source_container_id: str
    observed_at: datetime
    evidence_ref: str

    @property
    def endpoint_arm_id(self) -> str:
        """Return the endpoint asserted by this witness role."""

        return self.caller_arm_id if self.endpoint_role == "caller" else self.target_arm_id


__all__ = ["RUNTIME_CALL_TELEMETRY_KQL", "RuntimeCallEndpointWitness"]

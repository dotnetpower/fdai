import {
  normalizeObservationSource,
  type ObservationSource,
} from "../hooks/observation-source";
import type { AgentStreamStatus } from "../hooks/use-agent-stream";

export function agentActivitySnapshotSource(source: string): ObservationSource {
  return source === "durable-operational-projection"
    ? "runtime-observed"
    : normalizeObservationSource(source);
}

export function agentEvidenceAvailable(
  status: AgentStreamStatus,
  snapshotAvailable: boolean,
): boolean {
  return status === "open" || snapshotAvailable;
}

export function agentObservationSource(
  status: AgentStreamStatus,
  streamSource: ObservationSource,
  snapshotSource: ObservationSource,
): ObservationSource {
  return status === "open" ? streamSource : snapshotSource;
}

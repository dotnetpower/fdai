import type { OperatorApiClient } from "../api";
import type {
  CostGovernanceAvailability,
  CostGovernanceProjection,
  CostGovernanceSurface,
} from "../api-cost-governance";

export interface CostGovernanceClient {
  costGovernanceAvailability(): Promise<CostGovernanceAvailability>;
  costGovernance(surface: CostGovernanceSurface): Promise<CostGovernanceProjection>;
}

export async function loadCostGovernance(
  client: CostGovernanceClient,
  surface: CostGovernanceSurface,
): Promise<CostGovernanceProjection | CostGovernanceAvailability> {
  const availability = await client.costGovernanceAvailability();
  if (!availability.available || !availability.enabled || !availability.access_allowed) {
    return availability;
  }
  return client.costGovernance(surface);
}

export function isCostGovernanceProjection(
  value: CostGovernanceProjection | CostGovernanceAvailability,
): value is CostGovernanceProjection {
  return "surface" in value;
}

export function isCostGovernanceNavigationVisible(
  availability: CostGovernanceAvailability,
): boolean {
  return availability.available && availability.enabled && availability.access_allowed;
}

export function asCostGovernanceClient(client: OperatorApiClient): CostGovernanceClient {
  return client;
}

import { describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../api";
import type { DashboardKpi } from "../types";
import { loadDashboardOverview } from "./dashboard.loading";

const KPI: DashboardKpi = {
  event_count: 10,
  shadow_share: 0.95,
  enforce_share: 0.05,
  hil_pending: 0,
  by_action_kind: {},
  by_outcome: {},
  by_tier: {},
  last_recorded_at: null,
  audit_sample: null,
};

const COST_AVAILABLE = {
  available: true,
  enabled: true,
  access_allowed: true,
  availability_reasons: [],
  reason: null,
  activation_revision: 1,
  package_version: "1.0.0",
  image_digest: null,
  asset_manifest_digest: null,
  semantic_profile_digest: null,
  ontology_release_digest: null,
} as const;

const COST_UNAVAILABLE = {
  ...COST_AVAILABLE,
  available: false,
  enabled: false,
  availability_reasons: ["package_absent"],
  activation_revision: null,
  package_version: null,
} as const;

describe("loadDashboardOverview", () => {
  it("publishes the KPI backbone before optional projections settle", async () => {
    const pending = new Promise<never>(() => undefined);
    const publishBackbone = vi.fn();
    const panelCall = vi.fn();
    const client = {
      dashboardMetrics: vi.fn(async () => KPI),
      costGovernanceAvailability: vi.fn(async () => COST_AVAILABLE),
      costGovernance: vi.fn(() => pending),
      panel<T>(path: string): Promise<T> {
        panelCall(path);
        return pending;
      },
      autonomy: vi.fn(() => pending),
    };

    void loadDashboardOverview(client, publishBackbone);

    await vi.waitFor(() => {
      expect(publishBackbone).toHaveBeenCalledWith({
        kpi: KPI,
        cost: null,
        gates: null,
        autonomy: null,
        optionalPending: true,
      });
    });
    expect(client.costGovernance).toHaveBeenCalledWith("overview");
    expect(panelCall).toHaveBeenCalledOnce();
    expect(client.autonomy).toHaveBeenCalledOnce();
  });

  it("keeps the KPI backbone when the source registry refuses an unserved route", async () => {
    // The registry reports an unavailable source as 503 before any request is
    // sent, so every optional overview projection must tolerate that status.
    const publishBackbone = vi.fn();
    const client = {
      dashboardMetrics: vi.fn(async () => KPI),
      costGovernanceAvailability: vi.fn(async () => COST_AVAILABLE),
      costGovernance: vi.fn(async () => {
        throw new OperatorApiError(503, "not served here", "projection-unavailable");
      }),
      panel: vi.fn(async () => {
        throw new OperatorApiError(503, "not served here", "projection-unavailable");
      }),
      autonomy: vi.fn(async () => {
        throw new OperatorApiError(503, "not served here", "projection-unavailable");
      }),
    };

    await expect(loadDashboardOverview(client, publishBackbone)).resolves.toEqual({
      kpi: KPI,
      cost: null,
      gates: null,
      autonomy: null,
    });
  });

  it("keeps the KPI backbone when optional cost access and promotion data are unavailable", async () => {
    const publishBackbone = vi.fn();
    const client = {
      dashboardMetrics: vi.fn(async () => KPI),
      costGovernanceAvailability: vi.fn(async () => {
        throw new OperatorApiError(403, "access required");
      }),
      costGovernance: vi.fn(),
      panel: vi.fn(async () => {
        throw new OperatorApiError(503, "unavailable", "projection-unavailable");
      }),
      autonomy: vi.fn(async () => { throw new OperatorApiError(404, "not found"); }),
    };

    await expect(loadDashboardOverview(client, publishBackbone)).resolves.toEqual({
      kpi: KPI,
      cost: null,
      gates: null,
      autonomy: null,
    });
    expect(client.costGovernance).not.toHaveBeenCalled();
  });

  it("does not request a cost projection when the package is unavailable", async () => {
    const client = {
      dashboardMetrics: vi.fn(async () => KPI),
      costGovernanceAvailability: vi.fn(async () => COST_UNAVAILABLE),
      costGovernance: vi.fn(),
      panel: vi.fn(async () => { throw new OperatorApiError(404, "not found"); }),
      autonomy: vi.fn(async () => { throw new OperatorApiError(404, "not found"); }),
    };

    await expect(loadDashboardOverview(client, vi.fn())).resolves.toEqual({
      kpi: KPI,
      cost: null,
      gates: null,
      autonomy: null,
    });
    expect(client.costGovernanceAvailability).toHaveBeenCalledOnce();
    expect(client.costGovernance).not.toHaveBeenCalled();
  });

  it("surfaces decoder failures from an optional projection", async () => {
    const decodeFailure = new OperatorApiError(
      502,
      "invalid Operator API response: autonomy measurement is inconsistent",
    );
    const client = {
      dashboardMetrics: vi.fn(async () => KPI),
      costGovernanceAvailability: vi.fn(async () => COST_AVAILABLE),
      costGovernance: vi.fn(async () => {
        throw new OperatorApiError(404, "not found");
      }),
      panel: vi.fn(async () => {
        throw new OperatorApiError(404, "not found");
      }),
      autonomy: vi.fn(async () => {
        throw decodeFailure;
      }),
    };

    await expect(loadDashboardOverview(client, vi.fn())).rejects.toBe(decodeFailure);
  });

  it("surfaces an unclassified service unavailable response", async () => {
    const serviceFailure = new OperatorApiError(503, "upstream service unavailable");
    const client = {
      dashboardMetrics: vi.fn(async () => KPI),
      costGovernanceAvailability: vi.fn(async () => COST_AVAILABLE),
      costGovernance: vi.fn(async () => {
        throw serviceFailure;
      }),
      panel: vi.fn(async () => {
        throw new OperatorApiError(404, "not found");
      }),
      autonomy: vi.fn(async () => {
        throw new OperatorApiError(404, "not found");
      }),
    };

    await expect(loadDashboardOverview(client, vi.fn())).rejects.toBe(serviceFailure);
  });
});

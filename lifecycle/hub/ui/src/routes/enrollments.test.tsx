import { describe, expect, it } from "vitest";
import { EnrollmentsPage, filterAndSortEnrollments } from "./enrollments";
import { filterAndSortInstallations } from "./installations";

describe("enrollment detail identity", () => {
  it("remounts request data and decision inputs together when the target changes", () => {
    const alpha = EnrollmentsPage({ selectedId: "alpha" });
    const beta = EnrollmentsPage({ selectedId: "beta" });

    expect(alpha.key).toBe("alpha");
    expect(beta.key).toBe("beta");
  });

  it("trims search filters and breaks enrollment ties deterministically by request_id", () => {
    const sorted = filterAndSortEnrollments(
      [
        {
          installation_id: "inst-b",
          requested_at: "2026-11-01T00:00:00Z",
          request_id: "req-2",
        },
        {
          installation_id: "inst-a",
          requested_at: "2026-11-01T00:00:00Z",
          request_id: "req-1",
        },
      ],
      "  inst-  ",
    );
    expect(sorted.map((item) => item.request_id)).toEqual(["req-1", "req-2"]);

    const instFiltered = filterAndSortInstallations(
      [
        {
          installation_id: "prod-korea-1",
          channel: "stable",
          version_range: ">=1.0.0",
          current_release: "1.0.0",
          target_release_id: null,
          outcome: "up-to-date",
          health: "healthy",
          next_window_starts_at: null,
          next_window_ends_at: null,
          next_window_open: false,
          last_evaluated_at: null,
        },
      ],
      "  PROD-KOREA  ",
    );
    expect(instFiltered).toHaveLength(1);
  });
});

import { readFileSync } from "node:fs";

import { describe, expect, test } from "vitest";

const source = readFileSync(new URL("./dashboard-v2.tsx", import.meta.url), "utf8");

describe("Dashboard v2 refresh presentation", () => {
  test("keeps the completed view while an explicit refresh reports progress", () => {
    expect(source).toContain("const [refreshInFlight, setRefreshInFlight]");
    expect(source).toContain('disabled={state.status === "loading" || refreshInFlight}');
    expect(source).toContain('role="status">{t("refreshing")}');
    expect(source).toContain("<DashboardBody snapshot={snapshot} />");
    expect(source).not.toContain("<DashboardBody key={revision}");
    expect(source).toContain('if (!hasServing && lens === "serving")');
    expect(source).toContain("intervalMs: DASHBOARD_V2_REFRESH_INTERVAL_MS");
    expect(source).toContain("DASHBOARD_V2_REFRESH_INTERVAL_MS = 300_000");
    expect(source).toContain("enabled: streamSnapshot !== null");
    expect(source).toContain("String(streamSnapshot.invalidationWatermark)");
  });
});

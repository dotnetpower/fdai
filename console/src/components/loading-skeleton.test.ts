import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8");
}

describe("console loading skeleton contract", () => {
  test("uses a shared animated skeleton instead of spinner-only loading", () => {
    const ui = source("./ui.tsx");
    const app = source("../app.tsx");
    const styles = source("../styles.css");

    expect(ui).toContain("readonly loading?: ComponentChildren");
    expect(ui).toContain('class="loading-skeleton"');
    expect(ui).toContain('aria-busy="true"');
    expect(ui).not.toContain("state-spinner");
    expect(app).toContain('class="skeleton-shimmer"');
    expect(app).toContain('aria-busy="true"');
    expect(styles).toContain("@keyframes skeleton-shimmer");
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
    expect(styles).not.toContain("@keyframes state-spin");
  });

  test("gives Dashboard a route-owned structural skeleton", () => {
    const dashboard = source("../routes/dashboard.tsx");
    const skeleton = source("../routes/dashboard.skeleton.tsx");

    expect(dashboard).toContain("loading={<DashboardSkeleton />}");
    expect(skeleton).toContain('class="overview-skeleton"');
    expect(skeleton).toContain('layout="metrics" blocks={4}');
    expect(skeleton).toContain('layout="distributions" blocks={2}');
    expect(skeleton).toContain('layout="attention" blocks={3}');
    expect(skeleton).not.toContain('layout="verticals"');
    expect(skeleton).toContain('role="status"');
    expect(skeleton).toContain('aria-busy="true"');
  });
});

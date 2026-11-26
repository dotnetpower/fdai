import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { COMPONENTS, filterReleases, RELEASE_EXAMPLES } from "./data";
import { filterRegisteredInstallations, recentlyReportedVersions, REGISTERED_INSTALLATIONS, reportFreshness } from "./installation-monitor.data";
import { EDITION_NODES } from "./edition-canvas";
import { EDITION_AREAS } from "./edition-sections";
import { releaseInstallationsPreviewPath, resolvePreview } from "../../../../hub/ui/src/design-previews/model";
import { buildConnectorGeometry, CARD_WIDTH } from "../release-lineage.geometry";

const source = (relative: string) => readFileSync(new URL(relative, import.meta.url), "utf8");
describe("Release Hub isolated design collection", () => {
  it("draws the sample version lineage as four selectable nodes with three connected branches", () => {
    const ids = new Set(EDITION_NODES.map((node) => node.id));
    expect(EDITION_NODES).toHaveLength(4);
    expect(ids.size).toBe(4);
    expect([...ids].sort()).toEqual(RELEASE_EXAMPLES.records.map((item) => item.id).sort());
    const edges = EDITION_NODES.filter((node) => node.parent);
    expect(edges).toHaveLength(3);
    for (const node of edges) {
      const parent = EDITION_NODES.find((candidate) => candidate.id === node.parent);
      expect(parent).toBeDefined();
      expect(parent!.x + CARD_WIDTH).toBeLessThan(node.x);
      const connector = buildConnectorGeometry({
        startX: parent!.x + CARD_WIDTH, startY: parent!.y + 54,
        endX: node.x, endY: node.y + 54,
      });
      expect(connector.pathD).toContain("M ");
      expect(connector.arrowD).toContain("L ");
    }
    expect(EDITION_NODES.filter((node) => node.parent === "0.5.2")).toHaveLength(2);
  });
  it("offers only Edition and preserves the existing operational route", () => {
    expect(resolvePreview("release", "/design-previews/edition")).toEqual({ kind: "preview", hub: "release", design: "edition" });
    for (const retired of ["control", "atelier"]) {
      expect(resolvePreview("release", `/design-previews/${retired}`)).toEqual({ kind: "not-found" });
    }
    expect(resolvePreview("release", "/")).toEqual({ kind: "operational" });
    expect(resolvePreview("release", "/design-previews/atlas")).toEqual({ kind: "not-found" });
    expect(resolvePreview("release", releaseInstallationsPreviewPath)).toEqual({
      kind: "preview", hub: "release", design: "edition", page: "installations",
    });
    expect(resolvePreview("release", `${releaseInstallationsPreviewPath}/extra`)).toEqual({ kind: "not-found" });
    expect(resolvePreview("lifecycle", releaseInstallationsPreviewPath)).toEqual({ kind: "not-found" });
    expect(source("./entry.tsx")).toContain('await import("../main")');
    expect(source("../main.tsx")).toContain("initializeAuth(root)");
    expect(source("../../index.html")).toContain('id="app"');
  });

  it("keeps sample data out of the production API contract", () => {
    expect(RELEASE_EXAMPLES.mode).toBe("sample");
    expect(RELEASE_EXAMPLES.observedAt).toBeNull();
    expect(RELEASE_EXAMPLES.records.every((item) => !("signature" in item) && !("manifest" in item))).toBe(true);
    for (const path of ["./data.ts", "./previews.tsx", "./edition-sections.tsx", "./edition-canvas.tsx", "./installation-monitor.tsx"]) {
      expect(source(path)).not.toMatch(/authenticatedFetch|requestCatalog|from ["'][^"']*\/api["']|fetch\(/);
    }
  });

  it("covers the six operating-area entry points without offering a simulated write", () => {
    expect(EDITION_AREAS.map((item) => item.id)).toEqual([
      "stencils", "releases", "channels", "deployment-requests", "activity", "trust",
    ]);
    expect(source("../../../../hub/ui/src/design-previews/shell.tsx")).toContain("예시 데이터 · SAMPLE");
    expect(source("./edition-sections.tsx")).toContain("작업은 실행되지 않았습니다");
    expect(source("./edition-sections.tsx")).not.toContain("설치 요청의 맥락");
  });

  it("filters channel and version, including a reversible empty result", () => {
    expect(filterReleases("", "RELEASE").map((item) => item.id)).toEqual(["0.5.2", "0.5.1"]);
    expect(filterReleases("  0.5.3  ", "all")).toHaveLength(1);
    expect(filterReleases("not-found", "all")).toEqual([]);
    expect(filterReleases("", "all")).toHaveLength(4);
  });

  it("counts only recent reports from registered sample installations, not targets or missing reports", () => {
    const records = REGISTERED_INSTALLATIONS.records;
    expect(REGISTERED_INSTALLATIONS.mode).toBe("sample");
    expect(REGISTERED_INSTALLATIONS.observedAt).toBeNull();
    expect(records).toHaveLength(5);
    expect(records.map((item) => reportFreshness(item))).toEqual(["recent", "recent", "recent", "stale", "no-report"]);
    expect(recentlyReportedVersions()).toEqual([{ version: "0.5.2", count: 2 }, { version: "0.5.1", count: 1 }]);
    expect(filterRegisteredInstallations("", "recent")).toHaveLength(3);
    expect(filterRegisteredInstallations("", "stale").map((item) => item.id)).toEqual(["example-west"]);
    expect(filterRegisteredInstallations("0.5.4", "all").map((item) => item.id)).toEqual(["example-lab"]);
    expect(filterRegisteredInstallations("not-found", "all")).toEqual([]);
    expect(reportFreshness(records[2]!, "2026-11-05T07:30:01Z")).toBe("stale");
    expect(() => reportFreshness(records[0]!, "2026-11-05T07:00:00Z")).toThrow("Invalid example report time");
    expect(source("./installation-monitor.tsx")).toContain("등록하지 않은 설치의 수와 사용 버전은 알 수 없습니다");
  });

  it("retains eight distinct example component roles for the Stencil builder and release disclosure", () => {
    expect(COMPONENTS).toHaveLength(8);
    expect(new Set(COMPONENTS.map((part) => part.id)).size).toBe(8);
    expect(COMPONENTS.every((part) => part.name && part.role)).toBe(true);
  });

  it("keeps release node geometry and preserves components in a disclosure only", () => {
    const css = source("./edition-canvas.css");
    expect(css).toMatch(/\.dp-studio button\.dp-edition-node \{[^}]*width: 176px; height: 132px; padding: 10px 13px;[^}]*border: 1px solid/s);
    expect(css).not.toContain("button.dp-edition-component");
    expect(css).not.toMatch(/border-(?:top|left):\s*[2-9]\d*px/);
    expect(source("../../../../hub/ui/src/design-previews/studio.css")).toContain("prefers-reduced-motion: reduce");
    expect(source("../../../../hub/ui/src/design-previews/studio.css")).toContain(":focus-visible");
    expect(source("./previews.tsx")).toContain("구성 보기");
  });
});

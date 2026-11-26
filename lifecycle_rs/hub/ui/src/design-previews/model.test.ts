import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { DESIGNS, previewPath, releaseInstallationsPreviewPath, resolvePreview } from "./model";
import { filterInstallations, INSTALLATION_EXAMPLES, scheduledInstallations } from "./data";

const source = (relative: string) => readFileSync(new URL(relative, import.meta.url), "utf8");

describe("explicit preview routing boundary", () => {
  it("keeps the single Release Edition and three Lifecycle designs", () => {
    expect(DESIGNS.release).toHaveLength(1);
    expect(DESIGNS.lifecycle).toHaveLength(3);
    expect(new Set([...DESIGNS.release, ...DESIGNS.lifecycle].map((item) => item.id)).size).toBe(4);
    for (const item of DESIGNS.release) {
      expect(resolvePreview("release", previewPath("release", item.id))).toEqual({ kind: "preview", hub: "release", design: item.id });
    }
    for (const item of DESIGNS.lifecycle) {
      expect(resolvePreview("lifecycle", previewPath("lifecycle", item.id))).toEqual({ kind: "preview", hub: "lifecycle", design: item.id });
    }
  });

  it("does not infer a default preview or silently cross Hub boundaries", () => {
    for (const path of ["/design-previews", "/design-previews/", "/design-previews/unknown", "/design-previews/atlas/extra", "/design-previews/%61tlas", "/design-previews/ATLAS"]) {
      expect(resolvePreview("lifecycle", path)).toEqual({ kind: "not-found" });
    }
    expect(resolvePreview("release", "/design-previews/atlas")).toEqual({ kind: "not-found" });
    expect(resolvePreview("lifecycle", "/design-previews/edition")).toEqual({ kind: "not-found" });
    expect(resolvePreview("release", "/design-previews/control")).toEqual({ kind: "not-found" });
    expect(resolvePreview("release", "/design-previews/atelier")).toEqual({ kind: "not-found" });
    expect(resolvePreview("release", releaseInstallationsPreviewPath)).toEqual({
      kind: "preview", hub: "release", design: "edition", page: "installations",
    });
    expect(resolvePreview("lifecycle", releaseInstallationsPreviewPath)).toEqual({ kind: "not-found" });
    expect(resolvePreview("release", `${releaseInstallationsPreviewPath}/extra`)).toEqual({ kind: "not-found" });
  });

  it("leaves all existing live path and hash routing to the existing entry", () => {
    for (const hub of ["release", "lifecycle"] as const) {
      for (const path of ["/", "/installations", "/updates", "/catalog", "/enrollments/example", "/design-previews-other"]) {
        expect(resolvePreview(hub, path)).toEqual({ kind: "operational" });
      }
    }
  });

  it("retains original authentication and isolates production CSS from sample views", () => {
    expect(source("./entry.tsx")).toContain('await import("../main")');
    expect(source("./entry.tsx")).toContain('await import("../styles.css")');
    expect(source("../main.tsx")).toContain("initializeAuth(root)");
    for (const path of ["./data.ts", "./previews.tsx", "./shell.tsx"]) {
      expect(source(path)).not.toMatch(/authenticatedFetch|requestCatalog|from ["'][^"']*\/api["']|fetch\(/);
    }
    expect(source("../../index.html")).toContain('id="app"');
    expect(source("../../index.html")).not.toContain('href="/src/styles.css"');
  });
});

describe("installation presentation fixtures", () => {
  it("never represents fixtures as observed operational evidence", () => {
    expect(INSTALLATION_EXAMPLES.mode).toBe("sample");
    expect(INSTALLATION_EXAMPLES.observedAt).toBeNull();
    expect(INSTALLATION_EXAMPLES.records.every((item) => item.id.startsWith("example-"))).toBe(true);
    expect(INSTALLATION_EXAMPLES.records.find((item) => item.status === "unknown")?.currentRelease).toBeNull();
  });

  it("filters Korean labels, missing evidence and empty results without mutating fixtures", () => {
    expect(filterInstallations("사전 검증", "all").map((item) => item.id)).toEqual(["example-canary"]);
    expect(filterInstallations("", "attention")).toHaveLength(3);
    expect(filterInstallations("", "unknown").map((item) => item.id)).toEqual(["example-offline"]);
    expect(filterInstallations("not-a-record", "all")).toEqual([]);
    expect(filterInstallations("", "all")).toHaveLength(4);
  });

  it("switches fixed schedule days without scheduling missing reports", () => {
    expect(scheduledInstallations("first").map((item) => item.id)).toEqual(["example-north", "example-canary"]);
    expect(scheduledInstallations("next").map((item) => item.id)).toEqual(["example-west"]);
  });
});

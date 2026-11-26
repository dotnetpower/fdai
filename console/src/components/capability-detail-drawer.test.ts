import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { CapabilityDetailDrawer } from "./capability-detail-drawer";

const REPO_ROOT = fileURLToPath(new URL("../../../", import.meta.url));

describe("CapabilityDetailDrawer", () => {
  test("renders heading, identifier, state badges, facts, links, and close button without accent bars", () => {
    const rendered = JSON.stringify(
      CapabilityDetailDrawer({
        id: "capability-detail",
        heading: "Inventory Evidence",
        kicker: "publisher.example / v1.0.0",
        identifier: "cap.inventory.read",
        copyIdentifierLabel: "Copy ID",
        summary: "Read-only inventory snapshot lookup.",
        statusTone: "live",
        statusLabel: "Eligible",
        onClose: () => {},
        closeLabel: "Close",
        stateGridLabel: "Capability states",
        stateBadges: [
          { label: "Declaration", tone: "live", value: "Declared" },
          { label: "Runtime", tone: "neutral", value: "Not measured" },
          { label: "Execution", tone: "neutral", value: "Not granted" },
        ],
        facts: [
          { label: "Category", value: "inventory" },
          { label: "Required role", value: "Reader" },
        ],
        links: [
          { href: "/settings/iam", label: "Open access" },
        ],
      }),
    );

    expect(rendered).toContain('"id":"capability-detail"');
    expect(rendered).toContain("Inventory Evidence");
    expect(rendered).toContain("cap.inventory.read");
    expect(rendered).toContain("Not measured");
    expect(rendered).toContain("Not granted");
    expect(rendered).toContain("/settings/iam");
  });

  test("enforces >= 12px typography floor and prohibits colored left/top accent bars", () => {
    const css = readFileSync(`${REPO_ROOT}console/src/components/capability-detail-drawer.css`, "utf8");
    const pxUnder12 = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px\b/g)]
      .filter((match) => Number.parseFloat(match[1] ?? "12") < 12);
    const remUnder12 = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)rem\b/g)]
      .filter((match) => Number.parseFloat(match[1] ?? "0.75") < 0.75);
    expect(pxUnder12).toEqual([]);
    expect(remUnder12).toEqual([]);
    expect(css).not.toMatch(/border-(left|top):\s*[2-9]px\s+solid/);
  });
});

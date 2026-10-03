import { describe, expect, it } from "vitest";
import { leaveHref, leaveScreenLabel, type LeaveClick } from "./leave-consent";

const BASE = "https://console.example.test/overview?view=summary";
const ORIGIN = "https://console.example.test";

function click(overrides: Partial<LeaveClick>): LeaveClick {
  return { button: 0, modified: false, href: "/incidents", target: "", download: false, ...overrides };
}

describe("deck navigation consent", () => {
  it("asks before a primary click opens another screen", () => {
    expect(leaveHref(click({}), BASE)).toBe(`${ORIGIN}/incidents`);
    expect(leaveHref(click({ href: "/conversation-assurance?turn=turn+1" }), BASE)).toBe(
      `${ORIGIN}/conversation-assurance?turn=turn+1`,
    );
    expect(leaveHref(click({ href: "https://learn.example.test/doc" }), BASE)).toBe(
      "https://learn.example.test/doc",
    );
  });

  it("lets in-page anchors, new-tab or modified clicks, and downloads pass", () => {
    expect(leaveHref(click({ href: "#sources" }), BASE)).toBeNull();
    expect(leaveHref(click({ href: "/overview?view=summary#sources" }), BASE)).toBeNull();
    expect(leaveHref(click({ target: "_blank" }), BASE)).toBeNull();
    expect(leaveHref(click({ modified: true }), BASE)).toBeNull();
    expect(leaveHref(click({ button: 1 }), BASE)).toBeNull();
    expect(leaveHref(click({ download: true }), BASE)).toBeNull();
    expect(leaveHref(click({ href: null }), BASE)).toBeNull();
    expect(leaveHref(click({ href: "  " }), BASE)).toBeNull();
    expect(leaveHref(click({ href: "mailto:oncall@example.test" }), BASE)).toBeNull();
  });

  it("names the destination by its Console panel, path, or host", () => {
    const label = (panelId: string) => `panel:${panelId}`;

    expect(leaveScreenLabel(`${ORIGIN}/incidents`, ORIGIN, label)).toBe("panel:incidents");
    expect(leaveScreenLabel(`${ORIGIN}/settings/diagnostics`, ORIGIN, label)).toBe(
      "panel:settings-diagnostics",
    );
    expect(leaveScreenLabel(`${ORIGIN}/not-a-console-route`, ORIGIN, label)).toBe(
      "/not-a-console-route",
    );
    expect(leaveScreenLabel("https://learn.example.test/doc", ORIGIN, label)).toBe(
      "learn.example.test",
    );
  });
});

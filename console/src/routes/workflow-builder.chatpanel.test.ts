import { describe, expect, it } from "vitest";
import { displayInput, type Message } from "./workflow-builder.chatpanel";

/** displayInput is the only DOM-free view helper in the chat panel: it maps
 * the raw value a bubble was sent with back to what the operator should see -
 * a clicked chip's human label, a seed example's text, or free text verbatim.
 * The console has no component-render harness by design, so we test the pure
 * mapping directly. */
describe("workflow-builder chat displayInput", () => {
  const botWithChips: Message = {
    id: 1,
    role: "bot",
    text: "pick one",
    options: [
      { label: "Right-size", value: "action:remediate.right-size" },
      { label: "Every week (schedule)", value: "trigger:cron:0 3 * * 0" },
    ],
  };

  it("echoes a clicked chip's human label, not its machine value", () => {
    expect(displayInput("action:remediate.right-size", [botWithChips])).toBe("Right-size");
    expect(displayInput("trigger:cron:0 3 * * 0", [botWithChips])).toBe("Every week (schedule)");
  });

  it("strips the seed: prefix from an example click", () => {
    expect(displayInput("seed:When cost spikes, alert me", [botWithChips])).toBe(
      "When cost spikes, alert me",
    );
  });

  it("shows free text verbatim when it is not a known chip", () => {
    expect(displayInput("restart the service", [botWithChips])).toBe("restart the service");
  });

  it("matches the chip from the most recent bot turn only", () => {
    const older: Message = {
      id: 0,
      role: "bot",
      text: "old",
      options: [{ label: "Old label", value: "action:remediate.right-size" }],
    };
    const newer: Message = {
      id: 2,
      role: "bot",
      text: "new",
      options: [{ label: "New label", value: "action:remediate.right-size" }],
    };
    expect(displayInput("action:remediate.right-size", [older, newer])).toBe("New label");
  });

  it("falls back to verbatim when there is no bot message", () => {
    expect(displayInput("anything", [])).toBe("anything");
  });
});

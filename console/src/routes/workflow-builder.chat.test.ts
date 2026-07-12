import { describe, expect, it } from "vitest";
import type { ActionTypePaletteEntry } from "../workflow/validate";
import { KNOWN_SIGNAL_VALUES } from "./workflow-builder.model";
import {
  extractResourceHint,
  respondToChat,
  slugifyName,
  startChat,
  type ChatSlots,
} from "./workflow-builder.chat";

/** Minimal palette whose leaf names line up with the intent matcher's
 * synonym table so the deterministic parser can resolve them. */
function entry(
  name: string,
  category: string,
  description = name,
): ActionTypePaletteEntry {
  return {
    name,
    operation: "apply",
    category,
    rollback_contract: "pr_revert",
    irreversible: false,
    default_mode: "shadow",
    execution_path: "pr_native",
    env_scope: "any",
    hil_tiers: [],
    description,
  };
}

const PALETTE: readonly ActionTypePaletteEntry[] = [
  entry("remediate.right-size", "remediation", "Right-size an over-provisioned resource"),
  entry("notify.publish-change-summary", "tool", "Post a change summary"),
  entry("ops.scale-out", "ops", "Scale a workload out"),
  entry("remediate.restart-service", "ops", "Restart a service"),
];

function findValues(options: readonly { value: string }[]): string[] {
  return options.map((o) => o.value);
}

describe("workflow-builder chat engine", () => {
  it("opens with a welcome, examples, and no ready draft", () => {
    const turn = startChat(PALETTE);
    expect(turn.draftReady).toBe(false);
    expect(turn.text.toLowerCase()).toContain("design a workflow");
    expect(turn.options.length).toBeGreaterThanOrEqual(3);
    expect(turn.options.every((o) => o.value.startsWith("seed:"))).toBe(true);
    expect(turn.slots.stage).toBe("welcome");
  });

  it("warns and offers nothing when the palette is empty", () => {
    const turn = startChat([]);
    expect(turn.options).toHaveLength(0);
    expect(turn.text).toContain("workflow_authoring");
  });

  it("reads a full sentence: trigger + two actions -> offers an extra step", () => {
    const start = startChat(PALETTE);
    const turn = respondToChat(
      start.slots,
      "When cost spikes, right-size the resource and post a summary",
      PALETTE,
    );
    // cost -> cost-anomaly trigger; right-size + summary actions matched.
    expect(turn.slots.triggerConfirmed).toBe(true);
    expect(turn.slots.actionsConfirmed).toBe(true);
    expect(turn.slots.form.signalType).toBe("object.cost-anomaly");
    const refs = turn.slots.form.steps.map((s) => s.action_type_ref);
    expect(refs).toContain("remediate.right-size");
    expect(refs).toContain("notify.publish-change-summary");
    // With trigger + actions settled, the next question offers extra steps.
    expect(turn.slots.stage).toBe("offer_extra");
    expect(findValues(turn.options)).toContain("done");
  });

  it("asks for a trigger when the sentence has an action but no clear signal", () => {
    const start = startChat(PALETTE);
    const turn = respondToChat(start.slots, "alert me and restart the service", PALETTE);
    expect(turn.slots.actionsConfirmed).toBe(true);
    expect(turn.slots.triggerConfirmed).toBe(false);
    expect(turn.slots.stage).toBe("need_trigger");
    // Trigger chips include an anomaly option and a weekly schedule.
    const vals = findValues(turn.options);
    expect(vals).toContain("trigger:object.anomaly");
    expect(vals.some((v) => v.startsWith("trigger:cron:"))).toBe(true);
  });

  it("accepts an explicit trigger pick and advances", () => {
    const start = startChat(PALETTE);
    const t1 = respondToChat(start.slots, "restart the service", PALETTE);
    expect(t1.slots.stage).toBe("need_trigger");
    const t2 = respondToChat(t1.slots, "trigger:object.anomaly", PALETTE);
    expect(t2.slots.triggerConfirmed).toBe(true);
    expect(t2.slots.form.signalType).toBe("object.anomaly");
    expect(t2.slots.stage).toBe("offer_extra");
  });

  it("walks to a ready draft through done + keep-name", () => {
    const start = startChat(PALETTE);
    const t1 = respondToChat(
      start.slots,
      "When cost spikes, right-size the resource",
      PALETTE,
    );
    const t2 = respondToChat(t1.slots, "done", PALETTE); // finish extras
    expect(t2.slots.stage).toBe("confirm_name");
    const t3 = respondToChat(t2.slots, "name:keep", PALETTE);
    expect(t3.draftReady).toBe(true);
    expect(t3.slots.stage).toBe("ready");
    expect(t3.slots.form.name.length).toBeGreaterThan(0);
    expect(t3.slots.form.description.length).toBeGreaterThan(0);
    // Refine + restart options are offered at the ready stage.
    const vals = findValues(t3.options);
    expect(vals).toContain("refine:extra");
    expect(vals).toContain("restart");
  });

  it("adds an extra action step when one is picked in offer_extra", () => {
    const start = startChat(PALETTE);
    const t1 = respondToChat(start.slots, "When cost spikes, right-size the resource", PALETTE);
    expect(t1.slots.stage).toBe("offer_extra");
    const t2 = respondToChat(t1.slots, "action:notify.publish-change-summary", PALETTE);
    const refs = t2.slots.form.steps.map((s) => s.action_type_ref);
    expect(refs).toContain("remediate.right-size");
    expect(refs).toContain("notify.publish-change-summary");
    expect(t2.slots.extraOffered).toBe(true);
  });

  it("restart returns a fresh welcome turn", () => {
    const start = startChat(PALETTE);
    const t1 = respondToChat(start.slots, "restart the service", PALETTE);
    const reset = respondToChat(t1.slots as ChatSlots, "restart", PALETTE);
    expect(reset.slots.stage).toBe("welcome");
    expect(reset.slots.form.steps.every((s) => s.action_type_ref === "")).toBe(true);
  });

  it("does not duplicate an action already in the draft", () => {
    const start = startChat(PALETTE);
    const t1 = respondToChat(start.slots, "restart the service", PALETTE);
    const t2 = respondToChat(t1.slots, "trigger:object.anomaly", PALETTE);
    const before = t2.slots.form.steps.length;
    const t3 = respondToChat(t2.slots, "action:remediate.restart-service", PALETTE);
    const refs = t3.slots.form.steps.map((s) => s.action_type_ref);
    expect(refs.filter((r) => r === "remediate.restart-service")).toHaveLength(1);
    expect(t3.slots.form.steps.length).toBe(before);
  });

  it("offers only known signal values (single source with the model catalog)", () => {
    const start = startChat(PALETTE);
    // Reach the need_trigger stage: pick an action first, no trigger yet.
    const t1 = respondToChat(start.slots, "action:remediate.restart-service", PALETTE);
    expect(t1.slots.stage).toBe("need_trigger");
    const triggerChips = t1.options.filter((o) => o.value.startsWith("trigger:"));
    expect(triggerChips.length).toBeGreaterThanOrEqual(5);
    for (const chip of triggerChips) {
      const sig = chip.value.slice("trigger:".length);
      if (sig.startsWith("cron:")) {
        expect(sig.slice("cron:".length)).toMatch(/^[\d*/, -]+$/);
      } else {
        expect(KNOWN_SIGNAL_VALUES.has(sig)).toBe(true);
      }
      // Every chip carries a human label, never a raw machine value.
      expect(chip.label).not.toBe(sig);
    }
  });

  it("a schedule chip sets a cron trigger, not a signal", () => {
    const start = startChat(PALETTE);
    const t1 = respondToChat(start.slots, "action:remediate.restart-service", PALETTE);
    const sched = t1.options.find((o) => o.value.includes("cron:"));
    expect(sched).toBeDefined();
    const t2 = respondToChat(t1.slots, sched!.value, PALETTE);
    expect(t2.slots.form.triggerKind).toBe("schedule");
    expect(t2.slots.form.schedule).toBe("0 3 * * 0");
  });
});

describe("chat engine pure utilities", () => {
  it("extractResourceHint pulls a resource-like token", () => {
    expect(extractResourceHint("a pod on aks-cluster-01 runs hot")).toBe("aks-cluster-01");
    expect(extractResourceHint("restart vm-1 now")).toBe("vm-1");
    expect(extractResourceHint("nothing here")).toBe("");
  });

  it("slugifyName produces a schema-legal name", () => {
    expect(slugifyName("Cost Aware Remediation!")).toBe("cost-aware-remediation");
    expect(slugifyName("  123 leading digits ")).toBe("leading-digits");
    expect(slugifyName("")).toBe("workflow");
  });

  it("slugifyName strips a trailing hyphen introduced by 80-char truncation", () => {
    // 79 legal chars then a separator: slice(0, 80) lands a hyphen on the last
    // char; result must not end in '-' (NAME_PATTERN).
    const long = "a".repeat(79) + " tail";
    const slug = slugifyName(long);
    expect(slug.length).toBeLessThanOrEqual(80);
    expect(slug.endsWith("-")).toBe(false);
    expect(/^[a-z][a-z0-9_.-]{0,79}$/.test(slug)).toBe(true);
  });

  it("extractResourceHint ignores model-family names", () => {
    expect(extractResourceHint("gpt-4 costs spiked")).toBe("");
    expect(extractResourceHint("claude-opus-4 is expensive")).toBe("");
    // a real resource in the same sentence still wins when it appears first
    expect(extractResourceHint("vm-2 running gpt-4")).toBe("vm-2");
  });
});

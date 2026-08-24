import { describe, expect, it } from "vitest";
import {
  buildModelBindingPolicy,
  modelBindingT2Conflict,
} from "./settings-model-binding-policy";
import type { ModelCapabilityView, ModelSettingsView } from "./settings-models.model";

const capabilities: readonly ModelCapabilityView[] = [
  capability("t1.embedding", "OpenAI", "text-embedding-3-small"),
  capability("t2.reasoner.primary", "OpenAI", "gpt-4o"),
  capability("t2.reasoner.secondary", "Anthropic", "claude-opus-4"),
];

const view = {
  capabilities,
  resolvedMetadata: { digest: "sha256:" + "a".repeat(64) },
  bindingPolicy: { environment: "staging" },
} as ModelSettingsView;

describe("model binding policy editor", () => {
  it("serializes every capability and preserves PTU without direct authority", () => {
    const policy = buildModelBindingPolicy(view, {
      "t1.embedding": {
        selectionMode: "auto",
        publisher: "OpenAI",
        family: "text-embedding-3-small",
        sku: "Standard",
        capacityValue: 1000,
      },
      "t2.reasoner.primary": {
        selectionMode: "pinned",
        publisher: "OpenAI",
        family: "gpt-4o",
        sku: "GlobalProvisionedManaged",
        capacityValue: 30,
      },
      "t2.reasoner.secondary": {
        selectionMode: "hil-only",
        publisher: "Anthropic",
        family: "claude-opus-4",
        sku: "Standard",
        capacityValue: 1000,
      },
    }, 4);

    expect(policy).toMatchObject({
      schema_version: "1.0.0",
      environment: "staging",
      revision: 4,
      expected_active_digest: "sha256:" + "a".repeat(64),
      capabilities: {
        "t1.embedding": { selection_mode: "auto" },
        "t2.reasoner.primary": {
          selection_mode: "pinned",
          sku: "GlobalProvisionedManaged",
          capacity: { unit: "ptu", value: 30 },
        },
        "t2.reasoner.secondary": { selection_mode: "hil-only" },
      },
    });
    expect(policy).not.toHaveProperty("execution_authority");
  });

  it("detects a same-publisher T2 pair but allows a human-review-only side", () => {
    const samePublisher = {
      "t2.reasoner.primary": {
        selectionMode: "pinned" as const,
        publisher: "OpenAI",
        family: "gpt-4o",
        sku: "Standard",
        capacityValue: 1000,
      },
      "t2.reasoner.secondary": {
        selectionMode: "pinned" as const,
        publisher: "OpenAI",
        family: "gpt-4.1",
        sku: "Standard",
        capacityValue: 1000,
      },
    };

    expect(modelBindingT2Conflict(capabilities, samePublisher)).not.toBeNull();
    expect(modelBindingT2Conflict(capabilities, {
      ...samePublisher,
      "t2.reasoner.secondary": {
        ...samePublisher["t2.reasoner.secondary"],
        selectionMode: "hil-only",
      },
    })).toBeNull();
  });

  it.each([0, 1.5, 10_000_001])("rejects invalid pinned capacity %s", (capacityValue) => {
    expect(() => buildModelBindingPolicy(view, {
      "t1.embedding": {
        selectionMode: "pinned",
        publisher: "OpenAI",
        family: "text-embedding-3-small",
        sku: "Standard",
        capacityValue,
      },
    }, 4)).toThrow("capacity");
  });
});

function capability(name: string, publisher: string, family: string): ModelCapabilityView {
  return {
    name,
    tier: name.startsWith("t1.") ? "T1" : "T2",
    publisher,
    family,
    version: null,
    sku: "Standard",
    selectionMode: "auto",
    status: "resolved",
    capacityTpm: 1000,
    capacityUnit: "tpm",
    capacityValue: 1000,
    invocation: "always",
    reasons: [],
  };
}

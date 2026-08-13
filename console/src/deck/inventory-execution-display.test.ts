import { describe, expect, it } from "vitest";
import { inventoryExecutionDisplay } from "./inventory-execution-display";

describe("inventoryExecutionDisplay", () => {
  it("separates canonical IQL from bounded provider commands and results", () => {
    const display = inventoryExecutionDisplay(JSON.stringify({
      query_language: "IQL",
      operation: "query_inventory",
      query: { source: "current" },
      provider_execution: {
        transport: "azure_cli",
        backend: "azure_resource_graph",
        executed: true,
        redacted: true,
        subscription_id: "subscription-example",
        page_count: 1,
        commands: [{
          label: "resources",
          language: "azure_cli",
          command: "az graph query --subscriptions subscription-example",
          result: {
            count: 1,
            preview: [{ name: "resource-example", type: "example/type" }],
            truncated: false,
          },
        }],
      },
    }));

    expect(JSON.parse(display?.iql ?? "{}")).toEqual({
      query_language: "IQL",
      operation: "query_inventory",
      query: { source: "current" },
    });
    expect(display?.provider).toEqual({
      backend: "azure_resource_graph",
      pageCount: 1,
      subscriptionId: "subscription-example",
      commands: [{
        label: "resources",
        language: "azure_cli",
        command: "az graph query --subscriptions subscription-example",
        result: {
          count: 1,
          preview: [{ name: "resource-example", type: "example/type" }],
          truncated: false,
        },
      }],
    });
  });

  it("does not invent provider execution for legacy or invalid receipts", () => {
    expect(inventoryExecutionDisplay('{"operation":"query_inventory"}')).toBeUndefined();
    const display = inventoryExecutionDisplay(JSON.stringify({
      query_language: "IQL",
      operation: "query_inventory",
      query: { source: "current" },
      provider_execution: {
        transport: "azure_cli",
        backend: "azure_resource_graph",
        executed: true,
        redacted: false,
        page_count: 1,
        commands: [],
      },
    }));
    expect(display?.provider).toBeUndefined();
  });

  it.each([
    "az resource list; env",
    "az resource list | grep secret",
    "az resource show --ids /subscriptions/hidden/resourceGroups/hidden",
    "az account get-access-token",
    "AZURE_CONFIG_DIR=/tmp az resource list",
    "az resource list < /tmp/input",
    "az resource list > /tmp/output",
    "source /tmp/profile",
    "az resource list\u0000hidden",
  ])("rejects unsafe provider command %s", (command) => {
    const display = inventoryExecutionDisplay(JSON.stringify({
      query_language: "IQL",
      operation: "query_inventory",
      query: { source: "current" },
      provider_execution: {
        transport: "azure_cli",
        backend: "azure_resource_manager",
        executed: true,
        redacted: true,
        page_count: 1,
        commands: [{ label: "resources", language: "azure_cli", command }],
      },
    }));

    expect(display?.provider).toBeUndefined();
  });
});

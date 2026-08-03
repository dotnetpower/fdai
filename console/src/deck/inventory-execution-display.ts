export interface InventoryProviderCommand {
  readonly label: "resource_groups" | "resources";
  readonly language: "azure_cli";
  readonly command: string;
}

export interface InventoryProviderExecution {
  readonly backend: "azure_resource_graph" | "azure_resource_manager";
  readonly pageCount: number;
  readonly commands: readonly InventoryProviderCommand[];
}

export interface InventoryExecutionDisplay {
  readonly iql: string;
  readonly provider?: InventoryProviderExecution;
}

export function inventoryExecutionDisplay(raw: string): InventoryExecutionDisplay | undefined {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return undefined;
  }
  if (!isRecord(value) || value.query_language !== "IQL" || value.operation !== "query_inventory") {
    return undefined;
  }
  const { provider_execution: providerExecution, ...iql } = value;
  const provider = parseProviderExecution(providerExecution);
  return {
    iql: JSON.stringify(iql, null, 2),
    ...(provider ? { provider } : {}),
  };
}

function parseProviderExecution(value: unknown): InventoryProviderExecution | undefined {
  if (
    !isRecord(value) ||
    value.transport !== "azure_cli" ||
    !["azure_resource_graph", "azure_resource_manager"].includes(String(value.backend)) ||
    value.executed !== true ||
    value.redacted !== true ||
    !Number.isInteger(value.page_count) ||
    Number(value.page_count) < 1 ||
    !Array.isArray(value.commands) ||
    value.commands.length < 1 ||
    value.commands.length > 4
  ) return undefined;
  const commands = value.commands.flatMap((candidate): InventoryProviderCommand[] => {
    if (
      !isRecord(candidate) ||
      !["resource_groups", "resources"].includes(String(candidate.label)) ||
      candidate.language !== "azure_cli" ||
      typeof candidate.command !== "string" ||
      candidate.command.length < 1 ||
      candidate.command.length > 4096 ||
      candidate.command.includes("\n")
    ) return [];
    return [{
      label: candidate.label as InventoryProviderCommand["label"],
      language: "azure_cli",
      command: candidate.command,
    }];
  });
  if (commands.length !== value.commands.length) return undefined;
  return {
    backend: value.backend as InventoryProviderExecution["backend"],
    pageCount: Number(value.page_count),
    commands,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

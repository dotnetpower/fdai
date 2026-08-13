export interface InventoryProviderCommand {
  readonly label: "resource_groups" | "resources";
  readonly language: "azure_cli";
  readonly command: string;
  readonly result?: InventoryProviderResult;
}

export interface InventoryProviderResult {
  readonly count: number;
  readonly preview: readonly Readonly<Record<string, string>>[];
  readonly truncated: boolean;
}

export interface InventoryProviderExecution {
  readonly backend: "azure_resource_graph" | "azure_resource_manager";
  readonly pageCount: number;
  readonly subscriptionId?: string;
  readonly commands: readonly InventoryProviderCommand[];
}

export interface InventoryExecutionDisplay {
  readonly iql: string;
  readonly provider?: InventoryProviderExecution;
}

const SENSITIVE_PROVIDER_TEXT = /((?:^|\s)\/subscriptions\/|access[_-]?token|authorization:|bearer\s|client[_-]?secret|password|\$skiptoken|continuation[_-]?token|provider[_-]?error)/i;
const SHELL_CONTROL = /[`$;&|]|\$\(/;
const GUID = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i;
const ENV_ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;

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
  const commands: InventoryProviderCommand[] = [];
  for (const candidate of value.commands) {
    if (
      !isRecord(candidate) ||
      !["resource_groups", "resources"].includes(String(candidate.label)) ||
      candidate.language !== "azure_cli" ||
      typeof candidate.command !== "string" ||
      candidate.command.length < 1 ||
      candidate.command.length > 4096 ||
      candidate.command.includes("\n") ||
      SENSITIVE_PROVIDER_TEXT.test(candidate.command) ||
      SHELL_CONTROL.test(candidate.command) ||
      GUID.test(candidate.command) ||
      ENV_ASSIGNMENT.test(candidate.command)
    ) return undefined;
    const result = candidate.result === undefined
      ? undefined
      : parseProviderResult(candidate.result);
    if (candidate.result !== undefined && result === undefined) return undefined;
    commands.push({
      label: candidate.label as InventoryProviderCommand["label"],
      language: "azure_cli",
      command: candidate.command,
      ...(result ? { result } : {}),
    });
  }
  const subscriptionId = value.subscription_id;
  if (subscriptionId !== undefined && (
    typeof subscriptionId !== "string" ||
    subscriptionId.length < 1 ||
    subscriptionId.length > 128 ||
    subscriptionId.includes("\n")
  )) return undefined;
  return {
    backend: value.backend as InventoryProviderExecution["backend"],
    pageCount: Number(value.page_count),
    ...(typeof subscriptionId === "string" ? { subscriptionId } : {}),
    commands,
  };
}

function parseProviderResult(value: unknown): InventoryProviderResult | undefined {
  if (!isRecord(value) ||
    !Number.isInteger(value.count) || Number(value.count) < 0 ||
    !Array.isArray(value.preview) || value.preview.length > Math.min(Number(value.count), 10) ||
    typeof value.truncated !== "boolean") return undefined;
  const allowed = new Set(["name", "type", "resource_group", "location", "status"]);
  const preview = value.preview.flatMap((candidate): Readonly<Record<string, string>>[] => {
    if (!isRecord(candidate) || Object.keys(candidate).some((key) => !allowed.has(key))) return [];
    const entries = Object.entries(candidate);
    if (entries.some(([, item]) =>
      typeof item !== "string" ||
      item.length < 1 ||
      item.length > 512 ||
      item.includes("\n") ||
      SENSITIVE_PROVIDER_TEXT.test(item) ||
      GUID.test(item)
    )) return [];
    return [Object.fromEntries(entries) as Readonly<Record<string, string>>];
  });
  if (preview.length !== value.preview.length || value.truncated !== (Number(value.count) > preview.length)) {
    return undefined;
  }
  return { count: Number(value.count), preview, truncated: value.truncated };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

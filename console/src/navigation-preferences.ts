import type { PanelGroup } from "./panels";

export interface NavigationPreferences {
  readonly explorerOpen: boolean;
  readonly hiddenPanelIds: readonly string[];
  readonly groupOrder: Readonly<Partial<Record<PanelGroup, readonly string[]>>>;
}

type StorageReader = Pick<Storage, "getItem">;
type StorageWriter = Pick<Storage, "setItem" | "removeItem">;

const STORAGE_PREFIX = "fdai:console:navigation:v1";

export const DEFAULT_NAVIGATION_PREFERENCES: NavigationPreferences = {
  explorerOpen: true,
  hiddenPanelIds: [],
  groupOrder: {},
};

export function navigationPreferenceKey(principalId: string | null | undefined): string {
  const namespace = principalId?.trim() || "local";
  return `${STORAGE_PREFIX}:${namespace}`;
}

export function readNavigationPreferences(
  panelIds: readonly string[],
  principalId?: string | null,
  storage: StorageReader | null = browserStorage(),
): NavigationPreferences {
  const validIds = new Set(panelIds);
  const parsed = parseStored(storage, navigationPreferenceKey(principalId));
  if (parsed === null) return DEFAULT_NAVIGATION_PREFERENCES;

  const hiddenPanelIds = stringArray(parsed.hiddenPanelIds).filter((id) => validIds.has(id));
  const groupOrder: Partial<Record<PanelGroup, readonly string[]>> = {};
  if (isRecord(parsed.groupOrder)) {
    for (const group of ["overview", "operations", "agents", "governance", "evidence", "labs"] as const) {
      const order = stringArray(parsed.groupOrder[group]).filter((id) => validIds.has(id));
      if (order.length > 0) groupOrder[group] = unique(order);
    }
  }

  return {
    explorerOpen: typeof parsed.explorerOpen === "boolean"
      ? parsed.explorerOpen
      : DEFAULT_NAVIGATION_PREFERENCES.explorerOpen,
    hiddenPanelIds: unique(hiddenPanelIds),
    groupOrder,
  };
}

export function writeNavigationPreferences(
  preferences: NavigationPreferences,
  principalId?: string | null,
  storage: StorageWriter | null = browserWritableStorage(),
): boolean {
  if (storage === null) return false;
  try {
    storage.setItem(navigationPreferenceKey(principalId), JSON.stringify(preferences));
    return true;
  } catch {
    return false;
  }
}

export function resetNavigationPreferences(
  principalId?: string | null,
  storage: StorageWriter | null = browserWritableStorage(),
): boolean {
  if (storage === null) return false;
  try {
    storage.removeItem(navigationPreferenceKey(principalId));
    return true;
  } catch {
    return false;
  }
}

function parseStored(storage: StorageReader | null, key: string): Record<string, unknown> | null {
  if (storage === null) return null;
  try {
    const raw = storage.getItem(key);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values)];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function browserStorage(): StorageReader | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function browserWritableStorage(): StorageWriter | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

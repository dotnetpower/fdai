import { ReadApiError } from "../api";

export function panelRecord(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw panelContractError(`${label} MUST be an object`);
  }
  return value as Readonly<Record<string, unknown>>;
}

export function panelArray(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) throw panelContractError(`${label} MUST be an array`);
  return value;
}

export function panelString(value: Readonly<Record<string, unknown>>, key: string, label: string): string {
  if (typeof value[key] !== "string") throw panelContractError(`${label}.${key} MUST be a string`);
  return value[key];
}

export function panelNonEmptyString(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string {
  const item = panelString(value, key, label);
  if (item.trim().length === 0) throw panelContractError(`${label}.${key} MUST NOT be empty`);
  return item;
}

export function panelNumber(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  if (typeof value[key] !== "number" || !Number.isFinite(value[key])) {
    throw panelContractError(`${label}.${key} MUST be a finite number`);
  }
  return value[key];
}

export function panelNonNegativeInteger(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number {
  const item = panelNumber(value, key, label);
  if (!Number.isInteger(item) || item < 0) {
    throw panelContractError(`${label}.${key} MUST be a non-negative integer`);
  }
  return item;
}

export function panelNonNegativeNumber(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number {
  const item = panelNumber(value, key, label);
  if (item < 0) throw panelContractError(`${label}.${key} MUST be non-negative`);
  return item;
}

export function panelRatio(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number {
  const item = panelNumber(value, key, label);
  if (item < 0 || item > 1) throw panelContractError(`${label}.${key} MUST be between 0 and 1`);
  return item;
}

export function panelBoolean(value: Readonly<Record<string, unknown>>, key: string, label: string): boolean {
  if (typeof value[key] !== "boolean") throw panelContractError(`${label}.${key} MUST be a boolean`);
  return value[key];
}

export function panelStringArray(value: unknown, label: string): readonly string[] {
  const items = panelArray(value, label);
  if (!items.every((item) => typeof item === "string")) {
    throw panelContractError(`${label} MUST contain only strings`);
  }
  return items;
}

export function panelNullableString(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  if (value[key] === null) return null;
  return panelString(value, key, label);
}

export function panelContractError(message: string): ReadApiError {
  return new ReadApiError(502, `invalid read API response: ${message}`);
}

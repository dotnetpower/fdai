import { ReadApiError } from "./api-transport";

export function contractError(message: string): ReadApiError {
  return new ReadApiError(502, `invalid read API response: ${message}`);
}

export function apiRecord(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw contractError(`${label} MUST be an object`);
  }
  return value as Readonly<Record<string, unknown>>;
}

export function apiString(value: Readonly<Record<string, unknown>>, key: string, label: string): string {
  if (typeof value[key] !== "string") throw contractError(`${label}.${key} MUST be a string`);
  return value[key];
}

export function apiNullableString(value: Readonly<Record<string, unknown>>, key: string, label: string): string | null {
  if (value[key] === null) return null;
  return apiString(value, key, label);
}

export function apiOptionalString(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string {
  return value[key] === undefined ? "" : apiString(value, key, label);
}

export function apiOptionalNullableString(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  return value[key] === undefined ? null : apiNullableString(value, key, label);
}

export function apiNumber(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  if (typeof value[key] !== "number" || !Number.isFinite(value[key])) {
    throw contractError(`${label}.${key} MUST be a finite number`);
  }
  return value[key];
}

export function apiNonNegativeInteger(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  const number = apiNumber(value, key, label);
  if (!Number.isInteger(number) || number < 0) {
    throw contractError(`${label}.${key} MUST be a non-negative integer`);
  }
  return number;
}

export function apiOptionalNullableNonNegativeInteger(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  if (value[key] === undefined || value[key] === null) return null;
  return apiNonNegativeInteger(value, key, label);
}

export function apiOptionalStringArray(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): readonly string[] {
  const items = value[key];
  if (items === undefined) return [];
  if (!Array.isArray(items) || items.some((item) => typeof item !== "string")) {
    throw contractError(`${label}.${key} MUST be an array of strings`);
  }
  return items;
}

export function apiPositiveInteger(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  const number = apiNonNegativeInteger(value, key, label);
  if (number < 1) throw contractError(`${label}.${key} MUST be a positive integer`);
  return number;
}

export function apiRatio(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  const number = apiNumber(value, key, label);
  if (number < 0 || number > 1) throw contractError(`${label}.${key} MUST be between 0 and 1`);
  return number;
}

export function apiNumberRecord(value: unknown, label: string): Record<string, number> {
  const raw = apiRecord(value, label);
  const result: Record<string, number> = {};
  for (const [key, item] of Object.entries(raw)) {
    if (typeof item !== "number" || !Number.isFinite(item) || !Number.isInteger(item) || item < 0) {
      throw contractError(`${label}.${key} MUST be a non-negative integer`);
    }
    result[key] = item;
  }
  return result;
}

export function apiMode(value: unknown): "shadow" | "enforce" {
  if (value === "shadow" || value === "enforce") return value;
  throw contractError("audit item.mode MUST be shadow or enforce");
}

export function apiBoolean(value: Readonly<Record<string, unknown>>, key: string, label: string): boolean {
  if (typeof value[key] !== "boolean") throw contractError(`${label}.${key} MUST be a boolean`);
  return value[key];
}

export function apiNullableRatio(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number | null {
  if (value[key] === null) return null;
  return apiRatio(value, key, label);
}

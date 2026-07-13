/**
 * Console i18n helper - L2 product-surface localization.
 *
 * Mirrors the CLI i18n contract (see cli/src/i18n) for the operator console:
 * - English (`messages.en.json`) is the source of truth.
 * - A locale catalog (`messages.ko.json`) MAY lag; a missing key falls back to
 *   the English source (mandatory English fallback), never a blank. A missing
 *   English key returns the key itself so a typo is visible.
 * - Keys are dot-paths into the nested catalog (e.g. `"route.dashboard"`).
 *
 * Locale is resolved once per page load. To keep the default experience
 * byte-identical to the pre-i18n console, English is the default and Korean is
 * opt-in via `?locale=ko` in the URL. Auto-detection from `navigator.language`
 * can be layered on later without changing call sites.
 */

import en from "./messages.en.json";
import ko from "./messages.ko.json";
import { readConsolePreferences } from "../preferences";

export type Locale = "en" | "ko";

type Catalog = Record<string, unknown>;

const CATALOGS: Record<Locale, Catalog> = { en, ko };

function detectLocale(): Locale {
  return readConsolePreferences().locale;
}

let current: Locale = detectLocale();

/** The locale resolved for this page load. */
export function getLocale(): Locale {
  return current;
}

/** Override the active locale (e.g. from a future locale switcher). */
export function setLocale(locale: Locale): void {
  current = locale;
}

function lookup(catalog: Catalog, key: string): string | undefined {
  let cursor: unknown = catalog;
  for (const part of key.split(".")) {
    if (typeof cursor !== "object" || cursor === null) return undefined;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return typeof cursor === "string" ? cursor : undefined;
}

/**
 * Translate `key` in the active locale. Falls back to the English source when
 * the locale catalog lacks the key, and to the key itself when even English is
 * missing. `params` substitute `{name}` placeholders; an unmatched placeholder
 * is left verbatim.
 */
export function t(key: string, params?: Record<string, string | number>): string {
  const template = lookup(CATALOGS[current], key) ?? lookup(CATALOGS.en, key) ?? key;
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

/**
 * CLI i18n helper - L2 product-surface localization.
 *
 * Implements the Product i18n rule in
 * `.github/instructions/language.instructions.md`:
 * - English is the source of truth (`messages.en.json`).
 * - A locale catalog (`messages.ko.json`) MAY lag; a missing key falls back
 *   to the English source (mandatory English fallback), never a blank.
 * - Locale resolution order: explicit preference -> `FDAI_LOCALE` env -> `en`.
 *
 * Keys are dot-paths into the nested catalog (e.g. `"tier.t0"`).
 */

import en from "./messages.en.json" with { type: "json" };
import ko from "./messages.ko.json" with { type: "json" };

export type Locale = "en" | "ko";

type Catalog = Record<string, unknown>;

const CATALOGS: Record<Locale, Catalog> = { en, ko };

/** Resolve a raw preference/env value to a supported locale (default `en`). */
export function resolveLocale(preference?: string): Locale {
  const raw = (preference ?? process.env.FDAI_LOCALE ?? "en").toLowerCase();
  return raw.startsWith("ko") ? "ko" : "en";
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
 * Translate `key` in `locale`. Falls back to the English source when the
 * locale catalog lacks the key, and to the key itself when even English is
 * missing (so a typo is visible rather than silently blank).
 *
 * `params` substitute `{name}` placeholders in the resolved string; an
 * unmatched placeholder is left verbatim (again, visible rather than blank).
 */
export function t(
  key: string,
  locale: Locale = "en",
  params?: Record<string, string | number>,
): string {
  const localized = lookup(CATALOGS[locale], key);
  const template = localized ?? lookup(CATALOGS.en, key) ?? key;
  if (params === undefined) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

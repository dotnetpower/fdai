/** Manual Studio locale resolution and English-fallback translation helpers. */

export const supportedLocales = Object.freeze(["en", "ko"]);

/** Return a supported primary locale, or null when the value is unsupported. */
export function normalizeLocale(value) {
  if (typeof value !== "string") return null;
  const primary = value.trim().toLowerCase().split("-")[0];
  return supportedLocales.includes(primary) ? primary : null;
}

/** Resolve URL preference, saved preference, browser languages, then English. */
export function resolveLocale({ url, storedLocale = null, browserLocales = [] }) {
  const requested = normalizeLocale(new URL(url).searchParams.get("locale"));
  if (requested !== null) return requested;

  const stored = normalizeLocale(storedLocale);
  if (stored !== null) return stored;

  for (const candidate of browserLocales) {
    const browserLocale = normalizeLocale(candidate);
    if (browserLocale !== null) return browserLocale;
  }
  return "en";
}

function lookup(catalog, key) {
  let cursor = catalog;
  for (const part of key.split(".")) {
    if (typeof cursor !== "object" || cursor === null) return undefined;
    cursor = cursor[part];
  }
  return typeof cursor === "string" && cursor.length > 0 ? cursor : undefined;
}

/** Create a translator that falls back to the English source catalog. */
export function createTranslator(catalogs, locale) {
  const activeLocale = normalizeLocale(locale) ?? "en";
  if (typeof catalogs?.en !== "object" || catalogs.en === null) {
    throw new TypeError("Manual Studio requires an English message catalog.");
  }

  return (key, params) => {
    const template = lookup(catalogs[activeLocale], key) ?? lookup(catalogs.en, key) ?? key;
    if (params === undefined) return template;
    return template.replace(/\{(\w+)\}/g, (whole, name) =>
      Object.hasOwn(params, name) ? String(params[name]) : whole,
    );
  };
}

/** Preserve the current route and state while selecting a supported locale. */
export function urlWithLocale(value, locale) {
  const normalized = normalizeLocale(locale);
  if (normalized === null) throw new TypeError(`Unsupported Manual Studio locale: ${locale}`);
  const url = new URL(value);
  url.searchParams.set("locale", normalized);
  return url;
}

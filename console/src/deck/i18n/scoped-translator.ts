import { getLocale, t as mainT } from "../../i18n";

type Catalog = Record<string, unknown>;
type Params = Record<string, string | number>;

/**
 * Builds a translator for a deck-only catalog that ships with the lazy Command Deck chunk instead
 * of the entry catalog. The catalog holds keys below `prefix`. Keys outside it resolve through the
 * main catalog, which keeps its English fallback. Like `t`, `params` substitute `{name}`
 * placeholders and an unmatched placeholder stays verbatim.
 */
export function scopedTranslator(
  catalogs: { readonly en: Catalog; readonly ko: Catalog },
  prefix: string,
): (key: string, params?: Params) => string {
  const lookup = (catalog: Catalog, key: string): string | undefined => {
    if (!key.startsWith(prefix)) return undefined;
    let cursor: unknown = catalog;
    for (const part of key.slice(prefix.length).split(".")) {
      if (typeof cursor !== "object" || cursor === null) return undefined;
      cursor = (cursor as Record<string, unknown>)[part];
    }
    return typeof cursor === "string" && cursor.length > 0 ? cursor : undefined;
  };
  return (key, params) => {
    const template = lookup(catalogs[getLocale()], key) ?? lookup(catalogs.en, key);
    if (template === undefined) return mainT(key, params);
    if (params === undefined) return template;
    return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
      name in params ? String(params[name]) : whole,
    );
  };
}

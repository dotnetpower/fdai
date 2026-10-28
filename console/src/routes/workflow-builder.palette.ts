/**
 * Workflow-builder ActionType search - a presentation-only filter over the
 * reviewed palette. It narrows the list the operator explicitly picks from;
 * it never infers meaning, ranks by intent, or selects an action itself.
 *
 * SRP: palette + query -> ordered matches. No preact, no DOM, no I/O.
 */

import type { ActionTypePaletteEntry } from "../workflow/validate";

/** Distinct, sorted ActionType categories for the category filter. */
export function paletteCategories(palette: readonly ActionTypePaletteEntry[]): string[] {
  return [...new Set(palette.map((entry) => entry.category ?? "other"))].sort();
}

/** Return palette entries whose name, category, or description contain every
 * whitespace-separated query token, in catalog name order. Entries listed in
 * `exclude` (already in the draft) are omitted. */
export function filterActionTypes(
  palette: readonly ActionTypePaletteEntry[],
  query: string,
  category: string,
  exclude: ReadonlySet<string> = new Set(),
): ActionTypePaletteEntry[] {
  const tokens = query.toLowerCase().split(/\s+/).filter((token) => token.length > 0);
  return palette
    .filter((entry) => !exclude.has(entry.name))
    .filter((entry) => category === "" || (entry.category ?? "other") === category)
    .filter((entry) => {
      if (tokens.length === 0) return true;
      const haystack = [entry.name, entry.category ?? "", entry.description ?? ""]
        .join(" ")
        .toLowerCase();
      return tokens.every((token) => haystack.includes(token));
    })
    .sort((left, right) => left.name.localeCompare(right.name));
}

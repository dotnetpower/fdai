/**
 * Intro suggestions - context-aware starter questions for the empty deck.
 *
 * Pure and DOM-free so it is unit-tested directly. Given the current
 * ``ViewSnapshot`` presence, it surfaces only starter questions whose typed
 * semantic contracts and server-owned evidence paths are implemented.
 */

import type { ViewSnapshot } from "./context";
import { tForLocale, type Locale } from "../i18n";

export function introSuggestions(
  _snapshot: ViewSnapshot | null,
  locale: Locale = "en",
): readonly string[] {
  return [
    tForLocale(locale, "deck.starterSuggestions.tierMix"),
    tForLocale(locale, "deck.starterSuggestions.screen"),
  ];
}

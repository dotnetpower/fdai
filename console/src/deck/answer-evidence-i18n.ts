import { getLocale } from "../i18n";
import en from "./i18n/answer-evidence.en.json";
import ko from "./i18n/answer-evidence.ko.json";

export type AnswerEvidenceTextKey = keyof typeof en;

/** Deck-only copy ships with the lazy Command Deck chunk instead of the entry catalog. */
export function answerEvidenceText(key: AnswerEvidenceTextKey): string {
  return (getLocale() === "ko" ? ko[key] : undefined) || en[key];
}

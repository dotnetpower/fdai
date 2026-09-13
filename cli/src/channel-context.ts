import type { Locale } from "./i18n/index.js";
import type { OperatorApiSession } from "./operator-api-session.js";
import type { TerminalCapabilities } from "./terminal-capabilities.js";
import type { BriefingPayload } from "./view-model/contract.js";

/** Presentation inputs available to the CLI channel. */
export interface CliChannelContext {
  apiUrl: string | null;
  payload: BriefingPayload | null;
  locale?: Locale;
  apiSession?: OperatorApiSession;
  terminal?: TerminalCapabilities;
}

/** Attach the locale key consumed by the shared L3 narrator. */
export function withChannelLocale(
  locale: Locale,
  snapshot: Record<string, unknown>,
): Record<string, unknown> {
  return { ...snapshot, _locale: locale };
}

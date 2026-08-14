import {
  type ConversationSearchContextPayload,
  type ConversationSearchHitPayload,
  type ConversationSearchPayload,
  UserContextRequestError,
} from "../user-context-client";

export type SearchMode = "terms" | "phrase" | "prefix";
export type SearchRole = "" | "operator" | "assistant" | "tool" | "system";

export interface SearchForm {
  readonly query: string;
  readonly mode: SearchMode;
  readonly channel: string;
  readonly role: SearchRole;
  readonly conversationId: string;
  readonly incidentId: string;
  readonly after: string;
  readonly before: string;
}

export const EMPTY_FORM: SearchForm = {
  query: "",
  mode: "terms",
  channel: "",
  role: "",
  conversationId: "",
  incidentId: "",
  after: "",
  before: "",
};

export type ConversationSearchViewStatus =
  | "idle"
  | "loading"
  | "empty"
  | "results"
  | "unavailable"
  | "error";

export interface HighlightSegment {
  readonly text: string;
  readonly highlighted: boolean;
}

export function conversationSearchInput(form: SearchForm) {
  return {
    query: form.query.trim(),
    mode: form.mode,
    ...(form.channel.trim() ? { channel: form.channel.trim() } : {}),
    ...(form.role ? { role: form.role } : {}),
    ...(form.conversationId.trim() ? { conversationId: form.conversationId.trim() } : {}),
    ...(form.incidentId.trim() ? { incidentId: form.incidentId.trim() } : {}),
    ...(form.after ? { recordedAfter: new Date(form.after).toISOString() } : {}),
    ...(form.before ? { recordedBefore: new Date(form.before).toISOString() } : {}),
  };
}

export function conversationSearchViewStatus(
  loading: boolean,
  error: unknown,
  result: ConversationSearchPayload | null,
): ConversationSearchViewStatus {
  if (loading) return "loading";
  if (
    error instanceof UserContextRequestError
    && (error.status === 404 || error.status === 501 || error.status === 503)
  ) return "unavailable";
  if (error !== null) return "error";
  if (result === null) return "idle";
  return result.hits.length === 0 ? "empty" : "results";
}

export function conversationSearchFailureMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function toggleConversationSearchContext(
  contexts: Readonly<Record<string, ConversationSearchContextPayload>>,
  resultId: string,
  context: ConversationSearchContextPayload | null,
): Readonly<Record<string, ConversationSearchContextPayload>> {
  if (context === null) {
    const next = { ...contexts };
    delete next[resultId];
    return next;
  }
  return { ...contexts, [resultId]: context };
}

export function conversationSearchHighlightSegments(
  hit: ConversationSearchHitPayload,
): readonly HighlightSegment[] {
  const ranges = hit.snippet.highlights;
  if (ranges.length === 0) return [{ text: hit.snippet.text, highlighted: false }];
  const parts: HighlightSegment[] = [];
  let cursor = 0;
  for (const range of ranges) {
    if (range.start < cursor || range.end <= range.start || range.end > hit.snippet.text.length) {
      return [{ text: hit.snippet.text, highlighted: false }];
    }
    if (range.start > cursor) {
      parts.push({ text: hit.snippet.text.slice(cursor, range.start), highlighted: false });
    }
    parts.push({ text: hit.snippet.text.slice(range.start, range.end), highlighted: true });
    cursor = range.end;
  }
  if (cursor < hit.snippet.text.length) {
    parts.push({ text: hit.snippet.text.slice(cursor), highlighted: false });
  }
  return parts;
}

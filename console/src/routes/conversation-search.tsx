import type { JSX } from "preact";
import { useState } from "preact/hooks";
import type { PanelProps } from "../panels";
import { t } from "../i18n";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import {
  fetchConversationSearchContext,
  searchConversations,
  type ConversationSearchContextPayload,
  type ConversationSearchHitPayload,
  type ConversationSearchPayload,
} from "../user-context-client";

type SearchMode = "terms" | "phrase" | "prefix";
type SearchRole = "" | "operator" | "assistant" | "tool" | "system";

interface SearchForm {
  readonly query: string;
  readonly mode: SearchMode;
  readonly channel: string;
  readonly role: SearchRole;
  readonly conversationId: string;
  readonly incidentId: string;
  readonly after: string;
  readonly before: string;
}

const EMPTY_FORM: SearchForm = {
  query: "",
  mode: "terms",
  channel: "",
  role: "",
  conversationId: "",
  incidentId: "",
  after: "",
  before: "",
};

export function ConversationSearchRoute(_props: PanelProps) {
  const [form, setForm] = useState<SearchForm>(EMPTY_FORM);
  const [result, setResult] = useState<ConversationSearchPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contexts, setContexts] = useState<Readonly<Record<string, ConversationSearchContextPayload>>>({});
  const [contextLoading, setContextLoading] = useState<string | null>(null);

  async function submit(event: JSX.TargetedSubmitEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setContexts({});
    try {
      setResult(await searchConversations({
        query: form.query.trim(),
        mode: form.mode,
        ...(form.channel.trim() ? { channel: form.channel.trim() } : {}),
        ...(form.role ? { role: form.role } : {}),
        ...(form.conversationId.trim() ? { conversationId: form.conversationId.trim() } : {}),
        ...(form.incidentId.trim() ? { incidentId: form.incidentId.trim() } : {}),
        ...(form.after ? { recordedAfter: new Date(form.after).toISOString() } : {}),
        ...(form.before ? { recordedBefore: new Date(form.before).toISOString() } : {}),
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadContext(hit: ConversationSearchHitPayload): Promise<void> {
    if (contexts[hit.result_id]) {
      const next = { ...contexts };
      delete next[hit.result_id];
      setContexts(next);
      return;
    }
    setContextLoading(hit.result_id);
    try {
      const context = await fetchConversationSearchContext(hit.result_id, 1, 1);
      setContexts((current) => ({ ...current, [hit.result_id]: context }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setContextLoading(null);
    }
  }

  return (
    <div class="stack conversation-search-view">
      <PageHeader
        title={t("conversationSearch.title")}
        subtitle={t("conversationSearch.subtitle")}
      />
      <form class="conversation-search-form" onSubmit={(event) => void submit(event)}>
        <label class="conversation-search-query">
          <span>{t("conversationSearch.query")}</span>
          <input
            type="search"
            required
            maxLength={256}
            value={form.query}
            onInput={(event) => setForm({ ...form, query: event.currentTarget.value })}
          />
        </label>
        <label>
          <span>{t("conversationSearch.mode")}</span>
          <select
            value={form.mode}
            onChange={(event) => setForm({ ...form, mode: event.currentTarget.value as SearchMode })}
          >
            <option value="terms">{t("conversationSearch.modes.terms")}</option>
            <option value="phrase">{t("conversationSearch.modes.phrase")}</option>
            <option value="prefix">{t("conversationSearch.modes.prefix")}</option>
          </select>
        </label>
        <label>
          <span>{t("conversationSearch.channel")}</span>
          <input value={form.channel} onInput={(event) => setForm({ ...form, channel: event.currentTarget.value })} />
        </label>
        <label>
          <span>{t("conversationSearch.role")}</span>
          <select
            value={form.role}
            onChange={(event) => setForm({ ...form, role: event.currentTarget.value as SearchRole })}
          >
            <option value="">{t("conversationSearch.any")}</option>
            <option value="operator">{t("conversationSearch.roles.operator")}</option>
            <option value="assistant">{t("conversationSearch.roles.assistant")}</option>
            <option value="tool">{t("conversationSearch.roles.tool")}</option>
            <option value="system">{t("conversationSearch.roles.system")}</option>
          </select>
        </label>
        <label>
          <span>{t("conversationSearch.session")}</span>
          <input value={form.conversationId} onInput={(event) => setForm({ ...form, conversationId: event.currentTarget.value })} />
        </label>
        <label>
          <span>{t("conversationSearch.incident")}</span>
          <input value={form.incidentId} onInput={(event) => setForm({ ...form, incidentId: event.currentTarget.value })} />
        </label>
        <label>
          <span>{t("conversationSearch.after")}</span>
          <input type="datetime-local" value={form.after} onInput={(event) => setForm({ ...form, after: event.currentTarget.value })} />
        </label>
        <label>
          <span>{t("conversationSearch.before")}</span>
          <input type="datetime-local" value={form.before} onInput={(event) => setForm({ ...form, before: event.currentTarget.value })} />
        </label>
        <button type="submit" disabled={loading}>{t("conversationSearch.search")}</button>
      </form>

      {loading ? <LoadingState label={t("conversationSearch.loading")} /> : null}
      {error ? <ErrorState message={error} /> : null}
      {!loading && result?.hits.length === 0 ? (
        <EmptyState title={t("conversationSearch.empty")} />
      ) : null}
      {result && result.hits.length > 0 ? (
        <section class="conversation-search-results" aria-label={t("conversationSearch.results")}>
          <header>
            <strong>{t("conversationSearch.resultCount", { count: result.hits.length })}</strong>
            <span class="muted">{t("conversationSearch.indexScope", { count: result.index_rows })}</span>
          </header>
          {result.hits.map((hit) => {
            const context = contexts[hit.result_id];
            return <article class="conversation-search-result" key={hit.result_id}>
              <div class="conversation-search-meta">
                <span>{hit.channel_id}</span>
                <span>{t(`conversationSearch.roles.${hit.role}`)}</span>
                <time dateTime={hit.recorded_at}>{new Date(hit.recorded_at).toLocaleString()}</time>
                <span class="mono">{hit.conversation_id}</span>
                {hit.incident_id ? <span class="mono">{hit.incident_id}</span> : null}
              </div>
              <p><HighlightedSnippet hit={hit} /></p>
              <div class="conversation-search-actions">
                <button type="button" onClick={() => void loadContext(hit)} disabled={contextLoading === hit.result_id}>
                  {contexts[hit.result_id]
                    ? t("conversationSearch.hideContext")
                    : t("conversationSearch.showContext")}
                </button>
                {hit.evidence_refs.map((ref) => <code key={ref}>{ref}</code>)}
              </div>
              {context ? <ContextRows context={context} /> : null}
            </article>;
          })}
        </section>
      ) : null}
    </div>
  );
}

function HighlightedSnippet({ hit }: { readonly hit: ConversationSearchHitPayload }) {
  const ranges = hit.snippet.highlights;
  if (ranges.length === 0) return <>{hit.snippet.text}</>;
  const parts: JSX.Element[] = [];
  let cursor = 0;
  ranges.forEach((range, index) => {
    if (range.start > cursor) parts.push(<span key={`text-${index}`}>{hit.snippet.text.slice(cursor, range.start)}</span>);
    parts.push(<mark key={`mark-${index}`}>{hit.snippet.text.slice(range.start, range.end)}</mark>);
    cursor = range.end;
  });
  if (cursor < hit.snippet.text.length) parts.push(<span key="tail">{hit.snippet.text.slice(cursor)}</span>);
  return <>{parts}</>;
}

function ContextRows({ context }: { readonly context: ConversationSearchContextPayload }) {
  return (
    <div class="conversation-search-context">
      {[...context.before, ...context.after].map((turn) => (
        <div key={turn.result_id}>
          <span class="muted">{t(`conversationSearch.roles.${turn.role}`)}</span>
          <span>{turn.snippet.text}</span>
        </div>
      ))}
    </div>
  );
}

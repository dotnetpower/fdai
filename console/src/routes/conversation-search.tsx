import type { JSX } from "preact";
import { useRef, useState } from "preact/hooks";
import type { PanelProps } from "../panels";
import { t } from "../i18n";
import { EmptyState, ErrorState, LoadingState, PageHeader, UnavailableState } from "../components/ui";
import {
  fetchConversationSearchContext,
  searchConversations,
  type ConversationSearchContextPayload,
  type ConversationSearchHitPayload,
  type ConversationSearchPayload,
} from "../user-context-client";
import {
  conversationSearchFailureMessage,
  conversationSearchHighlightSegments,
  conversationSearchInput,
  conversationSearchViewStatus,
  EMPTY_FORM,
  type SearchForm,
  type SearchMode,
  type SearchRole,
  toggleConversationSearchContext,
} from "./conversation-search.model";

export function ConversationSearchRoute(_props: PanelProps) {
  const [form, setForm] = useState<SearchForm>(EMPTY_FORM);
  const [result, setResult] = useState<ConversationSearchPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [contexts, setContexts] = useState<Readonly<Record<string, ConversationSearchContextPayload>>>({});
  const [contextLoading, setContextLoading] = useState<ReadonlySet<string>>(new Set());
  const searchGeneration = useRef(0);
  const contextRequests = useRef(new Set<string>());

  async function submit(event: JSX.TargetedSubmitEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const generation = ++searchGeneration.current;
    setLoading(true);
    setError(null);
    setResult(null);
    setContexts({});
    try {
      const next = await searchConversations(conversationSearchInput(form));
      if (generation === searchGeneration.current) setResult(next);
    } catch (reason) {
      if (generation === searchGeneration.current) {
        setError(reason);
      }
    } finally {
      if (generation === searchGeneration.current) setLoading(false);
    }
  }

  async function loadContext(hit: ConversationSearchHitPayload): Promise<void> {
    if (contexts[hit.result_id]) {
      setContexts((current) => toggleConversationSearchContext(current, hit.result_id, null));
      return;
    }
    const generation = searchGeneration.current;
    const requestKey = `${generation}:${hit.result_id}`;
    if (contextRequests.current.has(requestKey)) return;
    contextRequests.current.add(requestKey);
    setError(null);
    setContextLoading((current) => new Set(current).add(hit.result_id));
    try {
      const context = await fetchConversationSearchContext(hit.result_id, 1, 1);
      if (generation === searchGeneration.current) {
        setContexts((current) => toggleConversationSearchContext(current, hit.result_id, context));
      }
    } catch (reason) {
      if (generation === searchGeneration.current) {
        setError(reason);
      }
    } finally {
      contextRequests.current.delete(requestKey);
      setContextLoading((current) => {
        const next = new Set(current);
        next.delete(hit.result_id);
        return next;
      });
    }
  }

  const viewStatus = conversationSearchViewStatus(loading, error, result);

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

      {viewStatus === "loading" ? <LoadingState label={t("conversationSearch.loading")} /> : null}
      {viewStatus === "unavailable" ? <UnavailableState message={conversationSearchFailureMessage(error)} /> : null}
      {viewStatus === "error" ? <ErrorState message={conversationSearchFailureMessage(error)} /> : null}
      {viewStatus === "empty" ? (
        <EmptyState title={t("conversationSearch.empty")} />
      ) : null}
      {viewStatus === "results" && result ? (
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
                <button
                  type="button"
                  onClick={() => void loadContext(hit)}
                  disabled={contextLoading.has(hit.result_id)}
                  aria-expanded={Boolean(context)}
                >
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
  return <>{conversationSearchHighlightSegments(hit).map((segment, index) => segment.highlighted
    ? <mark key={`mark-${index}`}>{segment.text}</mark>
    : <span key={`text-${index}`}>{segment.text}</span>)}</>;
}

function ContextRows({ context }: { readonly context: ConversationSearchContextPayload }) {
  return (
    <div class="conversation-search-context">
      <div aria-label={t("conversationSearch.contextBefore")}>
        {context.before.map((turn) => (
          <div key={turn.result_id}>
            <span class="muted">{t(`conversationSearch.roles.${turn.role}`)}</span>
            <span>{turn.snippet.text}</span>
          </div>
        ))}
      </div>
      <div aria-label={t("conversationSearch.contextAfter")}>
        {context.after.map((turn) => (
          <div key={turn.result_id}>
            <span class="muted">{t(`conversationSearch.roles.${turn.role}`)}</span>
            <span>{turn.snippet.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

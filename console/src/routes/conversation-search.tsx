import type { JSX } from "preact";
import { useRef, useState } from "preact/hooks";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import type { PanelProps } from "../panels";
import { getLocale, t } from "../i18n";
import { formatConsoleTimestamp } from "../time-format";
import {
  ConversationTurnItem,
  type ConversationRole,
} from "../components/domain-primitives";
import { SearchInput, SelectField, TextInput } from "../components/form-controls";
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
import "./conversation-search.css";

function normalizeTurnRole(role: string): ConversationRole {
  if (role === "operator" || role === "assistant" || role === "tool" || role === "system") {
    return role;
  }
  return "assistant";
}

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
    if (!form.query.trim()) return;
    const generation = ++searchGeneration.current;
    setLoading(true);
    setError(null);
    setResult(null);
    setContexts({});
    setContextLoading(new Set());
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
      if (generation === searchGeneration.current) {
        setContextLoading((current) => {
          const next = new Set(current);
          next.delete(hit.result_id);
          return next;
        });
      }
    }
  }

  const viewStatus = conversationSearchViewStatus(loading, error, result);
  usePublishViewContext(
    () => ({
      routeId: "conversation-search",
      routeLabel: t("conversationSearch.title"),
      purpose: t("conversationSearch.subtitle"),
      glossary: composeGlossary([TERMS.correlationId]),
      headline: result
        ? `${result.hits.length} hits (${form.mode})`
        : viewStatus,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "status", value: viewStatus, group: "search" },
        { key: "mode", value: form.mode, group: "search" },
        { key: "hit_count", value: result?.hits.length ?? 0, group: "search" },
      ],
      records: {
        hits: (result?.hits ?? []).slice(0, 25).map((hit) => ({
          result_id: hit.result_id,
          conversation_id: hit.conversation_id,
          role: hit.role,
          channel: hit.channel_id,
          recorded_at: formatConsoleTimestamp(hit.recorded_at),
        })),
      },
    }),
    [form.mode, result, viewStatus],
  );

  return (
    <div class="stack conversation-search-view cs-workspace-route">
      <PageHeader
        title={t("conversationSearch.title")}
        subtitle={t("conversationSearch.subtitle")}
      />
      <form class="conversation-search-form" onSubmit={(event) => void submit(event)}>
        <SearchInput
          label={t("conversationSearch.query")}
          value={form.query}
          maxLength={256}
          className="conversation-search-query"
          onInput={(value) => setForm({ ...form, query: value })}
        />
        <SelectField
          label={t("conversationSearch.mode")}
          value={form.mode}
          className="conversation-search-compact"
          options={[
            { value: "terms", label: t("conversationSearch.modes.terms") },
            { value: "phrase", label: t("conversationSearch.modes.phrase") },
            { value: "prefix", label: t("conversationSearch.modes.prefix") },
          ]}
          onChange={(value) => setForm({ ...form, mode: value as SearchMode })}
        />
        <SelectField
          label={t("conversationSearch.role")}
          value={form.role}
          className="conversation-search-compact"
          options={[
            { value: "", label: t("conversationSearch.any") },
            { value: "operator", label: t("conversationSearch.roles.operator") },
            { value: "assistant", label: t("conversationSearch.roles.assistant") },
            { value: "tool", label: t("conversationSearch.roles.tool") },
            { value: "system", label: t("conversationSearch.roles.system") },
          ]}
          onChange={(value) => setForm({ ...form, role: value as SearchRole })}
        />
        <TextInput
          label={t("conversationSearch.channel")}
          value={form.channel}
          onInput={(value) => setForm({ ...form, channel: value })}
        />
        <TextInput
          label={t("conversationSearch.session")}
          value={form.conversationId}
          mono
          onInput={(value) => setForm({ ...form, conversationId: value })}
        />
        <TextInput
          label={t("conversationSearch.incident")}
          value={form.incidentId}
          mono
          onInput={(value) => setForm({ ...form, incidentId: value })}
        />
        <TextInput
          type="datetime-local"
          label={t("conversationSearch.after")}
          value={form.after}
          onInput={(value) => setForm({ ...form, after: value })}
        />
        <TextInput
          type="datetime-local"
          label={t("conversationSearch.before")}
          value={form.before}
          onInput={(value) => setForm({ ...form, before: value })}
        />
        <button
          type="submit"
          class="btn primary conversation-search-submit"
          disabled={loading || !form.query.trim()}
        >
          {t("conversationSearch.search")}
        </button>
      </form>

      {viewStatus === "idle" ? (
        <dl class="cs-facts-grid">
          <div><dt>{t("conversationSearch.mode")}</dt><dd>{t(`conversationSearch.modes.${form.mode}`)}</dd></div>
          <div><dt>{t("conversationSearch.role")}</dt><dd>{form.role ? t(`conversationSearch.roles.${form.role}`) : t("conversationSearch.any")}</dd></div>
          <div><dt>{getLocale() === "ko" ? "맥락 불러오기" : "Context loading"}</dt><dd>{getLocale() === "ko" ? "운영자 선택 시" : "Operator selected"}</dd></div>
          <div><dt>{getLocale() === "ko" ? "권한" : "Authority"}</dt><dd>{getLocale() === "ko" ? "읽기 전용" : "Read-only"}</dd></div>
        </dl>
      ) : null}
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
            const contextDomId = `conversation-search-context-${hit.result_id}`;
            return (
              <article class="conversation-search-result" key={hit.result_id}>
                <div class="conversation-search-meta">
                  <span>{hit.channel_id}</span>
                  <span class="mono">{hit.conversation_id}</span>
                  {hit.incident_id ? <span class="mono">{hit.incident_id}</span> : null}
                </div>
                <ConversationTurnItem
                  role={normalizeTurnRole(hit.role)}
                  authorLabel={t(`conversationSearch.roles.${hit.role}`)}
                  timestamp={formatConsoleTimestamp(hit.recorded_at)}
                  content={<HighlightedSnippet hit={hit} />}
                  footer={(
                    <div class="conversation-search-actions">
                      <button
                        type="button"
                        class="btn secondary"
                        onClick={() => void loadContext(hit)}
                        disabled={contextLoading.has(hit.result_id)}
                        aria-expanded={Boolean(context)}
                        aria-controls={context ? contextDomId : undefined}
                      >
                        {contexts[hit.result_id]
                          ? t("conversationSearch.hideContext")
                          : t("conversationSearch.showContext")}
                      </button>
                      {hit.evidence_refs.map((ref, index) => <code key={`${ref}:${index}`}>{ref}</code>)}
                    </div>
                  )}
                />
                {context ? <ContextRows id={contextDomId} context={context} /> : null}
              </article>
            );
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

function ContextRows({ id, context }: { readonly id: string; readonly context: ConversationSearchContextPayload }) {
  if (context.before.length === 0 && context.after.length === 0) {
    return (
      <div id={id} class="conversation-search-context muted">
        {t("conversationSearch.empty")}
      </div>
    );
  }
  return (
    <div id={id} class="conversation-search-context">
      <div class="conversation-search-context-group" aria-label={t("conversationSearch.contextBefore")}>
        {context.before.map((turn) => (
          <ConversationTurnItem
            key={turn.result_id}
            role={normalizeTurnRole(turn.role)}
            authorLabel={t(`conversationSearch.roles.${turn.role}`)}
            timestamp={formatConsoleTimestamp(turn.recorded_at)}
            content={turn.snippet.text}
          />
        ))}
      </div>
      <div class="conversation-search-context-group" aria-label={t("conversationSearch.contextAfter")}>
        {context.after.map((turn) => (
          <ConversationTurnItem
            key={turn.result_id}
            role={normalizeTurnRole(turn.role)}
            authorLabel={t(`conversationSearch.roles.${turn.role}`)}
            timestamp={formatConsoleTimestamp(turn.recorded_at)}
            content={turn.snippet.text}
          />
        ))}
      </div>
    </div>
  );
}

import { Tooltip } from "../components/tooltip";
import { t } from "../i18n";
import {
  type AnswerVerification,
  type AnswerPlanMetadata,
  type AnswerPlanningMetadata,
  type BackendHealth,
  type GroundedCodeArtifact,
  type RouterSnapshot,
  type VerificationProgress,
} from "./backend";
import { type DeckLayoutMode } from "./command-deck-session";
import {
  conversationGroups,
  isScreenConversationKey,
  type ConversationSummary,
} from "./conversation-sessions";
import { useViewContext } from "./context";
import { GroundedReply } from "./grounded-reply";
import { introSuggestions } from "./intro-suggestions";

export interface Turn {
  readonly id: string;
  readonly role: "operator" | "deck";
  readonly text: string;
  readonly citations?: readonly { readonly label: string; readonly value?: string }[];
  readonly followUps?: readonly string[];
  readonly source?: string;
  readonly router?: RouterSnapshot;
  readonly streaming?: boolean;
  readonly terminal?: boolean;
  readonly revision?: number;
  readonly verification?: AnswerVerification;
  readonly verificationProgress?: VerificationProgress;
  readonly answerPlan?: AnswerPlanMetadata;
  readonly answerPlanning?: AnswerPlanningMetadata;
  readonly codeArtifacts?: readonly GroundedCodeArtifact[];
  readonly agent?: string;
  readonly at: string;
}

export const DEFAULT_NARRATOR = "Bragi";

function agentIconUrl(name: string): string {
  const base = typeof import.meta.env.BASE_URL === "string" ? import.meta.env.BASE_URL : "/";
  return `url("${base}agent-icons/${name.toLowerCase()}.svg")`;
}

function routerTooltip(router: RouterSnapshot | undefined): string | undefined {
  if (!router) return undefined;
  const lines = router.candidates.map((candidate) => {
    const p50 = candidate.p50_ms === null ? "-" : `${Math.round(candidate.p50_ms)}ms`;
    const p95 = candidate.p95_ms === null ? "-" : `${Math.round(candidate.p95_ms)}ms`;
    const marker = candidate.deployment === router.chose ? "* " : "  ";
    return `${marker}${candidate.deployment} · p50 ${p50} · p95 ${p95} · n=${candidate.samples}`;
  });
  return `auto-router (${router.reason}) chose ${router.chose}\n${lines.join("\n")}`;
}

export function DeckLayoutIcon({ mode }: { readonly mode: DeckLayoutMode }) {
  if (mode === "dock") {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <rect x="2" y="2.5" width="12" height="11" rx="1.5" />
        <path d="M10 3v10" />
      </svg>
    );
  }
  if (mode === "workspace") {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M5.5 2.5h-3v3M10.5 2.5h3v3M5.5 13.5h-3v-3M10.5 13.5h3v-3" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <rect x="3" y="4" width="10" height="8" rx="1.5" />
      <path d="M3.5 6.5h9" />
    </svg>
  );
}

export function ConversationSidebar({
  conversations,
  activeKey,
  currentPath,
  onNew,
  onSelect,
  onRemove,
}: {
  readonly conversations: readonly ConversationSummary[];
  readonly activeKey: string;
  readonly currentPath: string;
  readonly onNew: () => void;
  readonly onSelect: (conversation: ConversationSummary) => void;
  readonly onRemove: (conversation: ConversationSummary) => void;
}) {
  const groups = conversationGroups(conversations, currentPath);
  return (
    <aside class="deck-conversations" aria-label={t("deck.conversations")}>
      <div class="deck-conversations-head">
        <span>{t("deck.conversations")}</span>
        <span class="deck-conversations-count">{conversations.length}</span>
      </div>
      <button type="button" class="deck-conversation-new" onClick={onNew}>
        <span aria-hidden="true">+</span>
        {t("deck.newConversation")}
      </button>
      <div class="deck-conversation-list">
        {conversations.length === 0 ? (
          <p class="deck-conversation-empty">{t("deck.noConversations")}</p>
        ) : (
          <>
            <ConversationGroup
              label={t("deck.currentScreen")}
              conversations={groups.current}
              activeKey={activeKey}
              showOrigin={false}
              onSelect={onSelect}
              onRemove={onRemove}
            />
            <ConversationGroup
              label={t("deck.otherScreens")}
              conversations={groups.other}
              activeKey={activeKey}
              showOrigin
              onSelect={onSelect}
              onRemove={onRemove}
            />
            <ConversationGroup
              label={t("deck.agentConversations")}
              conversations={groups.agents}
              activeKey={activeKey}
              showOrigin
              onSelect={onSelect}
              onRemove={onRemove}
            />
          </>
        )}
      </div>
    </aside>
  );
}

function ConversationGroup({
  label,
  conversations,
  activeKey,
  showOrigin,
  onSelect,
  onRemove,
}: {
  readonly label: string;
  readonly conversations: readonly ConversationSummary[];
  readonly activeKey: string;
  readonly showOrigin: boolean;
  readonly onSelect: (conversation: ConversationSummary) => void;
  readonly onRemove: (conversation: ConversationSummary) => void;
}) {
  if (conversations.length === 0) return null;
  return (
    <section class="deck-conversation-group" aria-label={label}>
      <h3>{label}</h3>
      {conversations.map((conversation) => (
        <div
          key={conversation.key}
          class={`deck-conversation ${conversation.key === activeKey ? "is-active" : ""}`}
        >
          <button
            type="button"
            class="deck-conversation-select"
            aria-current={conversation.key === activeKey ? "true" : undefined}
            onClick={() => onSelect(conversation)}
          >
            <span
              class="deck-conversation-avatar is-agent"
              aria-hidden="true"
              style={{
                WebkitMaskImage: agentIconUrl(conversation.agent ?? DEFAULT_NARRATOR),
                maskImage: agentIconUrl(conversation.agent ?? DEFAULT_NARRATOR),
              }}
            />
            <span class="deck-conversation-copy">
              <strong>{conversation.label}</strong>
              <small>
                {showOrigin && conversation.originLabel !== conversation.label
                  ? `${conversation.originLabel} · `
                  : ""}
                {new Date(conversation.updatedAt).toLocaleString()}
              </small>
            </span>
          </button>
          {!isScreenConversationKey(conversation.key) ? (
            <Tooltip content={t("deck.removeCachedConversationHint")}>
              <button
                type="button"
                class="deck-conversation-remove"
                onClick={() => onRemove(conversation)}
                aria-label={`${t("deck.removeCachedConversation")}: ${conversation.label}`}
              >
                ×
              </button>
            </Tooltip>
          ) : null}
        </div>
      ))}
    </section>
  );
}

export function TurnBubble({
  turn,
  onPickFollowUp,
  onRegenerate,
  searchMatch,
  activeSearchMatch,
}: {
  readonly turn: Turn;
  readonly onPickFollowUp: (text: string) => void;
  readonly onRegenerate?: () => void;
  readonly searchMatch: boolean;
  readonly activeSearchMatch: boolean;
}) {
  const isDeck = turn.role === "deck";
  return (
    <article
      id={`deck-turn-${turn.id}`}
      class={`deck-turn deck-turn-${turn.role}${turn.streaming ? " is-streaming" : ""}${searchMatch ? " is-search-match" : ""}${activeSearchMatch ? " is-active-search-match" : ""}`}
    >
      {isDeck ? (
        <header class="deck-turn-head">
          <span class="deck-turn-role deck-turn-agent">
            <span
              class="deck-turn-agent-icon"
              aria-hidden="true"
              style={{
                WebkitMaskImage: agentIconUrl(turn.agent ?? DEFAULT_NARRATOR),
                maskImage: agentIconUrl(turn.agent ?? DEFAULT_NARRATOR),
              }}
            />
            {turn.agent ?? DEFAULT_NARRATOR}
          </span>
          {turn.source ? (
            <Tooltip content={routerTooltip(turn.router) ?? t("deck.tooltip.replySource")}>
              <span class="deck-turn-source">{turn.source}</span>
            </Tooltip>
          ) : null}
        </header>
      ) : null}
      {isDeck ? (
        <GroundedReply
          turnId={turn.id}
          text={turn.text}
          citations={turn.citations}
          source={turn.source}
          streaming={turn.streaming === true}
          verification={turn.verification}
          verificationProgress={turn.verificationProgress}
          answerPlan={turn.answerPlan}
          answerPlanning={turn.answerPlanning}
          codeArtifacts={turn.codeArtifacts}
          {...(onRegenerate ? { onRegenerate } : {})}
        />
      ) : (
        <div class="deck-turn-body">
          {turn.text.split("\n").map((line, index) => (
            <p key={index} class="deck-turn-line">{line}</p>
          ))}
        </div>
      )}
      {turn.followUps && turn.followUps.length > 0 ? (
        <ul class="deck-followups" aria-label="suggested follow-ups">
          {turn.followUps.map((followUp) => (
            <li key={followUp}>
              <button
                type="button"
                class="deck-followup"
                onClick={() => onPickFollowUp(followUp)}
              >
                {followUp}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div class="deck-turn-foot">
        <span class="deck-turn-time muted">{turn.at}</span>
      </div>
    </article>
  );
}

export function BackendBadge({
  health,
  placement,
}: {
  readonly health: BackendHealth | null;
  readonly placement: "invoke" | "header";
}) {
  if (health === null) {
    return (
      <Tooltip content={t("deck.tooltip.backendProbing")}>
        <span class={`deck-backend deck-backend-${placement} deck-backend-probing`}>
          <span class="deck-backend-dot" />
          <span class="deck-backend-label">probing</span>
        </span>
      </Tooltip>
    );
  }
  if (health.available) {
    const routed = health.router;
    const label = routed
      ? `LLM · auto(${routed.candidates.length}) · ${routed.chose}`
      : health.model
        ? `LLM · ${health.model}`
        : "LLM ready";
    const base = `chat mode ${health.mode}${
      health.endpoint ? ` · ${health.endpoint}` : ""
    }`;
    const tooltip = routed ? `${base}\n${routerTooltip(routed) ?? ""}` : base;
    return (
      <Tooltip content={tooltip}>
        <span class={`deck-backend deck-backend-${placement} deck-backend-ready`}>
          <span class="deck-backend-dot" />
          <span class="deck-backend-label">{label}</span>
        </span>
      </Tooltip>
    );
  }
  return (
    <Tooltip content={t("deck.tooltip.backendFallback", { mode: health.mode })}>
      <span class={`deck-backend deck-backend-${placement} deck-backend-fallback`}>
        <span class="deck-backend-dot" />
        <span class="deck-backend-label">deterministic</span>
      </span>
    </Tooltip>
  );
}

export function IntroPanel({
  snapshot,
  onPick,
}: {
  readonly snapshot: ReturnType<typeof useViewContext>;
  readonly onPick: (suggestion: string) => void;
}) {
  const suggestions = introSuggestions(snapshot);
  return (
    <div class="deck-intro">
      <p class="deck-intro-lead">
        Ask about anything currently visible - tiles, KPIs, approvals, audit rows,
        promotion status, blast radius, or ontology. I ground every answer in the
        snapshot on the right.
      </p>
      <ul class="deck-intro-suggest">
        {suggestions.map((suggestion) => (
          <li key={suggestion}>
            <button type="button" class="deck-suggest" onClick={() => onPick(suggestion)}>
              {suggestion}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

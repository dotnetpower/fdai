import { Tooltip } from "../components/tooltip";
import { t } from "../i18n";
import { useLayoutEffect, useRef, useState } from "preact/hooks";
import {
  type AnswerVerification,
  type ActionDraft,
  type AnswerPlanMetadata,
  type AnswerPlanningMetadata,
  type BackendHealth,
  type DelegationMetadata,
  type ConfirmedAnswerSegment,
  type EvidenceBranch,
  type EvidenceFreshnessContext,
  type GroundedCodeArtifact,
  type InvestigationActivity,
  type IntentGraphEvidence,
  type IntentGraphMetadata,
  type IntentEvidenceMode,
  type ModelTrace,
  type TurnTiming,
  type TrajectoryDetail,
  type RouterSnapshot,
  type ResourceContext,
  type VerificationProgress,
} from "./backend";
import { replyAgentLabel, type DeckLayoutMode } from "./command-deck-session";
import {
  conversationHasUnreadActivity,
  CONVERSATION_HISTORY_PAGE_SIZE,
  conversationGroups,
  isScreenConversationKey,
  type ConversationSummary,
  type ConversationListFilter,
  conversationMatchesFilter,
} from "./conversation-sessions";
import { useViewContext } from "./context";
import type { ConversationTrajectory } from "./conversation-trajectory";
import { ConversationTrajectoryView } from "./conversation-trajectory-view";
import { ConversationTurnAttachments } from "./conversation-turn-attachments";
import { GroundedReply } from "./grounded-reply";
import { InvestigationTimeline } from "./investigation-timeline";
import { introSuggestions } from "./intro-suggestions";
import type { TurnAttachment } from "./turn-attachments";

export interface Turn {
  readonly id: string;
  readonly role: "operator" | "deck";
  readonly text: string;
  readonly attachments?: readonly TurnAttachment[];
  readonly recordedAt?: string;
  /** Bounded non-rendered context sent in place of `text` for backend history. */
  readonly groundingText?: string;
  readonly kind?: "message" | "activity";
  readonly activities?: readonly InvestigationActivity[];
  readonly branches?: readonly EvidenceBranch[];
  readonly confirmed?: ConfirmedAnswerSegment;
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
  readonly delegation?: DelegationMetadata;
  readonly codeArtifacts?: readonly GroundedCodeArtifact[];
  readonly incidentCandidates?: readonly import("./backend-types").IncidentCandidate[];
  readonly actionDraft?: ActionDraft;
  readonly modelTrace?: ModelTrace;
  readonly turnTiming?: TurnTiming;
  readonly trajectoryDetail?: TrajectoryDetail;
  readonly resourceContext?: ResourceContext;
  readonly evidenceFreshnessContext?: EvidenceFreshnessContext;
  readonly intentGraph?: IntentGraphMetadata;
  readonly intentGraphEvidence?: IntentGraphEvidence;
  readonly evidenceMode?: IntentEvidenceMode;
  readonly agent?: string;
  readonly at: string;
}

export const DEFAULT_NARRATOR = "Bragi";

export function conversationCountLabel(count: number, hasMore: boolean): string {
  return count >= CONVERSATION_HISTORY_PAGE_SIZE || hasMore
    ? `${CONVERSATION_HISTORY_PAGE_SIZE}+`
    : String(count);
}

export function shouldLoadMoreConversations(
  element: Pick<HTMLElement, "clientHeight" | "scrollHeight" | "scrollTop">,
  hasMore: boolean,
): boolean {
  return hasMore && element.scrollHeight - element.scrollTop - element.clientHeight <= 120;
}

export function hasOverflowingText(
  element: Pick<HTMLElement, "clientWidth" | "scrollWidth">,
): boolean {
  return element.scrollWidth > element.clientWidth;
}

function ConversationTitle({ label }: { readonly label: string }) {
  const titleRef = useRef<HTMLSpanElement | null>(null);
  const [truncated, setTruncated] = useState(false);

  useLayoutEffect(() => {
    const title = titleRef.current;
    if (!title) return undefined;
    const measure = () => setTruncated(hasOverflowingText(title));
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(title);
    return () => observer.disconnect();
  }, [label]);

  return (
    <Tooltip content={truncated ? label : undefined}>
      <span ref={titleRef} class="deck-conversation-title">{label}</span>
    </Tooltip>
  );
}

function agentIconUrl(name: string): string {
  const base = typeof import.meta.env.BASE_URL === "string" ? import.meta.env.BASE_URL : "/";
  return `url("${base}agent-icons/${name.toLowerCase()}.svg")`;
}

interface BackendTooltipCandidateView {
  readonly deployment: string;
  readonly p50: string;
  readonly p95: string;
  readonly samples: number;
  readonly selected: boolean;
}

export interface BackendTooltipView {
  readonly mode: string;
  readonly endpoint: string | null;
  readonly router: {
    readonly deployment: string;
    readonly reason: string;
    readonly candidates: readonly BackendTooltipCandidateView[];
  } | null;
  readonly visionRouter?: {
    readonly deployment: string;
    readonly candidates: readonly BackendTooltipCandidateView[];
  };
}

export function backendTooltipView(health: BackendHealth): BackendTooltipView {
  const router = health.router;
  const vision = router?.vision;
  return {
    mode: health.mode,
    endpoint: health.endpoint,
    router: router ? {
      deployment: router.chose,
      reason: router.reason.trim(),
      candidates: router.candidates.map((candidate) => ({
        deployment: candidate.deployment,
        p50: candidate.p50_ms === null ? "-" : `${Math.round(candidate.p50_ms)}ms`,
        p95: candidate.p95_ms === null ? "-" : `${Math.round(candidate.p95_ms)}ms`,
        samples: candidate.samples,
        selected: candidate.deployment === router.chose,
      })),
    } : null,
    ...(vision?.available && vision.chose
      ? {
          visionRouter: {
            deployment: vision.chose,
            candidates: vision.candidates.map((candidate) => ({
              deployment: candidate.deployment,
              p50: candidate.p50_ms === null ? "-" : `${Math.round(candidate.p50_ms)}ms`,
              p95: candidate.p95_ms === null ? "-" : `${Math.round(candidate.p95_ms)}ms`,
              samples: candidate.samples,
              selected: candidate.deployment === vision.chose,
            })),
          },
        }
      : {}),
  };
}

export function routerTooltip(router: RouterSnapshot | undefined): string | undefined {
  if (!router) return undefined;
  const lines = router.candidates.map((candidate) => {
    const p50 = candidate.p50_ms === null ? "-" : `${Math.round(candidate.p50_ms)}ms`;
    const p95 = candidate.p95_ms === null ? "-" : `${Math.round(candidate.p95_ms)}ms`;
    const marker = candidate.deployment === router.chose ? "* " : "  ";
    return `${marker}${candidate.deployment} · p50 ${p50} · p95 ${p95} · n=${candidate.samples}`;
  });
  const choice = t("deck.tooltip.routerChoice", {
    reason: router.reason,
    deployment: router.chose,
    candidates: lines.join("\n"),
  });
  return router.reason.trim() ? choice : choice.replace(" ()", "").replace("()", "");
}

export function backendTooltip(health: BackendHealth): string {
  const base = t("deck.tooltip.chatMode", {
    mode: health.mode,
    endpoint: health.endpoint ? ` · ${health.endpoint}` : "",
  });
  const routed = routerTooltip(health.router);
  return routed ? `${base}\n${routed}` : base;
}

function BackendTooltipContent({ health }: { readonly health: BackendHealth }) {
  const view = backendTooltipView(health);
  return (
    <span class="deck-backend-tooltip">
      <span class="deck-backend-tooltip-context">
        <span>{t("deck.tooltip.chatMode", { mode: "", endpoint: "" }).trim()}</span>
        <strong>{view.mode}</strong>
      </span>
      {view.endpoint ? <code class="deck-backend-tooltip-endpoint">{view.endpoint}</code> : null}
      {view.router ? (
        <span class="deck-backend-tooltip-router">
          <span class="deck-backend-tooltip-choice">
            <span>auto-router</span>
            <strong>{view.router.deployment}</strong>
            {view.router.reason ? <small>{view.router.reason}</small> : null}
          </span>
          <span class="deck-backend-tooltip-candidates">
            {view.router.candidates.map((candidate) => (
              <span
                key={candidate.deployment}
                class={`deck-backend-tooltip-candidate${candidate.selected ? " is-selected" : ""}`}
                aria-current={candidate.selected ? "true" : undefined}
              >
                <span class="deck-backend-tooltip-marker" aria-hidden="true" />
                <code>{candidate.deployment}</code>
                <span><small>p50</small>{candidate.p50}</span>
                <span><small>p95</small>{candidate.p95}</span>
                <span><small>n</small>{candidate.samples}</span>
              </span>
            ))}
          </span>
        </span>
      ) : null}
      {view.visionRouter ? (
        <span class="deck-backend-tooltip-router">
          <span class="deck-backend-tooltip-choice">
            <span>vision-router</span>
            <strong>{view.visionRouter.deployment}</strong>
          </span>
          <span class="deck-backend-tooltip-candidates">
            {view.visionRouter.candidates.map((candidate) => (
              <span
                key={`vision-${candidate.deployment}`}
                class={`deck-backend-tooltip-candidate${candidate.selected ? " is-selected" : ""}`}
                aria-current={candidate.selected ? "true" : undefined}
              >
                <span class="deck-backend-tooltip-marker" aria-hidden="true" />
                <code>{candidate.deployment}</code>
                <span><small>p50</small>{candidate.p50}</span>
                <span><small>p95</small>{candidate.p95}</span>
                <span><small>n</small>{candidate.samples}</span>
              </span>
            ))}
          </span>
        </span>
      ) : null}
    </span>
  );
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
  hasMore,
  loading,
  onNew,
  onLoadMore,
  onSelect,
  onRemove,
  onToggleFavorite,
}: {
  readonly conversations: readonly ConversationSummary[];
  readonly activeKey: string;
  readonly currentPath: string;
  readonly hasMore: boolean;
  readonly loading: boolean;
  readonly onNew: () => void;
  readonly onLoadMore: () => void;
  readonly onSelect: (conversation: ConversationSummary) => void;
  readonly onRemove: (conversation: ConversationSummary) => void;
  readonly onToggleFavorite: (conversation: ConversationSummary) => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ConversationListFilter>("mine");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredConversations = conversations.filter((conversation) =>
    conversationMatchesFilter(conversation, filter));
  const visibleConversations = normalizedQuery
    ? filteredConversations.filter((conversation) =>
        `${conversation.label} ${conversation.originLabel}`.toLocaleLowerCase().includes(normalizedQuery))
    : filteredConversations;
  const groups = conversationGroups(visibleConversations, currentPath);
  return (
    <aside
      class="deck-conversations"
      aria-label={t("deck.conversations")}
      aria-busy={loading}
      onScroll={(event) => {
        const element = event.currentTarget;
        if (shouldLoadMoreConversations(element, hasMore)) onLoadMore();
      }}
    >
      <div class="deck-conversations-head">
        <span>{t("deck.conversations")}</span>
        <span class="deck-conversations-count">
          {conversationCountLabel(conversations.length, hasMore)}
        </span>
      </div>
      <button type="button" class="deck-conversation-new" onClick={onNew}>
        <span aria-hidden="true">+</span>
        {t("deck.newConversation")}
      </button>
      <input
        class="deck-conversation-filter"
        type="search"
        value={query}
        aria-label={t("deck.filterConversations")}
        placeholder={t("deck.filterConversations")}
        onInput={(event) => setQuery(event.currentTarget.value)}
      />
      <div class="deck-conversation-filters" role="group" aria-label={t("deck.conversationFilters.label")}>
        {(["mine", "unread", "favorites"] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
          >
            {t(`deck.conversationFilters.${value}`)}
          </button>
        ))}
      </div>
      <div class="deck-conversation-list">
        {visibleConversations.length === 0 ? (
          <p class="deck-conversation-empty">
            {conversations.length === 0 ? t("deck.noConversations") : t("deck.noConversationMatches")}
          </p>
        ) : (
          <>
            <ConversationGroup
              label={t("deck.currentScreen")}
              conversations={groups.current}
              activeKey={activeKey}
              showOrigin={false}
              onSelect={onSelect}
              onRemove={onRemove}
              onToggleFavorite={onToggleFavorite}
            />
            <ConversationGroup
              label={t("deck.otherScreens")}
              conversations={groups.other}
              activeKey={activeKey}
              showOrigin
              onSelect={onSelect}
              onRemove={onRemove}
              onToggleFavorite={onToggleFavorite}
            />
            <ConversationGroup
              label={t("deck.agentConversations")}
              conversations={groups.agents}
              activeKey={activeKey}
              showOrigin
              onSelect={onSelect}
              onRemove={onRemove}
              onToggleFavorite={onToggleFavorite}
            />
          </>
        )}
        {loading ? (
          <div
            class="deck-conversation-load-skeleton"
            role="status"
            aria-label={t("deck.loadingConversations")}
          >
            <span aria-hidden="true" /><span aria-hidden="true" /><span aria-hidden="true" />
          </div>
        ) : null}
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
  onToggleFavorite,
}: {
  readonly label: string;
  readonly conversations: readonly ConversationSummary[];
  readonly activeKey: string;
  readonly showOrigin: boolean;
  readonly onSelect: (conversation: ConversationSummary) => void;
  readonly onRemove: (conversation: ConversationSummary) => void;
  readonly onToggleFavorite: (conversation: ConversationSummary) => void;
}) {
  if (conversations.length === 0) return null;
  return (
    <section class="deck-conversation-group" aria-label={label}>
      <h3>{label}</h3>
      {conversations.map((conversation) => (
        <div
          key={conversation.key}
          class={`deck-conversation ${conversation.key === activeKey ? "is-active" : ""} ${
            conversation.key !== activeKey && conversationHasUnreadActivity(conversation)
              ? "is-unread"
              : ""
          }`}
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
              <ConversationTitle label={conversation.label} />
              <small>
                {showOrigin && conversation.originLabel !== conversation.label
                  ? `${conversation.originLabel} · `
                  : ""}
                {conversationTimeLabel(conversation.updatedAt)}
              </small>
            </span>
          </button>
          <Tooltip content={t(conversation.favorite ? "deck.favorite.remove" : "deck.favorite.add")}>
            <button
              type="button"
              class={`deck-conversation-favorite${conversation.favorite ? " is-favorite" : ""}`}
              onClick={() => onToggleFavorite(conversation)}
              aria-label={`${t(conversation.favorite ? "deck.favorite.remove" : "deck.favorite.add")}: ${conversation.label}`}
              aria-pressed={conversation.favorite === true}
            >
              <span aria-hidden="true">{conversation.favorite ? "★" : "☆"}</span>
            </button>
          </Tooltip>
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

export function conversationTimeLabel(value: string, nowMs: number = Date.now()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = new Date(nowMs);
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return time;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) {
    return t("deck.yesterdayAt", { time });
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function TurnBubble({
  turn,
  trajectory,
  showModelTrace,
  onPickFollowUp,
  onRegenerate,
  searchMatch,
  activeSearchMatch,
  progressIndex,
  investigationFlowContinuation,
  investigationFlowStart,
  investigationFlowEnd,
}: {
  readonly turn: Turn;
  readonly trajectory?: ConversationTrajectory;
  readonly showModelTrace: boolean;
  readonly onPickFollowUp: (text: string) => void;
  readonly onRegenerate?: () => void;
  readonly searchMatch: boolean;
  readonly activeSearchMatch: boolean;
  readonly progressIndex?: number;
  readonly investigationFlowContinuation: boolean;
  readonly investigationFlowStart: boolean;
  readonly investigationFlowEnd: boolean;
}) {
  const isDeck = turn.role === "deck";
  const isActivity = turn.kind === "activity";
  const isProgressMessage = turn.kind === "message" && turn.source === "investigation";
  const isInvestigationFlow = isActivity || isProgressMessage || investigationFlowContinuation;
  return (
    <article
      id={`deck-turn-${turn.id}`}
      class={`deck-turn deck-turn-${turn.role}${isActivity ? " deck-turn-activity" : ""}${turn.source === "context" ? " is-context" : ""}${turn.streaming ? " is-streaming" : ""}${searchMatch ? " is-search-match" : ""}${activeSearchMatch ? " is-active-search-match" : ""}${isInvestigationFlow ? " is-investigation-flow" : ""}${investigationFlowStart ? " is-flow-start" : ""}${investigationFlowEnd ? " is-flow-end" : ""}`}
    >
      {isDeck && (!isInvestigationFlow || investigationFlowStart) ? (
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
            {replyAgentLabel(turn.agent ?? DEFAULT_NARRATOR, turn.delegation)}
          </span>
          {isInvestigationFlow ? (
            <span class="deck-turn-source">{t("deck.investigation.title")}</span>
          ) : turn.source ? (
            <Tooltip content={routerTooltip(turn.router) ?? t("deck.tooltip.replySource")}>
              <span class="deck-turn-source">{turn.source}</span>
            </Tooltip>
          ) : null}
        </header>
      ) : null}
      {isActivity ? (
        <InvestigationTimeline
          activities={turn.activities ?? []}
          branches={turn.branches ?? []}
          running={turn.streaming === true}
          showStartNote={investigationFlowStart}
        />
      ) : isProgressMessage ? (
        <div class="deck-progress-note" role="status">
          <span class="deck-progress-note-mark" aria-hidden="true">
            {String((progressIndex ?? 0) + 1).padStart(2, "0")}
          </span>
          <div class="deck-progress-note-body">
            <strong>
              {t((progressIndex ?? 0) === 0
                ? "deck.investigation.startingWork"
                : "deck.investigation.progressUpdate")}
            </strong>
            <p>{turn.text}</p>
          </div>
        </div>
      ) : isDeck ? (
        <GroundedReply
          turnId={turn.id}
          text={turn.text}
          citations={turn.citations}
          source={turn.source}
          streaming={turn.streaming === true}
          verification={turn.verification}
          confirmed={turn.confirmed}
          verificationProgress={turn.verificationProgress}
          answerPlanning={turn.answerPlanning}
          delegation={turn.delegation}
          codeArtifacts={turn.codeArtifacts}
          incidentCandidates={turn.incidentCandidates}
          actionDraft={turn.actionDraft}
          trajectory={trajectory}
          {...(onRegenerate ? { onRegenerate } : {})}
        />
      ) : (
        <div class="deck-turn-body">
          {turn.attachments && turn.attachments.length > 0 ? (
            <ConversationTurnAttachments attachments={turn.attachments} />
          ) : null}
          {turn.text.split("\n").map((line, index) => (
            <p key={index} class="deck-turn-line">{line}</p>
          ))}
        </div>
      )}
      {turn.followUps && turn.followUps.length > 0 ? (
        <ul class="deck-followups" aria-label={t("deck.suggestedFollowUps")}>
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
      {trajectory && !turn.streaming ? (
        <ConversationTrajectoryView
          trajectory={trajectory}
          showModelTrace={showModelTrace}
        />
      ) : null}
      {!isInvestigationFlow ? (
        <div class="deck-turn-foot">
          <span class="deck-turn-time muted">{turn.at}</span>
        </div>
      ) : null}
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
          <span class="deck-backend-label">{t("deck.backend.probing")}</span>
        </span>
      </Tooltip>
    );
  }
  if (health.available) {
    const label = t("deck.backend.connected");
    return (
      <Tooltip content={<BackendTooltipContent health={health} />} variant="backend">
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
        <span class="deck-backend-label">{t("deck.backend.deterministic")}</span>
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
  const verticals = verticalQuickStarts();
  return (
    <div class="deck-intro">
      <p class="deck-intro-lead">{t("deck.intro")}</p>
      <div class="deck-intro-verticals" aria-label={t("deck.verticalQuickStarts.label")}>
        <span>{t("deck.verticalQuickStarts.label")}</span>
        {verticals.map((vertical) => (
          <button
            key={vertical.key}
            type="button"
            class="deck-vertical-suggest"
            onClick={() => onPick(vertical.prompt)}
          >
            {vertical.label}
          </button>
        ))}
      </div>
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

export function verticalQuickStarts(): readonly Readonly<{
  key: "resilience" | "changeSafety" | "costGovernance";
  label: string;
  prompt: string;
}>[] {
  return [
    {
      key: "resilience",
      label: t("deck.verticalQuickStarts.resilience"),
      prompt: t("deck.verticalQuickStarts.resiliencePrompt"),
    },
    {
      key: "changeSafety",
      label: t("deck.verticalQuickStarts.changeSafety"),
      prompt: t("deck.verticalQuickStarts.changeSafetyPrompt"),
    },
    {
      key: "costGovernance",
      label: t("deck.verticalQuickStarts.costGovernance"),
      prompt: t("deck.verticalQuickStarts.costGovernancePrompt"),
    },
  ];
}

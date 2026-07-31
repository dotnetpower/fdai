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
  type GroundedCodeArtifact,
  type InvestigationActivity,
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
  conversationGroups,
  isScreenConversationKey,
  type ConversationSummary,
} from "./conversation-sessions";
import { useViewContext } from "./context";
import type { ConversationTrajectory } from "./conversation-trajectory";
import { ConversationTrajectoryView } from "./conversation-trajectory-view";
import { GroundedReply } from "./grounded-reply";
import { InvestigationTimeline } from "./investigation-timeline";
import { introSuggestions } from "./intro-suggestions";

export interface Turn {
  readonly id: string;
  readonly role: "operator" | "deck";
  readonly text: string;
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
  readonly actionDraft?: ActionDraft;
  readonly modelTrace?: ModelTrace;
  readonly turnTiming?: TurnTiming;
  readonly trajectoryDetail?: TrajectoryDetail;
  readonly resourceContext?: ResourceContext;
  readonly agent?: string;
  readonly at: string;
}

export const DEFAULT_NARRATOR = "Bragi";

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

function routerTooltip(router: RouterSnapshot | undefined): string | undefined {
  if (!router) return undefined;
  const lines = router.candidates.map((candidate) => {
    const p50 = candidate.p50_ms === null ? "-" : `${Math.round(candidate.p50_ms)}ms`;
    const p95 = candidate.p95_ms === null ? "-" : `${Math.round(candidate.p95_ms)}ms`;
    const marker = candidate.deployment === router.chose ? "* " : "  ";
    return `${marker}${candidate.deployment} · p50 ${p50} · p95 ${p95} · n=${candidate.samples}`;
  });
  return `${t("deck.tooltip.routerChoice", { reason: router.reason, deployment: router.chose })}\n${lines.join("\n")}`;
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
  trajectory,
  showModelTrace,
  onPickFollowUp,
  onRegenerate,
  searchMatch,
  activeSearchMatch,
}: {
  readonly turn: Turn;
  readonly trajectory?: ConversationTrajectory;
  readonly showModelTrace: boolean;
  readonly onPickFollowUp: (text: string) => void;
  readonly onRegenerate?: () => void;
  readonly searchMatch: boolean;
  readonly activeSearchMatch: boolean;
}) {
  const isDeck = turn.role === "deck";
  const isActivity = turn.kind === "activity";
  const isProgressMessage = turn.kind === "message" && turn.source === "investigation";
  return (
    <article
      id={`deck-turn-${turn.id}`}
      class={`deck-turn deck-turn-${turn.role}${turn.source === "context" ? " is-context" : ""}${turn.streaming ? " is-streaming" : ""}${searchMatch ? " is-search-match" : ""}${activeSearchMatch ? " is-active-search-match" : ""}`}
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
            {replyAgentLabel(turn.agent ?? DEFAULT_NARRATOR, turn.delegation)}
          </span>
          {turn.source && !isProgressMessage && !isActivity ? (
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
        />
      ) : isProgressMessage ? (
        <div class="deck-progress-note" role="status">
          <span class="deck-progress-note-mark" aria-hidden="true" />
          <p>{turn.text}</p>
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
          answerPlan={turn.answerPlan}
          answerPlanning={turn.answerPlanning}
          delegation={turn.delegation}
          codeArtifacts={turn.codeArtifacts}
          actionDraft={turn.actionDraft}
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
          <span class="deck-backend-label">{t("deck.backend.probing")}</span>
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
        : t("deck.backend.ready");
      const base = `${t("deck.tooltip.chatMode", { mode: health.mode })}${
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
  return (
    <div class="deck-intro">
      <p class="deck-intro-lead">{t("deck.intro")}</p>
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

import { conversationContextMode, conversationPath, type ConversationSummary } from "./conversation-sessions";

interface ConversationNavigationActions {
  readonly navigate: (path: string) => void;
  readonly activate: (conversation: ConversationSummary) => void;
  readonly focus: () => void;
}

interface MutableBooleanRef {
  current: boolean;
}

/** Suppress only the synchronous route event emitted by a conversation-origin navigation. */
export function runConversationRouteNavigation(
  path: string,
  navigating: MutableBooleanRef,
  navigate: (path: string) => void,
): void {
  navigating.current = true;
  try {
    navigate(path);
  } finally {
    navigating.current = false;
  }
}

/** Navigate to a conversation's screen without letting route policy leave the Deck closed. */
export function selectConversationWithRoute(
  conversation: ConversationSummary,
  currentPathname: string,
  activeKey: string,
  actions: ConversationNavigationActions,
): void {
  const changesRoute = conversation.kind !== "agent" &&
    conversationContextMode(conversation) === "screen" &&
    conversation.originPath !== conversationPath(currentPathname);
  if (!changesRoute && conversation.key === activeKey) {
    actions.focus();
    return;
  }
  if (changesRoute) actions.navigate(conversation.originPath);
  actions.activate(conversation);
  actions.focus();
}

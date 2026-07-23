import { conversationPath, type ConversationSummary } from "./conversation-sessions";

interface ConversationNavigationActions {
  readonly navigate: (path: string) => void;
  readonly activate: (conversation: ConversationSummary) => void;
  readonly reopen: () => void;
  readonly focus: () => void;
}

/** Navigate to a conversation's screen without letting route policy leave the Deck closed. */
export function selectConversationWithRoute(
  conversation: ConversationSummary,
  currentPathname: string,
  activeKey: string,
  actions: ConversationNavigationActions,
): void {
  const changesRoute = conversation.kind !== "agent" &&
    conversation.originPath !== conversationPath(currentPathname);
  if (!changesRoute && conversation.key === activeKey) {
    actions.focus();
    return;
  }
  if (changesRoute) actions.navigate(conversation.originPath);
  actions.activate(conversation);
  if (changesRoute) actions.reopen();
  actions.focus();
}

import type { OperatorApiClient } from "./api";
import { fetchHandoverInvitation } from "./handover-api";
import { openDeckWithContext } from "./deck/open-deck";
import { handoverText } from "./deck/handover-i18n";
export {
  decodeHandoverGoal,
  decodeHandoverInvitation,
  type HandoverGoal,
  type HandoverInvitation,
} from "./handover-model";
import type { HandoverInvitation } from "./handover-model";

const SESSION_KEY = "fdai.handover.login-session.v1";

export function handoverLoginSessionId(storage: Storage | null): string {
  const existing = storage?.getItem(SESSION_KEY)?.trim();
  if (existing) return existing;
  const generated = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `handover-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  storage?.setItem(SESSION_KEY, generated);
  return generated;
}

export async function offerProactiveHandover(
  client: OperatorApiClient,
  storage: Storage | null,
  load: typeof fetchHandoverInvitation = fetchHandoverInvitation,
): Promise<HandoverInvitation | null> {
  const invitation = await load(client, handoverLoginSessionId(storage));
  if (invitation === null) return null;
  openDeckWithContext({
    sessionKey: `handover:${invitation.goalId}`,
    sessionLabel: invitation.agentName,
    newConversation: false,
    targetAgent: invitation.agentName,
    onlyWhenIdle: true,
    openingBriefing: handoverText("opening", {
      agent: invitation.agentName,
      minutes: invitation.maxMinutes,
    }),
    contextNote: handoverText("opening", {
      agent: invitation.agentName,
      minutes: invitation.maxMinutes,
    }),
    prompt: handoverText("prompt", { agent: invitation.agentName }),
  });
  return invitation;
}

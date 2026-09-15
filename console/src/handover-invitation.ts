import type { OperatorApiClient } from "./api";
import { fetchHandoverInvitation } from "./handover-api";
import { openDeckWithContext } from "./deck/open-deck";
import { handoverText } from "./deck/handover-i18n";
import { handoverConversationKey, handoverLoginSessionId } from "./handover-session";
export { handoverConversationKey, handoverLoginSessionId } from "./handover-session";
export {
  decodeHandoverGoal,
  decodeHandoverInvitation,
  type HandoverGoal,
  type HandoverInvitation,
} from "./handover-model";
import type { HandoverInvitation } from "./handover-model";

export async function offerProactiveHandover(
  client: OperatorApiClient,
  storage: Storage | null,
  load: typeof fetchHandoverInvitation = fetchHandoverInvitation,
): Promise<HandoverInvitation | null> {
  const invitation = await load(client, handoverLoginSessionId(storage));
  if (invitation === null) return null;
  openDeckWithContext({
    sessionKey: handoverConversationKey(invitation.goalId, invitation.sessionId),
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

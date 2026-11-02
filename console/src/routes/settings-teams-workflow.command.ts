import type { AuthContext } from "../auth";
import { getGovernedJson, GovernedCommandError, putGovernedJson } from "../governed-command";
import {
  decodeTeamsWorkflowBindingReveal,
  decodeTeamsWorkflowBindingView,
  decodeTeamsWorkflowTestResult,
  type TeamsWorkflowBindingView,
  type TeamsWorkflowRevealedBinding,
  type TeamsWorkflowSubmitOptions,
  type TeamsWorkflowTestResult,
} from "./settings-teams-workflow.model";

export { GovernedCommandError as TeamsWorkflowTestCommandError };

export async function loadTeamsWorkflowBinding(
  auth: AuthContext,
  operatorApiBaseUrl: string,
): Promise<TeamsWorkflowBindingView> {
  return decodeTeamsWorkflowBindingView(
    await getGovernedJson(
      auth,
      operatorApiBaseUrl,
      "/runtime/integrations/teams-workflow/binding",
    ),
  );
}

export async function revealTeamsWorkflowBinding(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  channelId?: string,
): Promise<TeamsWorkflowRevealedBinding> {
  const query = channelId
    ? `?reveal=1&channel_id=${encodeURIComponent(channelId)}`
    : "?reveal=1";
  return decodeTeamsWorkflowBindingReveal(
    await getGovernedJson(
      auth,
      operatorApiBaseUrl,
      `/runtime/integrations/teams-workflow/binding${query}`,
    ),
  );
}

export async function testTeamsWorkflowWebhook(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  webhookUrl: string,
  requestId: string,
  options?: TeamsWorkflowSubmitOptions,
): Promise<TeamsWorkflowTestResult> {
  const body: Record<string, unknown> = {
    request_id: requestId,
    webhook_url: webhookUrl,
  };
  if (options?.channelLabel) {
    body["channel_label"] = options.channelLabel;
  }
  if (options?.selectedChannelIds) {
    body["selected_channel_ids"] = [...options.selectedChannelIds];
  }
  if (options?.deliveryTargets) {
    body["delivery_targets"] = [...options.deliveryTargets];
  }
  if (options?.removeChannelId) {
    body["remove_channel_id"] = options.removeChannelId;
  }
  if (options?.selectionOnly) {
    body["selection_only"] = true;
  }
  return decodeTeamsWorkflowTestResult(
    await putGovernedJson(
      auth,
      operatorApiBaseUrl,
      "/runtime/integrations/teams-workflow/test",
      body,
      "POST",
    ),
  );
}

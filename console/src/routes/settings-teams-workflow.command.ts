import type { AuthContext } from "../auth";
import { getGovernedJson, GovernedCommandError, putGovernedJson } from "../governed-command";
import {
  decodeTeamsWorkflowBindingSaveResult,
  decodeTeamsWorkflowBindingView,
  decodeTeamsWorkflowTestResult,
  type TeamsWorkflowBindingSaveResult,
  type TeamsWorkflowBindingView,
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

export async function testTeamsWorkflowWebhook(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  webhookUrl: string,
  requestId: string,
): Promise<TeamsWorkflowTestResult> {
  return decodeTeamsWorkflowTestResult(
    await putGovernedJson(
      auth,
      operatorApiBaseUrl,
      "/runtime/integrations/teams-workflow/test",
      {
        request_id: requestId,
        webhook_url: webhookUrl,
      },
      "POST",
    ),
  );
}

export async function saveTeamsWorkflowBinding(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  webhookUrl: string,
  requestId: string,
): Promise<TeamsWorkflowBindingSaveResult> {
  return decodeTeamsWorkflowBindingSaveResult(
    await putGovernedJson(
      auth,
      operatorApiBaseUrl,
      "/runtime/integrations/teams-workflow/binding",
      {
        request_id: requestId,
        webhook_url: webhookUrl,
      },
    ),
  );
}

export async function testSavedTeamsWorkflowBinding(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  requestId: string,
): Promise<TeamsWorkflowTestResult> {
  return decodeTeamsWorkflowTestResult(
    await putGovernedJson(
      auth,
      operatorApiBaseUrl,
      "/runtime/integrations/teams-workflow/test",
      { request_id: requestId },
      "POST",
    ),
  );
}

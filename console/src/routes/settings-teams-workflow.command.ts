import type { AuthContext } from "../auth";
import { GovernedCommandError, putGovernedJson } from "../governed-command";
import {
  decodeTeamsWorkflowTestResult,
  type TeamsWorkflowTestResult,
} from "./settings-teams-workflow.model";

export { GovernedCommandError as TeamsWorkflowTestCommandError };

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

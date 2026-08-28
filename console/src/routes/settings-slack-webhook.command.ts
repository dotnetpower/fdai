import type { AuthContext } from "../auth";
import { putGovernedJson } from "../governed-command";
import {
  decodeSlackWebhookTestResult,
  type SlackWebhookTestResult,
} from "./settings-slack-webhook.model";

export async function testSlackWebhook(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  webhookUrl: string,
  requestId: string,
): Promise<SlackWebhookTestResult> {
  return decodeSlackWebhookTestResult(
    await putGovernedJson(
      auth,
      operatorApiBaseUrl,
      "/runtime/integrations/slack-webhook/test",
      {
        request_id: requestId,
        webhook_url: webhookUrl,
      },
      "POST",
    ),
  );
}

import type { AuthContext } from "../auth";
import { GovernedCommandError, putGovernedJson } from "../governed-command";
import { decodeModelSettings, type ModelSettingsView } from "./settings-models.model";

export { GovernedCommandError as ModelSettingsCommandError };

export async function saveNarratorPreference(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  preferredNarratorModel: string,
  expectedRevision: number,
): Promise<ModelSettingsView> {
  return putModelSettings(auth, operatorApiBaseUrl, "/me/model-preferences", {
    preferred_narrator_model: preferredNarratorModel,
    expected_revision: expectedRevision,
  });
}

export async function saveWebSearchSettings(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  input: {
    readonly enabled: boolean;
    readonly allowedDomains: readonly string[];
    readonly expectedRevision: number;
  },
): Promise<ModelSettingsView> {
  return putModelSettings(auth, operatorApiBaseUrl, "/models/web-search-settings", {
    enabled: input.enabled,
    allowed_domains: [...input.allowedDomains],
    expected_revision: input.expectedRevision,
  });
}

async function putModelSettings(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  path: string,
  body: Record<string, unknown>,
): Promise<ModelSettingsView> {
  return decodeModelSettings(await putGovernedJson(auth, operatorApiBaseUrl, path, body));
}

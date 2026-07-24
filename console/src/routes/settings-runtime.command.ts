import type { AuthContext } from "../auth";
import { GovernedCommandError, putGovernedJson } from "../governed-command";
import {
  decodeRuntimeSettings,
  type RuntimeSettingsView,
  type RuntimeSettingValue,
} from "./settings-runtime.model";

export { GovernedCommandError as RuntimeSettingsCommandError };

export async function saveRuntimeSettings(
  auth: AuthContext,
  readApiBaseUrl: string,
  changes: Readonly<Record<string, RuntimeSettingValue | null>>,
  expectedRevision: number,
): Promise<RuntimeSettingsView> {
  return decodeRuntimeSettings(
    await putGovernedJson(auth, readApiBaseUrl, "/runtime/settings", {
      changes: { ...changes },
      expected_revision: expectedRevision,
    }),
  );
}

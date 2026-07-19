import type { AuthContext } from "./auth";
import type { IamSelfStatus } from "./routes/settings-iam.model";

export function shouldLoadIamSelf(auth: AuthContext): boolean {
  return auth.account !== null;
}

export function shouldAllowLocalDevBypass(auth: AuthContext): boolean {
  return auth.devMode && auth.interactiveSignIn !== true && auth.account === null;
}

export function shouldShowAccessRequired(
  auth: AuthContext,
  iamSelf: IamSelfStatus | undefined,
): boolean {
  return auth.account !== null && iamSelf?.canAccessConsole === false;
}

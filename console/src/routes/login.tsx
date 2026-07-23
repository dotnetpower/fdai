import type { AuthContext } from "../auth";
import { useState } from "preact/hooks";
import { NebulaBackground } from "../components/nebula-background";
import { t } from "../i18n";

interface AccessRecovery {
  readonly error: string;
  readonly retry: () => Promise<void>;
}

interface LoginRouteProps {
  readonly auth: AuthContext;
  readonly allowDevBypass?: boolean;
  readonly onDevBypass?: () => Promise<void>;
  readonly accessRecovery?: AccessRecovery;
}

export function loginRouteMode(
  allowDevBypass: boolean,
  accessRecovery: AccessRecovery | undefined,
): "access-recovery" | "local" | "sign-in" {
  if (accessRecovery) return "access-recovery";
  return allowDevBypass ? "local" : "sign-in";
}

/**
 * Sign-in screen. A procedural WebGL nebula backdrop (the same shader the
 * landing site uses) with a centered glass card carrying the FDAI title and
 * the Entra sign-in button. The nebula is decorative (`aria-hidden`) and
 * degrades to the CSS deep-space fallback when WebGL is unavailable.
 */
export function LoginRoute({
  auth,
  allowDevBypass = false,
  onDevBypass,
  accessRecovery,
}: LoginRouteProps) {
  const mode = loginRouteMode(allowDevBypass, accessRecovery);
  const [signingIn, setSigningIn] = useState(false);
  const [checkingDev, setCheckingDev] = useState(false);
  const [checkingAccess, setCheckingAccess] = useState(false);
  const [error, setError] = useState<string | null>(accessRecovery?.error ?? null);

  const signIn = async () => {
    setSigningIn(true);
    setError(null);
    try {
      await auth.signIn();
    } catch (reason) {
      setError(t("login.signInFailed", {
        error: reason instanceof Error ? reason.message : String(reason),
      }));
      setSigningIn(false);
    }
  };

  const continueDev = async () => {
    if (!onDevBypass) return;
    setCheckingDev(true);
    setError(null);
    try {
      await onDevBypass();
    } catch (reason) {
      setError(t("login.devBypassFailed", {
        error: reason instanceof Error ? reason.message : String(reason),
      }));
    } finally {
      setCheckingDev(false);
    }
  };

  const retryAccess = async () => {
    if (!accessRecovery) return;
    setCheckingAccess(true);
    setError(null);
    try {
      await accessRecovery.retry();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setCheckingAccess(false);
    }
  };

  return (
    <div class="login-cosmos">
      <NebulaBackground intensity={1.05} speed={1} class="login-nebula" />

      <main class="login-panel" role="main">
        <p class="login-eyebrow">
          {mode === "local" ? t("login.localEyebrow") : t("login.eyebrow")}
        </p>
        <h1 class="login-title">FDAI Console</h1>
        <p class="login-subtitle">
          {mode === "access-recovery"
            ? t("accessRequired.checkFailed")
            : mode === "local"
              ? t("login.localSubtitle")
              : t("login.subtitle")}
        </p>

        <div class="login-actions">
          {mode === "access-recovery" ? (
            <button
              type="button"
              class="login-signin"
              disabled={signingIn || checkingAccess}
              onClick={() => { void retryAccess(); }}
            >
              <span>
                {checkingAccess ? t("accessRequired.checking") : t("accessRequired.retry")}
              </span>
            </button>
          ) : auth.interactiveSignIn ? (
            <button
              type="button"
              class="login-signin"
              disabled={signingIn || checkingDev}
              onClick={() => { void signIn(); }}
            >
              <svg viewBox="0 0 21 21" width="18" height="18" aria-hidden="true">
                <rect x="1" y="1" width="9" height="9" fill="#f25022" />
                <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
                <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
                <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
              </svg>
              <span>{signingIn ? t("login.signingIn") : t("login.signInEntra")}</span>
            </button>
          ) : null}
          {mode === "access-recovery" && auth.interactiveSignIn ? (
            <button
              type="button"
              class="login-bypass"
              disabled={signingIn || checkingAccess}
              onClick={() => { void signIn(); }}
            >
              {signingIn ? t("login.signingIn") : t("login.signInAgain")}
            </button>
          ) : null}
          {allowDevBypass && onDevBypass ? (
            <button
              type="button"
              class="login-bypass"
              disabled={signingIn || checkingDev}
              onClick={() => { void continueDev(); }}
            >
              {checkingDev ? t("login.checkingDev") : t("login.continueDev")}
            </button>
          ) : null}
        </div>

        {error ? <p class="login-error mono" role="alert">{error}</p> : null}

        <p class="login-foot">
          {mode === "access-recovery"
            ? t("accessRequired.recoveryHint")
            : mode === "local"
              ? t("login.localFoot")
              : t("login.foot")}
        </p>
      </main>
    </div>
  );
}

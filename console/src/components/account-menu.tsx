import { useEffect, useRef, useState } from "preact/hooks";
import type { AuthContext } from "../auth";
import { panelPath } from "../router";
import type { IamRole, IamSelfStatus } from "../routes/settings-iam.model";
import { accountMenuText } from "./account-menu.i18n";

interface AccountMenuProps {
  readonly auth: AuthContext;
  readonly iamSelf: IamSelfStatus | undefined;
}

type PendingAccountAction = "switch" | "sign-out";

export function accountInitials(name: string | undefined, username: string): string {
  const nameParts = name?.trim().split(/\s+/).filter(Boolean) ?? [];
  const parts = nameParts.length > 0
    ? nameParts
    : username.split("@", 1)[0]?.split(/[._\-\s]+/).filter(Boolean) ?? [];
  const selected = parts.length > 1 ? [parts[0], parts.at(-1)] : parts.slice(0, 1);
  const initials = selected
    .flatMap((part) => Array.from(part ?? "").slice(0, 1))
    .join("")
    .toUpperCase();
  return initials || "?";
}

export function verifiedAccountRoles(iamSelf: IamSelfStatus | undefined): readonly IamRole[] | null {
  return iamSelf?.principal.roles ?? null;
}

export function accountSessionLabel(auth: AuthContext): string {
  if (auth.localAzureCli) return accountMenuText("azureCli");
  if (auth.devMode) return accountMenuText("localEntra");
  return accountMenuText("entra");
}

export function AccountMenu({ auth, iamSelf }: AccountMenuProps) {
  const account = auth.account;
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<PendingAccountAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const firstActionRef = useRef<HTMLAnchorElement | null>(null);
  const actionInFlightRef = useRef(false);

  useEffect(() => {
    if (!open) return;
    const focusFrame = window.requestAnimationFrame(() => firstActionRef.current?.focus());
    const dismissOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node | null)) {
        setOpen(false);
        setError(null);
      }
    };
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      setError(null);
      window.requestAnimationFrame(() => triggerRef.current?.focus());
    };
    document.addEventListener("pointerdown", dismissOutside);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("pointerdown", dismissOutside);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, [open]);

  if (!account) return null;

  const displayName = account.name?.trim() || account.username;
  const roles = verifiedAccountRoles(iamSelf);
  const canUseInteractiveAuth = auth.interactiveSignIn === true;

  const runAction = async (
    action: PendingAccountAction,
    operation: () => Promise<void>,
  ): Promise<void> => {
    if (actionInFlightRef.current) return;
    actionInFlightRef.current = true;
    setPending(action);
    setError(null);
    try {
      await operation();
    } catch (reason) {
      console.warn("account_menu_action_failed", {
        action,
        error_name: reason instanceof Error ? reason.name : "unknown",
      });
      setError(accountMenuText("actionFailed"));
    } finally {
      actionInFlightRef.current = false;
      setPending(null);
    }
  };

  return (
    <div ref={rootRef} class="account-menu">
      <button
        ref={triggerRef}
        type="button"
        class="account-menu-trigger"
        aria-label={accountMenuText("open", { username: account.username })}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => {
          setOpen((current) => !current);
          setError(null);
        }}
        onKeyDown={(event) => {
          if (event.key !== "ArrowDown") return;
          event.preventDefault();
          setOpen(true);
          setError(null);
        }}
      >
        <span class="account-avatar account-avatar-small" aria-hidden="true">
          {accountInitials(account.name, account.username)}
        </span>
        <span class="account-trigger-copy">
          <strong>{displayName}</strong>
          <small>{account.username}</small>
        </span>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>

      {open ? (
        <section
          class="account-menu-panel"
          role="dialog"
          aria-label={accountMenuText("dialogLabel")}
        >
          <div class="account-menu-heading">
            <span class="account-avatar" aria-hidden="true">
              {accountInitials(account.name, account.username)}
            </span>
            <div>
              <span>{accountMenuText("signedInAs")}</span>
              <strong>{displayName}</strong>
              <small>{account.username}</small>
              <small>{accountSessionLabel(auth)}</small>
            </div>
          </div>

          <div class="account-role-summary">
            <span>{accountMenuText("verifiedRoles")}</span>
            {roles === null ? (
              <small>{accountMenuText("rolesUnavailable")}</small>
            ) : roles.length === 0 ? (
              <small>{accountMenuText("noRoles")}</small>
            ) : (
              <div class="account-role-list">
                {roles.map((role) => <span key={role}>{role}</span>)}
              </div>
            )}
          </div>

          <div class="account-menu-actions">
            <a
              ref={firstActionRef}
              href={panelPath("settings-iam")}
              onClick={() => setOpen(false)}
            >
              {accountMenuText("myAccess")}
            </a>
            {canUseInteractiveAuth ? (
              <>
                <button
                  type="button"
                  disabled={pending !== null}
                  onClick={() => {
                    void runAction("switch", () => auth.signIn({ selectAccount: true }));
                  }}
                >
                  {pending === "switch"
                    ? accountMenuText("switchingAccount")
                    : accountMenuText("switchAccount")}
                </button>
                <button
                  type="button"
                  disabled={pending !== null}
                  onClick={() => {
                    void runAction("sign-out", () => auth.signOut());
                  }}
                >
                  {pending === "sign-out"
                    ? accountMenuText("signingOut")
                    : accountMenuText("signOut")}
                </button>
              </>
            ) : null}
          </div>
          {error ? <p class="account-menu-error" role="alert">{error}</p> : null}
        </section>
      ) : null}
    </div>
  );
}

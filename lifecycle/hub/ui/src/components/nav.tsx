import { useEffect, useRef, useState } from "preact/hooks";
import {
  getEntraSession,
  refreshEntraSession,
  requestEntraLogin,
  requestEntraLogout,
  subscribeEntraSession,
  type EntraSessionStatus,
} from "../auth";
import { installationsPath, type Route } from "../router";
import { tr, useHubLocale } from "../locale";
import { Link } from "./link";
import { InstallationsIcon } from "./nav-icons";

export function useEntraSession(): EntraSessionStatus | null {
  const [state, setState] = useState<EntraSessionStatus | null>(() => getEntraSession());
  useEffect(() => subscribeEntraSession(() => setState(getEntraSession())), []);
  return state;
}

function isOnInstallations(route: Route): boolean {
  return route.kind === "installations" || route.kind === "installation" || route.kind === "plan";
}

export function Nav({ route }: { route: Route }) {
  const [locale, setLocale] = useHubLocale();
  const entraStatus = useEntraSession();
  const [entraDialogOpen, setEntraDialogOpen] = useState(false);
  const [principalInput, setPrincipalInput] = useState("");
  const [tenantInput, setTenantInput] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (!entraDialogOpen) return;
    dialogRef.current?.showModal();
    void refreshEntraSession().then((latest) => {
      const def = latest?.detected_accounts?.[0];
      if (def) {
        setPrincipalInput((prev) => prev || def.principal);
        setTenantInput((prev) => prev || def.tenant_id);
      }
    });
    return () => {
      dialogRef.current?.close();
    };
  }, [entraDialogOpen]);

  async function handleWorkstationSignIn(principal?: string, tenantId?: string, label?: string) {
    setAuthBusy(true);
    setAuthError("");
    try {
      await requestEntraLogin({
        mode: "workstation",
        principal: (principal ?? principalInput).trim(),
        tenant_id: (tenantId ?? tenantInput).trim(),
        display_name: label ?? "",
      });
      setEntraDialogOpen(false);
    } catch (failure) {
      setAuthError(failure instanceof Error ? failure.message : "Entra ID sign-in failed.");
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleSignOut() {
    setAuthBusy(true);
    setAuthError("");
    try {
      await requestEntraLogout();
    } finally {
      setAuthBusy(false);
    }
  }

  return (
    <nav class="side" aria-label="Lifecycle Hub">
      <div class="brand">
        <img class="brand-logo" src={`${import.meta.env.BASE_URL}brand/fdai-logo.png`} alt="" />
        <span class="brand-wordmark">FDAI</span>
        <span class="brand-separator" aria-hidden="true" />
        <span class="brand-product">Lifecycle Hub</span>
      </div>
      <div class="side-section-label">
        {tr(locale, "Console installations", "Console 설치 환경")}
      </div>
      <Link
        href={installationsPath()}
        class={`it ${isOnInstallations(route) ? "on" : ""}`}
        aria-current={isOnInstallations(route) ? "page" : undefined}
      >
        <InstallationsIcon />
        {tr(locale, "Installations", "설치 환경")}
      </Link>
      <div class="side-divider" role="separator" />
      <div class="side-entra">
        <div class="side-entra-row">
          <span class="side-entra-status">
            <span class={`side-dot ${entraStatus?.authenticated ? "ok" : "warn"}`} aria-hidden="true" />
            <strong>
              {entraStatus?.authenticated && entraStatus.session
                ? entraStatus.session.principal
                : tr(locale, "Not signed in", "Entra ID 미로그인")}
            </strong>
          </span>
        </div>
        <div class="side-entra-actions">
          {entraStatus?.authenticated ? (
            <>
              <button
                type="button"
                class="btn"
                onClick={() => setEntraDialogOpen(true)}
                disabled={authBusy}
              >
                {tr(locale, "Account", "계정 전환")}
              </button>
              <button
                type="button"
                class="btn"
                onClick={() => void handleSignOut()}
                disabled={authBusy}
              >
                {tr(locale, "Sign out", "로그아웃")}
              </button>
            </>
          ) : (
            <button
              type="button"
              class="btn primary"
              onClick={() => setEntraDialogOpen(true)}
              disabled={authBusy}
            >
              {tr(locale, "Sign in with Entra ID", "Entra ID 로그인")}
            </button>
          )}
        </div>
      </div>
      <div class="side-locale">
        <span>{tr(locale, "Language", "언어")}</span>
        <button
          type="button"
          class="btn"
          aria-label="Switch workspace language"
          onClick={() => setLocale(locale === "en" ? "ko" : "en")}
        >
          {locale === "en" ? "한국어" : "English"}
        </button>
      </div>
      {entraDialogOpen && (
        <dialog
          ref={dialogRef}
          class="entra-dialog"
          aria-labelledby="hub-entra-dialog-title"
          onClose={() => setEntraDialogOpen(false)}
        >
          <h2 id="hub-entra-dialog-title" class="panel-title">
            {tr(locale, "Microsoft Entra ID Operator Sign-In", "Microsoft Entra ID 운영자 로그인")}
          </h2>
          <p class="note">
            {tr(
              locale,
              "Bind your Microsoft Entra ID operator identity for execution schedule changes, application binding, and audit attribution.",
              "실행 일정 변경, 애플리케이션 바인딩 및 감사 기록 귀속을 위해 Microsoft Entra ID 운영자 계정을 연결합니다.",
            )}
          </p>
          {authError && <p class="banner fail" role="alert">{authError}</p>}
          {(entraStatus?.detected_accounts?.length ?? 0) > 0 && (
            <div class="entra-detected-list">
              <strong class="soft">
                {tr(locale, "Detected Workstation Accounts (az login)", "감지된 로컬 워크스테이션 계정 (az login)")}
              </strong>
              {(entraStatus?.detected_accounts ?? []).map((acct) => (
                <div key={`${acct.principal}-${acct.tenant_id}`} class="entra-detected-item">
                  <div>
                    <div><strong>{acct.principal}</strong></div>
                    <div class="soft mono">{acct.tenant_label} ({acct.tenant_id.slice(0, 8)}...)</div>
                  </div>
                  <button
                    type="button"
                    class="btn primary"
                    disabled={authBusy}
                    onClick={() => void handleWorkstationSignIn(acct.principal, acct.tenant_id, `${acct.principal} (${acct.tenant_label})`)}
                  >
                    {tr(locale, "1-Click Sign In", "원클릭 로그인")}
                  </button>
                </div>
              ))}
            </div>
          )}
          <details open={(entraStatus?.detected_accounts?.length ?? 0) === 0}>
            <summary>{tr(locale, "Sign in with custom UPN and Tenant ID", "직접 UPN 및 테넌트 ID 입력")}</summary>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void handleWorkstationSignIn();
              }}
            >
              <label>
                {tr(locale, "Operator UPN / Email", "운영자 UPN / 이메일")}
                <input
                  class="input"
                  required
                  value={principalInput}
                  placeholder="operator@microsoft.com"
                  onInput={(event) => setPrincipalInput(event.currentTarget.value)}
                />
              </label>
              <label>
                {tr(locale, "Entra Tenant ID (UUID)", "Entra 테넌트 ID (UUID)")}
                <input
                  class="input mono"
                  required
                  value={tenantInput}
                  placeholder="00000000-0000-0000-0000-000000000000"
                  onInput={(event) => setTenantInput(event.currentTarget.value)}
                />
              </label>
              <div class="acts" style={{ marginTop: "8px" }}>
                <button type="submit" class="btn primary" disabled={authBusy}>
                  {tr(locale, "Sign in", "로그인")}
                </button>
              </div>
            </form>
          </details>
          <div class="acts" style={{ marginTop: "12px", justifyContent: "flex-end" }}>
            <button type="button" class="btn" onClick={() => setEntraDialogOpen(false)}>
              {tr(locale, "Close", "닫기")}
            </button>
          </div>
        </dialog>
      )}
    </nav>
  );
}

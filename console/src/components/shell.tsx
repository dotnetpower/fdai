import type { ComponentChildren } from "preact";
import type { AuthContext } from "../auth";

interface ShellProps {
  readonly view: "dashboard" | "audit" | "hil-queue";
  readonly auth: AuthContext;
  readonly children: ComponentChildren;
}

function navLink(target: string, label: string, active: boolean) {
  return (
    <a href={`#/${target}`} class={active ? "active" : ""}>
      {label}
    </a>
  );
}

export function Shell({ view, auth, children }: ShellProps) {
  return (
    <div class="shell">
      <header class="topbar">
        <h1>AIOpsPilot Console</h1>
        <nav>
          {navLink("dashboard", "Dashboard", view === "dashboard")}
          {navLink("audit", "Audit", view === "audit")}
          {navLink("hil-queue", "HIL Queue", view === "hil-queue")}
        </nav>
        <div class="principal">
          {auth.devMode ? (
            <span class="badge">dev mode</span>
          ) : auth.account ? (
            <>
              <span>{auth.account.username}</span>
              <button
                type="button"
                onClick={() => {
                  void auth.signOut();
                }}
              >
                Sign out
              </button>
            </>
          ) : null}
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}

import type { ComponentChildren } from "preact";
import type { AuthContext } from "../auth";
import { resolvePanels } from "../panels";

interface ShellProps {
  readonly activePanelId: string;
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

export function Shell({ activePanelId, auth, children }: ShellProps) {
  return (
    <div class="shell">
      <header class="topbar">
        <h1>AIOpsPilot Console</h1>
        <nav>
          {resolvePanels().map((panel) =>
            navLink(panel.id, panel.label, panel.id === activePanelId),
          )}
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

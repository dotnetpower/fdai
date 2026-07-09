import type { AuthContext } from "../auth";
import { NebulaBackground } from "../components/nebula-background";

/**
 * Sign-in screen. A procedural WebGL nebula backdrop (the same shader the
 * landing site uses) with a centered glass card carrying the FDAI title and
 * the Entra sign-in button. The nebula is decorative (`aria-hidden`) and
 * degrades to the CSS deep-space fallback when WebGL is unavailable.
 */
export function LoginRoute({ auth }: { readonly auth: AuthContext }) {
  return (
    <div class="login-cosmos">
      <NebulaBackground intensity={1.05} speed={1} class="login-nebula" />

      <main class="login-card" role="main">
        <p class="login-eyebrow">Operator sign-in</p>
        <h1 class="login-title">FDAI Console</h1>
        <p class="login-subtitle">Autonomous cloud operations control plane</p>

        <button
          type="button"
          class="login-signin"
          onClick={() => {
            void auth.signIn();
          }}
        >
          <svg viewBox="0 0 21 21" width="18" height="18" aria-hidden="true">
            <rect x="1" y="1" width="9" height="9" fill="#f25022" />
            <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
            <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
            <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
          </svg>
          <span>Sign in with Entra ID</span>
        </button>

        <p class="login-foot">
          Read-only operator console. Changes are delivered as remediation PRs
          and high-risk actions require human approval.
        </p>
      </main>
    </div>
  );
}

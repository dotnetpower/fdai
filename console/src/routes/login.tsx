import type { AuthContext } from "../auth";

export function LoginRoute({ auth }: { readonly auth: AuthContext }) {
  return (
    <div class="empty">
      <p>Sign in to view the operator console.</p>
      <button
        type="button"
        class="primary"
        onClick={() => {
          void auth.signIn();
        }}
      >
        Sign in with Entra ID
      </button>
    </div>
  );
}

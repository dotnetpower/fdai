import { hubApi } from "../api";
import { useAsync } from "../hooks/use-async";
import { enrollmentsPath, installationsPath, type Route } from "../router";
import { Link } from "./link";

const DISABLED: Record<string, readonly string[]> = {
  Catalog: ["Available Releases", "Custom channels", "Configuration packages"],
  Admin: ["Customer Git configuration", "Confirmations", "Commands", "Audit"],
};

function isOnInstallations(route: Route): boolean {
  return route.kind === "installations" || route.kind === "installation" || route.kind === "plan";
}

function isOnEnrollments(route: Route): boolean {
  return route.kind === "enrollments" || route.kind === "enrollment";
}

export function Nav({ route }: { route: Route }) {
  // Refetch on every navigation so the counts don't go stale after an approve/reject action.
  const installations = useAsync(() => hubApi.listInstallations(), [route]);
  const pending = useAsync(() => hubApi.listPendingEnrollments(), [route]);

  return (
    <nav class="side" aria-label="Lifecycle Hub">
      <div class="brand">FDAI Lifecycle Hub</div>
      <div class="grp">Operate</div>
      <Link
        href={installationsPath()}
        class={`it ${isOnInstallations(route) ? "on" : ""}`}
        aria-current={isOnInstallations(route) ? "page" : undefined}
      >
        <span>Installations</span>
        {installations.status === "ready" && (
          <span class="cnt">{installations.data.installations.length}</span>
        )}
      </Link>
      <div class="grp">Catalog</div>
      {DISABLED.Catalog!.map((label) => (
        <span key={label} class="it disabled" aria-disabled="true">
          {label}
        </span>
      ))}
      <div class="grp">Admin</div>
      <Link
        href={enrollmentsPath()}
        class={`it ${isOnEnrollments(route) ? "on" : ""}`}
        aria-current={isOnEnrollments(route) ? "page" : undefined}
      >
        <span>Enrollment requests</span>
        {pending.status === "ready" && <span class="cnt">{pending.data.enrollments.length}</span>}
      </Link>
      {DISABLED.Admin!.map((label) => (
        <span key={label} class="it disabled" aria-disabled="true">
          {label}
        </span>
      ))}
    </nav>
  );
}

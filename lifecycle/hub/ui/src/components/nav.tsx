import {
  availableReleasesPath, configurationPackagesPath, enrollmentsPath, installationsPath, type Route,
} from "../router";
import { Link } from "./link";
import { EnrollmentsIcon, InstallationsIcon } from "./nav-icons";

function isOnInstallations(route: Route): boolean {
  return route.kind === "installations" || route.kind === "installation" || route.kind === "plan";
}

function isOnEnrollments(route: Route): boolean {
  return route.kind === "enrollments" || route.kind === "enrollment";
}

/** Hub surfaces with no backend yet (see hub-managed-lifecycle.md "Remaining work").
 * Listed so an operator can see the Hub's full intended footprint, same as the approved
 * mockup, but inert: no link, no hover state, nothing to click. */
const UNBUILT_SURFACES = [
  "Confirmations",
  "Commands",
  "Custom channels",
  "Audit",
];

export function Nav({ route }: { route: Route }) {
  return (
    <nav class="side" aria-label="Lifecycle Hub">
      <div class="brand">
        <img class="brand-logo" src={`${import.meta.env.BASE_URL}brand/fdai-logo.png`} alt="" />
        <span class="brand-wordmark">FDAI</span>
        <span class="brand-separator" aria-hidden="true" />
        <span class="brand-product">Lifecycle Hub</span>
      </div>
      <Link
        href={installationsPath()}
        class={`it ${isOnInstallations(route) ? "on" : ""}`}
        aria-current={isOnInstallations(route) ? "page" : undefined}
      >
        <InstallationsIcon />
        Installations
      </Link>
      <Link
        href={enrollmentsPath()}
        class={`it ${isOnEnrollments(route) ? "on" : ""}`}
        aria-current={isOnEnrollments(route) ? "page" : undefined}
      >
        <EnrollmentsIcon />
        Enrollment requests
      </Link>
      <div class="side-divider" role="separator" />
      <Link href="/catalog" class={`it ${route.kind === "catalog" ? "on" : ""}`}
        aria-current={route.kind === "catalog" ? "page" : undefined}>Catalog import</Link>
      <Link href={availableReleasesPath()} class={`it ${route.kind === "releases" ? "on" : ""}`}
        aria-current={route.kind === "releases" ? "page" : undefined}>Available releases</Link>
      <Link href={configurationPackagesPath()} class={`it ${route.kind === "configurations" ? "on" : ""}`}
        aria-current={route.kind === "configurations" ? "page" : undefined}>Configuration packages</Link>
      {UNBUILT_SURFACES.map((label) => (
        <span key={label} class="it disabled" aria-disabled="true" title="Not available yet">
          {label}
        </span>
      ))}
    </nav>
  );
}

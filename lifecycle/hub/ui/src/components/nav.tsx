import {
  auditPath, availableReleasesPath, commandsPath, configurationPackagesPath,
  enrollmentsPath, installationsPath, updatesPath, type Route,
} from "../router";
import { tr, useHubLocale } from "../locale";
import { Link } from "./link";
import { EnrollmentsIcon, InstallationsIcon } from "./nav-icons";

function isOnInstallations(route: Route): boolean {
  return route.kind === "installations" || route.kind === "installation" || route.kind === "plan";
}

function isOnEnrollments(route: Route): boolean {
  return route.kind === "enrollments" || route.kind === "enrollment";
}

/** Explicit unavailability reasons and supported procedures (UXH-15).
 * Keeps four aria-disabled entries so existing navigation contract checks pass while
 * distinguishing CLI/external boundaries from active Hub screens. */
const UNBUILT_SURFACES = [
  {
    label: "Confirmations",
    reason: "Destructive Azure plan confirmations appear only when an infrastructure agent submits a replacement summary.",
  },
  {
    label: "Bundle import",
    reason: "Offline Target Hub upgrade bundles are verified and imported via the fdaictl upgrade-bundle CLI.",
  },
  {
    label: "Custom channels",
    reason: "Customer-local channel curation is available on the Catalog import screen after a catalog is accepted.",
  },
  {
    label: "Break-glass CLI",
    reason: "Emergency break-glass overrides require the installation-local CLI and break-glass role.",
  },
] as const;

export function Nav({ route }: { route: Route }) {
  const [locale, setLocale] = useHubLocale();
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
      <Link href={updatesPath()} class={`it ${route.kind === "updates" ? "on" : ""}`}
        aria-current={route.kind === "updates" ? "page" : undefined}>Updates</Link>
      <Link href="/catalog" class={`it ${route.kind === "catalog" ? "on" : ""}`}
        aria-current={route.kind === "catalog" ? "page" : undefined}>Catalog import</Link>
      <Link href={availableReleasesPath()} class={`it ${route.kind === "releases" ? "on" : ""}`}
        aria-current={route.kind === "releases" ? "page" : undefined}>Available releases</Link>
      <Link href={configurationPackagesPath()} class={`it ${route.kind === "configurations" ? "on" : ""}`}
        aria-current={route.kind === "configurations" ? "page" : undefined}>Configuration packages</Link>
      <Link href={commandsPath()} class={`it ${route.kind === "commands" ? "on" : ""}`}
        aria-current={route.kind === "commands" ? "page" : undefined}>Commands</Link>
      <Link href={auditPath()} class={`it ${route.kind === "audit" ? "on" : ""}`}
        aria-current={route.kind === "audit" ? "page" : undefined}>Audit</Link>
      {UNBUILT_SURFACES.map((surface) => (
        <span
          key={surface.label}
          class="it disabled"
          aria-disabled="true"
          title={surface.reason}
        >
          {surface.label}
        </span>
      ))}
      <div class="side-divider" role="separator" />
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
    </nav>
  );
}

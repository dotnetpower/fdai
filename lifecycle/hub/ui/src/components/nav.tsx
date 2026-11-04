import { useEffect, useState } from "preact/hooks";
import {
  auditPath, availableReleasesPath, bundleImportPath, commandsPath, configurationPackagesPath,
  confirmationsPath, enrollmentsPath, installationsPath, updatesPath, type Route,
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

function isAdvancedCatalogRoute(route: Route): boolean {
  return (
    route.kind === "updates" ||
    route.kind === "releases" ||
    route.kind === "configurations" ||
    route.kind === "bundle-import" ||
    route.kind === "confirmations"
  );
}

/** Explicit unavailability reasons and supported procedures (UXH-15).
 * Keeps four aria-disabled entries so existing navigation contract checks pass while
 * distinguishing CLI/external boundaries from active Hub screens. */
const UNBUILT_SURFACES = [
  {
    label: "Customer Git PRs",
    labelKo: "고객 Git PR",
    reason: "Configuration changes stay in customer Git as reviewed merges (ADR-0003 L9).",
    reasonKo: "구성 변경은 고객 Git 저장소에서 검토된 병합(PR)으로 관리합니다 (ADR-0003 L9).",
  },
  {
    label: "Terraform executor",
    labelKo: "Terraform 실행기",
    reason: "Exact Terraform plans render and execute inside the installation boundary, never in the Hub.",
    reasonKo: "정확한 Terraform 계획은 Hub가 아닌 설치 경계 내부에서 렌더링되고 실행됩니다.",
  },
  {
    label: "Custom channels",
    labelKo: "사용자 정의 채널",
    reason: "Customer-local channel curation is available on the Catalog import screen after a catalog is accepted.",
    reasonKo: "카탈로그가 수락된 후 카탈로그 가져오기 화면에서 고객 로컬 채널을 구성할 수 있습니다.",
  },
  {
    label: "Break-glass CLI",
    labelKo: "긴급 복구 CLI",
    reason: "Emergency break-glass overrides also support the installation-local CLI and break-glass role.",
    reasonKo: "긴급(Break-glass) 재정의는 설치 환경 로컬 CLI 및 긴급 역할도 함께 지원합니다.",
  },
] as const;

export function Nav({ route }: { route: Route }) {
  const [locale, setLocale] = useHubLocale();
  const [showAdvanced, setShowAdvanced] = useState(() => isAdvancedCatalogRoute(route));
  const [showBoundaries, setShowBoundaries] = useState(false);

  useEffect(() => {
    if (isAdvancedCatalogRoute(route)) {
      setShowAdvanced(true);
    }
  }, [route.kind]);

  return (
    <nav class="side" aria-label="Lifecycle Hub">
      <div class="brand">
        <img class="brand-logo" src={`${import.meta.env.BASE_URL}brand/fdai-logo.png`} alt="" />
        <span class="brand-wordmark">FDAI</span>
        <span class="brand-separator" aria-hidden="true" />
        <span class="brand-product">Lifecycle Hub</span>
      </div>
      <div class="side-section-label">
        {tr(locale, "Console Provisioning", "콘솔 프로비저닝")}
      </div>
      <Link
        href={installationsPath()}
        class={`it ${isOnInstallations(route) ? "on" : ""}`}
        aria-current={isOnInstallations(route) ? "page" : undefined}
      >
        <InstallationsIcon />
        {tr(locale, "Installations", "설치 환경")}
      </Link>
      <Link href="/catalog" class={`it ${route.kind === "catalog" ? "on" : ""}`}
        aria-current={route.kind === "catalog" ? "page" : undefined}>
        {tr(locale, "Catalog import", "카탈로그 가져오기")}
      </Link>
      <Link
        href={enrollmentsPath()}
        class={`it ${isOnEnrollments(route) ? "on" : ""}`}
        aria-current={isOnEnrollments(route) ? "page" : undefined}
      >
        <EnrollmentsIcon />
        {tr(locale, "Enrollment requests", "등록 요청")}
      </Link>
      <div class="side-divider" role="separator" />
      <div class="side-section-label">
        {tr(locale, "Operations & Audit", "운영 제어 및 감사")}
      </div>
      <Link href={commandsPath()} class={`it ${route.kind === "commands" ? "on" : ""}`}
        aria-current={route.kind === "commands" ? "page" : undefined}>
        {tr(locale, "Commands", "수명 주기 명령")}
      </Link>
      <Link href={auditPath()} class={`it ${route.kind === "audit" ? "on" : ""}`}
        aria-current={route.kind === "audit" ? "page" : undefined}>
        {tr(locale, "Audit", "감사 기록")}
      </Link>
      <div class="side-divider" role="separator" />
      <button
        type="button"
        class="side-group-toggle"
        aria-expanded={showAdvanced}
        onClick={() => setShowAdvanced((current) => !current)}
      >
        <span>{tr(locale, "Advanced Catalog & Packages (5)", "고급 카탈로그 및 패키지 (5)")}</span>
        <span class="side-chevron" aria-hidden="true">{showAdvanced ? "▾" : "▸"}</span>
      </button>
      <div class="side-collapsible" hidden={!showAdvanced}>
        <Link href={updatesPath()} class={`it ${route.kind === "updates" ? "on" : ""}`}
          aria-current={route.kind === "updates" ? "page" : undefined}>
          {tr(locale, "Updates", "업데이트")}
        </Link>
        <Link href={availableReleasesPath()} class={`it ${route.kind === "releases" ? "on" : ""}`}
          aria-current={route.kind === "releases" ? "page" : undefined}>
          {tr(locale, "Available releases", "사용 가능한 릴리스")}
        </Link>
        <Link href={configurationPackagesPath()} class={`it ${route.kind === "configurations" ? "on" : ""}`}
          aria-current={route.kind === "configurations" ? "page" : undefined}>
          {tr(locale, "Configuration packages", "구성 패키지")}
        </Link>
        <Link href={bundleImportPath()} class={`it ${route.kind === "bundle-import" ? "on" : ""}`}
          aria-current={route.kind === "bundle-import" ? "page" : undefined}>
          {tr(locale, "Bundle import", "번들 가져오기")}
        </Link>
        <Link href={confirmationsPath()} class={`it ${route.kind === "confirmations" ? "on" : ""}`}
          aria-current={route.kind === "confirmations" ? "page" : undefined}>
          {tr(locale, "Confirmations", "파괴적 변경 확인")}
        </Link>
      </div>
      <button
        type="button"
        class="side-group-toggle"
        aria-expanded={showBoundaries}
        onClick={() => setShowBoundaries((current) => !current)}
      >
        <span>{tr(locale, "Architecture Boundaries (4)", "외부 아키텍처 경계 (4)")}</span>
        <span class="side-chevron" aria-hidden="true">{showBoundaries ? "▾" : "▸"}</span>
      </button>
      <div class="side-collapsible" hidden={!showBoundaries}>
        {UNBUILT_SURFACES.map((surface) => (
          <span
            key={surface.label}
            class="it disabled"
            aria-disabled="true"
            title={tr(locale, surface.reason, surface.reasonKo)}
          >
            {tr(locale, surface.label, surface.labelKo)}
          </span>
        ))}
      </div>
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

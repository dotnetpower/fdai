import type { InstallationDetail, ReleaseInventoryItem } from "../api";
import { tr, useHubLocale } from "../locale";
import { Badge, HealthBadge } from "./badge";

type InstalledModule = {
  id: string;
  version: string | null;
  health: InstallationDetail["health"];
};

const MODULE_LABELS: Readonly<Record<string, readonly [string, string]>> = {
  "core-control-plane": ["Core control plane", "Core 컨트롤 플레인"],
  "operator-service": ["Operator service", "Operator 서비스"],
  "document-ingestion-api": ["Document ingestion", "문서 수집"],
  "document-processing-worker": ["Document processing", "문서 처리"],
  "isolated-executor": ["Isolated executor", "격리 실행기"],
  clamav: ["Malware scanning", "악성 코드 검사"],
  pgvector: ["Vector database", "벡터 데이터베이스"],
};

function moduleLabel(id: string, locale: "en" | "ko"): string {
  const label = MODULE_LABELS[id];
  return label ? label[locale === "ko" ? 1 : 0] : id;
}

export function safeConsoleUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      url.pathname === "/" &&
      !url.search &&
      !url.hash
      ? url.href
      : null;
  } catch {
    return null;
  }
}

function installedModules(
  installation: InstallationDetail,
  releases: readonly ReleaseInventoryItem[] | null,
): InstalledModule[] {
  const release = releases?.find((item) => item.release_id === installation.current_release);
  if (release) {
    return [...new Set(release.images.map((image) => image.component))]
      .sort()
      .map((id) => ({
        id,
        version: installation.current_release,
        health: installation.health,
      }));
  }
  return installation.entities
    .filter((entity) => entity.release_id !== null)
    .map((entity) => ({
      id: entity.entity_id,
      version: entity.release_id,
      health: entity.health,
    }))
    .sort((left, right) => left.id.localeCompare(right.id));
}

export function InstallationSummary({
  installation,
  releases,
}: {
  installation: InstallationDetail;
  releases: readonly ReleaseInventoryItem[] | null;
}) {
  const [locale] = useHubLocale();
  const consoleUrl = safeConsoleUrl(installation.console_url);
  const modules = installedModules(installation, releases);
  return (
    <>
      <section class="installation-console" aria-labelledby="console-web-heading">
        <div>
          <h2 id="console-web-heading" class="panel-title">
            {tr(locale, "Console Web", "Console Web")}
          </h2>
          <p class="note">
            {tr(
              locale,
              "Open the deployed FDAI operator experience.",
              "배포된 FDAI 운영 화면을 엽니다.",
            )}
          </p>
        </div>
        <div class="installation-console-link">
          {consoleUrl ? (
            <>
              <a href={consoleUrl} target="_blank" rel="noreferrer">
                {consoleUrl}
              </a>
              <Badge variant={installation.health === "healthy" ? "ok" : "warn"}>
                {installation.health === "healthy"
                  ? tr(locale, "Reported healthy", "정상 보고됨")
                  : tr(locale, "Check status", "상태 확인 필요")}
              </Badge>
            </>
          ) : (
            <>
              <strong>{tr(locale, "Console URL not recorded", "Console URL 미기록")}</strong>
              <span class="soft">
                {tr(
                  locale,
                  "Ask the deployment owner to bind the installation's HTTPS Console origin.",
                  "배포 담당자가 설치 환경의 HTTPS Console origin을 연결해야 합니다.",
                )}
              </span>
            </>
          )}
        </div>
      </section>

      <section class="installed-modules" aria-labelledby="installed-modules-heading">
        <div class="section-title-row">
          <div>
            <h2 id="installed-modules-heading" class="panel-title">
              {tr(locale, "Installed modules", "설치된 모듈")}
            </h2>
            <p class="note">
              {tr(
                locale,
                "Modules in the currently installed signed Release.",
                "현재 설치된 서명 Release에 포함된 모듈입니다.",
              )}
            </p>
          </div>
          <Badge variant={modules.length > 0 ? "ok" : "warn"}>
            {`${modules.length} ${tr(locale, "modules", "개")}`}
          </Badge>
        </div>
        {modules.length > 0 ? (
          <ul class="module-grid">
            {modules.map((module) => (
              <li key={module.id} class="module-item">
                <strong>{moduleLabel(module.id, locale)}</strong>
                <code>{module.id}</code>
                <span>
                  {tr(locale, "Version", "버전")}{" "}
                  <strong>{module.version ?? tr(locale, "Not reported", "미보고")}</strong>
                </span>
                {module.health !== null && <HealthBadge health={module.health} />}
              </li>
            ))}
          </ul>
        ) : (
          <p class="note">
            {tr(
              locale,
              "No installed modules are reported yet.",
              "아직 설치된 모듈이 보고되지 않았습니다.",
            )}
          </p>
        )}
      </section>
    </>
  );
}

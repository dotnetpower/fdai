import { useEffect, useRef, useState } from "preact/hooks";
import { getLocale } from "../i18n";
import { helpCenterText } from "./help-center.i18n";
import { Tooltip } from "./tooltip";

export interface ManualCatalogEntry {
  readonly id: string;
  readonly stageId: string;
  readonly kind: "core" | "deep-dive";
  readonly level: ManualLevel;
  readonly status: ManualStatus;
  readonly title: string;
  readonly eyebrow: string;
  readonly description: string;
  readonly createdAt: string;
  readonly lastEditedAt: string;
  readonly reviewedAt: string | null;
  readonly duration: string;
  readonly slideCount: number;
  readonly coverImage: string;
  readonly coverLabel: string;
  readonly featured: boolean;
}

type ManualLevel = "L100" | "L200" | "L300" | "L400";
type ManualStatus = "complete" | "wip";

export interface ManualJourneyStage {
  readonly id: string;
  readonly number: number;
  readonly title: string;
  readonly question: string;
  readonly differentiator: boolean;
}

export interface ManualCatalog {
  readonly schemaVersion: 3;
  readonly generatedAt: string;
  readonly minimumSlidesByLevel: Readonly<Record<ManualLevel, number>>;
  readonly journey: {
    readonly id: string;
    readonly title: string;
    readonly stages: readonly ManualJourneyStage[];
  };
  readonly manuals: readonly ManualCatalogEntry[];
}

type CatalogState =
  | { readonly status: "idle" | "loading" | "unavailable" | "invalid" }
  | { readonly status: "ready"; readonly catalog: ManualCatalog }
  | { readonly status: "error" };

const CATALOG_TIMEOUT_MS = 8_000;
const SAFE_ASSET_PATH = /^[a-zA-Z0-9][a-zA-Z0-9/_.-]*$/;
const LOCAL_MANUAL_STUDIO_URL = "http://127.0.0.1:5474";

function asRecord(value: unknown): Readonly<Record<string, unknown>> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Readonly<Record<string, unknown>>
    : null;
}

function requiredString(
  record: Readonly<Record<string, unknown>>,
  key: string,
): string {
  const value = record[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`Manual catalog field ${key} must be a non-empty string.`);
  }
  return value;
}

function isManualLevel(value: unknown): value is ManualLevel {
  return value === "L100" || value === "L200" || value === "L300" || value === "L400";
}

function parseMinimumSlidesByLevel(value: unknown): Readonly<Record<ManualLevel, number>> {
  const record = asRecord(value);
  if (record === null) {
    throw new Error("Manual catalog minimumSlidesByLevel must be an object.");
  }
  for (const level of ["L100", "L200", "L300", "L400"] as const) {
    const minimum = record[level];
    if (!Number.isSafeInteger(minimum) || Number(minimum) <= 0) {
      throw new Error(`Manual catalog minimumSlidesByLevel.${level} must be a positive integer.`);
    }
  }
  return {
    L100: Number(record.L100),
    L200: Number(record.L200),
    L300: Number(record.L300),
    L400: Number(record.L400),
  };
}

export function manualAssetUrl(baseUrl: string, assetPath: string): string | null {
  if (
    !SAFE_ASSET_PATH.test(assetPath) ||
    assetPath.startsWith("/") ||
    assetPath.split("/").includes("..")
  ) return null;
  const base = new URL(`${baseUrl.replace(/\/+$/, "")}/`);
  const resolved = new URL(assetPath, base);
  return resolved.origin === base.origin && resolved.pathname.startsWith(base.pathname)
    ? resolved.toString()
    : null;
}

export function manualOpenUrl(baseUrl: string, manualId?: string): string {
  if (manualId !== undefined && !/^[a-z0-9-]+$/.test(manualId)) {
    throw new Error("Manual id must use lowercase ASCII kebab-case.");
  }
  return new URL(
    manualId === undefined ? "library.html" : `${manualId}.html`,
    `${baseUrl.replace(/\/+$/, "")}/`,
  ).toString();
}

export function resolveManualStudioUrl(
  configuredValue: unknown,
  development: boolean,
): string | null {
  const raw = typeof configuredValue === "string" ? configuredValue.trim() : "";
  const value = raw || (development ? LOCAL_MANUAL_STUDIO_URL : "");
  if (value === "") return null;
  if (!URL.canParse(value)) {
    throw new Error("VITE_MANUAL_STUDIO_URL must be a valid external web URL.");
  }
  const url = new URL(value);
  const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
  if (
    (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) ||
    url.username || url.password || url.search || url.hash
  ) {
    throw new Error(
      "VITE_MANUAL_STUDIO_URL must be HTTPS without URL state; loopback HTTP is also allowed.",
    );
  }
  return url.toString().replace(/\/+$/, "");
}

export function parseManualCatalog(value: unknown, baseUrl: string): ManualCatalog {
  const record = asRecord(value);
  const journey = record === null ? null : asRecord(record.journey);
  if (
    record === null ||
    record.schemaVersion !== 3 ||
    !Array.isArray(record.manuals) ||
    journey === null ||
    !Array.isArray(journey.stages)
  ) {
    throw new Error(
      "Manual catalog must use schemaVersion 3 and contain journey stages and manuals.",
    );
  }
  const generatedAt = requiredString(record, "generatedAt");
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(generatedAt)) {
    throw new Error("Manual catalog generatedAt must be an RFC 3339 UTC timestamp.");
  }
  const minimumSlidesByLevel = parseMinimumSlidesByLevel(record.minimumSlidesByLevel);

  const stages = journey.stages.map((value, index): ManualJourneyStage => {
    const stage = asRecord(value);
    if (stage === null) throw new Error(`Manual journey stage ${index} must be an object.`);
    const id = requiredString(stage, "id");
    if (!/^[a-z0-9-]+$/.test(id) || !Number.isSafeInteger(stage.number)) {
      throw new Error(`Manual journey stage ${index} has invalid identity fields.`);
    }
    if (typeof stage.differentiator !== "boolean") {
      throw new Error(`Manual journey stage ${id} has an invalid differentiator value.`);
    }
    return {
      id,
      number: Number(stage.number),
      title: requiredString(stage, "title"),
      question: requiredString(stage, "question"),
      differentiator: stage.differentiator,
    };
  });
  if (stages.length !== 5 || new Set(stages.map((stage) => stage.id)).size !== 5) {
    throw new Error("Manual journey must contain five unique stages.");
  }
  const stageIds = new Set(stages.map((stage) => stage.id));

  const manuals = record.manuals.map((value, index): ManualCatalogEntry => {
    const manual = asRecord(value);
    if (manual === null) throw new Error(`Manual catalog entry ${index} must be an object.`);
    const id = requiredString(manual, "id");
    const stageId = requiredString(manual, "stageId");
    const kind = requiredString(manual, "kind");
    const level = manual.level ?? "L100";
    const status = requiredString(manual, "status");
    const createdAt = requiredString(manual, "createdAt");
    const lastEditedAt = requiredString(manual, "lastEditedAt");
    const reviewedAt = manual.reviewedAt;
    const coverImage = requiredString(manual, "coverImage");
    if (!/^[a-z0-9-]+$/.test(id)) {
      throw new Error(`Manual catalog entry ${index} has an invalid id.`);
    }
    if (!stageIds.has(stageId) || (kind !== "core" && kind !== "deep-dive")) {
      throw new Error(`Manual catalog entry ${id} has invalid journey fields.`);
    }
    if (!isManualLevel(level)) {
      throw new Error(`Manual catalog entry ${id} has an invalid level.`);
    }
    if (status !== "complete" && status !== "wip") {
      throw new Error(`Manual catalog entry ${id} has an invalid status.`);
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(createdAt)) {
      throw new Error(`Manual catalog entry ${id} has an invalid createdAt date.`);
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(lastEditedAt) || lastEditedAt < createdAt) {
      throw new Error(`Manual catalog entry ${id} has an invalid lastEditedAt date.`);
    }
    if (reviewedAt !== null &&
        (typeof reviewedAt !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(reviewedAt))) {
      throw new Error(`Manual catalog entry ${id} has an invalid reviewedAt date.`);
    }
    if (!Number.isSafeInteger(manual.slideCount) || Number(manual.slideCount) <= 0) {
      throw new Error(`Manual catalog entry ${id} has an invalid slideCount.`);
    }
    if (status === "complete" && Number(manual.slideCount) < minimumSlidesByLevel[level]) {
      throw new Error(`Manual catalog entry ${id} does not meet the ${level} slide minimum.`);
    }
    if (typeof manual.featured !== "boolean") {
      throw new Error(`Manual catalog entry ${id} has an invalid featured value.`);
    }
    if (manualAssetUrl(baseUrl, coverImage) === null) {
      throw new Error(`Manual catalog entry ${id} has an unsafe coverImage path.`);
    }
    return {
      id,
      stageId,
      kind,
      level,
      status,
      title: requiredString(manual, "title"),
      eyebrow: requiredString(manual, "eyebrow"),
      description: requiredString(manual, "description"),
      createdAt,
      lastEditedAt,
      reviewedAt,
      duration: requiredString(manual, "duration"),
      slideCount: Number(manual.slideCount),
      coverImage,
      coverLabel: requiredString(manual, "coverLabel"),
      featured: manual.featured,
    };
  });

  return {
    schemaVersion: 3,
    generatedAt,
    minimumSlidesByLevel,
    journey: {
      id: requiredString(journey, "id"),
      title: requiredString(journey, "title"),
      stages,
    },
    manuals,
  };
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(getLocale() === "ko" ? "ko-KR" : "en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value.slice(0, 10)}T00:00:00Z`));
}

function ManualBookCover({
  manual,
  imageUrl,
  stageNumber,
}: {
  readonly manual: ManualCatalogEntry;
  readonly imageUrl: string;
  readonly stageNumber: number;
}) {
  return (
    <span class="manual-book" aria-hidden="true">
      <span class="manual-book-image">
        <img src={imageUrl} alt="" draggable={false} referrerPolicy="no-referrer" />
        <b>{manual.coverLabel}</b>
      </span>
      <span class="manual-book-copy">
        <small>
          {manual.kind === "core" ? helpCenterText("coreDeck") : helpCenterText("deepDive")}
          {` · ${manual.level} · ${String(stageNumber).padStart(2, "0")}`}
        </small>
        <strong>{manual.title}</strong>
        <span>{`${manual.duration} · ${helpCenterText("slides", { count: manual.slideCount })}`}</span>
      </span>
    </span>
  );
}

export function HelpCenter() {
  const [open, setOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [catalogState, setCatalogState] = useState<CatalogState>({ status: "idle" });
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  let manualStudioUrl: string | null = null;
  let invalidConfiguration = false;
  try {
    manualStudioUrl = resolveManualStudioUrl(
      import.meta.env.VITE_MANUAL_STUDIO_URL,
      import.meta.env.DEV,
    );
  } catch {
    invalidConfiguration = true;
  }

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (invalidConfiguration) {
      console.warn("manual_studio_configuration_invalid");
      setCatalogState({ status: "invalid" });
      return;
    }
    if (manualStudioUrl === null) {
      setCatalogState({ status: "unavailable" });
      return;
    }

    const controller = new AbortController();
    let cancelled = false;
    const timeout = window.setTimeout(() => controller.abort(), CATALOG_TIMEOUT_MS);
    setCatalogState({ status: "loading" });
    void fetch(`${manualStudioUrl}/catalog.json`, {
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Manual catalog request failed with HTTP ${response.status}.`);
        }
        const catalog = parseManualCatalog(await response.json(), manualStudioUrl);
        if (!cancelled) {
          setCatalogState({ status: "ready", catalog });
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        console.warn("manual_catalog_load_failed", {
          error_name: error instanceof Error ? error.name : "unknown",
        });
        setCatalogState({ status: "error" });
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [invalidConfiguration, manualStudioUrl, open, reloadKey]);

  const close = (): void => {
    setOpen(false);
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  };
  const readyCatalog = catalogState.status === "ready" ? catalogState.catalog : null;

  return (
    <span class="help-center">
      <Tooltip content={helpCenterText("open")} placement="bottom">
        <button
          ref={triggerRef}
          type="button"
          class="help-center-trigger"
          aria-label={helpCenterText("open")}
          aria-expanded={open}
          aria-controls="manual-library-drawer"
          onClick={() => setOpen(true)}
        >
          <span aria-hidden="true">?</span>
        </button>
      </Tooltip>
      <dialog
        ref={dialogRef}
        id="manual-library-drawer"
        class="manual-library-drawer"
        aria-labelledby="manual-library-title"
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
        onClose={() => {
          setOpen(false);
          window.requestAnimationFrame(() => triggerRef.current?.focus());
        }}
        onClick={(event) => {
          if (event.target !== event.currentTarget) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          if (event.clientX < bounds.left) close();
        }}
      >
        <header class="manual-library-header">
          <div>
            <span>{helpCenterText("title")}</span>
            <h2 id="manual-library-title">{helpCenterText("title")}</h2>
            <p>{helpCenterText("subtitle")}</p>
          </div>
          <button type="button" onClick={close} aria-label={helpCenterText("close")}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="m6 6 12 12M18 6 6 18" />
            </svg>
          </button>
        </header>

        <div class="manual-library-body">
          {catalogState.status === "loading" || catalogState.status === "idle" ? (
            <div
              class="manual-library-loading"
              role="status"
              aria-live="polite"
              aria-busy="true"
            >
              <span class="sr-only">{helpCenterText("loading")}</span>
              <div class="skeleton-shimmer" aria-hidden="true" />
              <div class="skeleton-shimmer" aria-hidden="true" />
              <div class="skeleton-shimmer" aria-hidden="true" />
              <div class="skeleton-shimmer" aria-hidden="true" />
            </div>
          ) : catalogState.status === "unavailable" ? (
            <div class="manual-library-state">
              <strong>{helpCenterText("notConfigured")}</strong>
              <p>{helpCenterText("notConfiguredHint")}</p>
            </div>
          ) : catalogState.status === "invalid" ? (
            <div class="manual-library-state" role="alert">
              <strong>{helpCenterText("invalidConfig")}</strong>
              <p>{helpCenterText("invalidConfigHint")}</p>
            </div>
          ) : catalogState.status === "error" ? (
            <div class="manual-library-state" role="alert">
              <strong>{helpCenterText("loadFailed")}</strong>
              <p>{helpCenterText("loadFailedHint")}</p>
              <button type="button" onClick={() => setReloadKey((current) => current + 1)}>
                {helpCenterText("retry")}
              </button>
            </div>
          ) : readyCatalog !== null && manualStudioUrl !== null ? (
            <>
              <div class="manual-library-toolbar">
                <span>{readyCatalog.journey.title}</span>
                <a
                  href={manualOpenUrl(manualStudioUrl)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {helpCenterText("allManuals")}
                </a>
              </div>
              {readyCatalog.manuals.length === 0 ? (
                <p class="manual-library-empty">{helpCenterText("noManuals")}</p>
              ) : (
                <div class="manual-journey">
                  {readyCatalog.journey.stages.map((stage) => {
                    const stageManuals = readyCatalog.manuals.filter((manual) =>
                      manual.stageId === stage.id);
                    if (stageManuals.length === 0) return null;
                    const headingId = `manual-journey-stage-${stage.id}`;
                    return (
                      <section
                        key={stage.id}
                        class="manual-journey-section"
                        aria-labelledby={headingId}
                      >
                        <div class="manual-journey-heading">
                          <span>{String(stage.number).padStart(2, "0")}</span>
                          <div>
                            {stage.differentiator
                              ? <small>FDAI DIFFERENTIATOR</small>
                              : null}
                            <strong id={headingId}>{stage.title}</strong>
                            <p>{stage.question}</p>
                          </div>
                        </div>
                        <ul class="manual-book-list">
                          {stageManuals.map((manual) => (
                            <li key={manual.id}>
                              <a
                                class="manual-book-list-item"
                                href={manualOpenUrl(manualStudioUrl, manual.id)}
                                target="_blank"
                                rel="noreferrer"
                                aria-label={helpCenterText("openManual", {
                                  title: manual.title,
                                })}
                                onClick={close}
                              >
                                <span class="manual-book-list-cover">
                                  <ManualBookCover
                                    manual={manual}
                                    imageUrl={
                                      manualAssetUrl(manualStudioUrl, manual.coverImage) ?? ""
                                    }
                                    stageNumber={stage.number}
                                  />
                                </span>
                                <span class="manual-book-list-details">
                                  <span class="manual-book-recommendation">
                                    {manual.description}
                                  </span>
                                </span>
                              </a>
                            </li>
                          ))}
                        </ul>
                      </section>
                    );
                  })}
                </div>
              )}
              <footer class="manual-library-footer">
                {helpCenterText("generated", {
                  date: formatDate(readyCatalog.generatedAt),
                })}
              </footer>
            </>
          ) : null}
        </div>
      </dialog>
    </span>
  );
}

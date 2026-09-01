import type { JSX } from "preact";
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
  readonly schemaVersion: 2;
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
  const url = new URL("library", `${baseUrl.replace(/\/+$/, "")}/`);
  if (manualId !== undefined) url.searchParams.set("manual", manualId);
  return url.toString();
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
    record.schemaVersion !== 2 ||
    !Array.isArray(record.manuals) ||
    journey === null ||
    !Array.isArray(journey.stages)
  ) {
    throw new Error(
      "Manual catalog must use schemaVersion 2 and contain journey stages and manuals.",
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
      duration: requiredString(manual, "duration"),
      slideCount: Number(manual.slideCount),
      coverImage,
      coverLabel: requiredString(manual, "coverLabel"),
      featured: manual.featured,
    };
  });

  return {
    schemaVersion: 2,
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
  reflection = false,
}: {
  readonly manual: ManualCatalogEntry;
  readonly imageUrl: string;
  readonly stageNumber: number;
  readonly reflection?: boolean;
}) {
  return (
    <span
      class={`manual-book${reflection ? " manual-book-reflection" : ""}`}
      aria-hidden={reflection || undefined}
    >
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

function applyManualCoverDrag(
  track: HTMLDivElement,
  selectedIndex: number,
  deltaX: number,
): void {
  const spacing = 150;
  Array.from(track.children).forEach((node, index) => {
    if (!(node instanceof HTMLElement)) return;
    const position = index - selectedIndex + deltaX / spacing;
    const distance = Math.abs(position);
    const x = position * spacing;
    const rotation = Math.max(-28, Math.min(28, -position * 22));
    const scale = distance <= 1
      ? 1 - distance * 0.44
      : Math.max(0.38, 0.56 - (distance - 1) * 0.16);
    node.style.transform =
      `translateX(calc(-50% + ${x}px)) rotateY(${rotation}deg) scale(${scale})`;
    node.style.filter =
      `brightness(${Math.max(0.36, 1 - distance * 0.4)}) ` +
      `saturate(${Math.max(0.5, 1 - distance * 0.28)})`;
    node.style.opacity = distance >= 2.4 ? "0" : "1";
    node.style.zIndex = String(Math.max(1, 10 - Math.round(distance * 2)));
  });
}

function clearManualCoverDrag(track: HTMLDivElement): void {
  Array.from(track.children).forEach((node) => {
    if (!(node instanceof HTMLElement)) return;
    node.style.removeProperty("transform");
    node.style.removeProperty("filter");
    node.style.removeProperty("opacity");
    node.style.removeProperty("z-index");
  });
}

export function HelpCenter() {
  const [open, setOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedManualId, setSelectedManualId] = useState<string | null>(null);
  const [catalogState, setCatalogState] = useState<CatalogState>({ status: "idle" });
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const manualDragRef = useRef({
    pointerId: null as number | null,
    startX: 0,
    deltaX: 0,
    targetManualId: null as string | null,
  });
  const suppressManualClickRef = useRef(false);
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
          setSelectedManualId((current) =>
            current !== null && catalog.manuals.some((manual) => manual.id === current)
              ? current
              : catalog.manuals.find((manual) => manual.id === "ontology-foundation")?.id
                ?? catalog.manuals.find((manual) => manual.featured)?.id
                ?? catalog.manuals[0]?.id
                ?? null
          );
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
  const selectedIndex = readyCatalog?.manuals.findIndex((manual) =>
    manual.id === selectedManualId) ?? -1;
  const selectedManual = selectedIndex >= 0 ? readyCatalog?.manuals[selectedIndex] : undefined;
  const selectedStage = selectedManual === undefined
    ? undefined
    : readyCatalog?.journey.stages.find((stage) => stage.id === selectedManual.stageId);
  const finishManualDrag = (
    event: JSX.TargetedPointerEvent<HTMLDivElement>,
  ): void => {
    const drag = manualDragRef.current;
    if (drag.pointerId !== event.pointerId) return;
    const track = event.currentTarget;
    if (track.hasPointerCapture(event.pointerId)) {
      track.releasePointerCapture(event.pointerId);
    }
    const moved = Math.abs(drag.deltaX) > 8;
    let nextManualId = selectedManual?.id ?? null;
    if (readyCatalog !== null && Math.abs(drag.deltaX) >= 36) {
      const movedCovers = Math.max(1, Math.round(Math.abs(drag.deltaX) / 150));
      const nextIndex = Math.max(
        0,
        Math.min(
          readyCatalog.manuals.length - 1,
          selectedIndex + (drag.deltaX < 0 ? movedCovers : -movedCovers),
        ),
      );
      nextManualId = readyCatalog.manuals[nextIndex]?.id ?? null;
    }
    track.classList.remove("dragging");
    if (nextManualId !== selectedManual?.id) {
      setSelectedManualId(nextManualId);
      window.requestAnimationFrame(() => clearManualCoverDrag(track));
    } else {
      clearManualCoverDrag(track);
    }
    const clickedActiveCover = drag.targetManualId === selectedManual?.id;
    if (
      !moved &&
      clickedActiveCover &&
      selectedManual !== undefined &&
      manualStudioUrl !== null
    ) {
      window.open(
        manualOpenUrl(manualStudioUrl, selectedManual.id),
        "_blank",
        "noopener,noreferrer",
      );
      close();
    }
    suppressManualClickRef.current = moved || clickedActiveCover;
    window.setTimeout(() => { suppressManualClickRef.current = false; }, 0);
    drag.pointerId = null;
    drag.deltaX = 0;
    drag.targetManualId = null;
  };

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
              ) : selectedManual !== undefined && selectedStage !== undefined ? (
                <div class="manual-journey">
                  <div class="manual-journey-stages" aria-label={readyCatalog.journey.title}>
                    {readyCatalog.journey.stages.map((stage) => (
                      <button
                        key={stage.id}
                        type="button"
                        class={stage.id === selectedStage.id ? "active" : ""}
                        aria-current={stage.id === selectedStage.id ? "step" : undefined}
                        aria-label={`${stage.number}. ${stage.title}`}
                        onClick={() => {
                          const next = readyCatalog.manuals.find((manual) =>
                            manual.stageId === stage.id &&
                            (manual.featured || manual.kind === "core"));
                          if (next) setSelectedManualId(next.id);
                        }}
                      >
                        <span>{String(stage.number).padStart(2, "0")}</span>
                      </button>
                    ))}
                  </div>
                  <div class="manual-journey-heading">
                    <span>{String(selectedStage.number).padStart(2, "0")}</span>
                    <div>
                      {selectedStage.differentiator
                        ? <small>FDAI DIFFERENTIATOR</small>
                        : null}
                      <strong>{selectedStage.title}</strong>
                      <p>{selectedStage.question}</p>
                    </div>
                  </div>
                  <div class="manual-coverflow">
                    <button
                      type="button"
                      class="manual-coverflow-arrow"
                      aria-label={helpCenterText("previousManual")}
                      disabled={selectedIndex <= 0}
                      onClick={() => setSelectedManualId(
                        readyCatalog.manuals[selectedIndex - 1]?.id ?? selectedManual.id
                      )}
                    >
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7" /></svg>
                    </button>
                    <div
                      class="manual-coverflow-track"
                      onPointerDown={(event) => {
                        if (event.button !== 0) return;
                        const drag = manualDragRef.current;
                        drag.pointerId = event.pointerId;
                        drag.startX = event.clientX;
                        drag.deltaX = 0;
                        const pointerTarget = event.target instanceof Element
                          ? event.target.closest<HTMLElement>(".manual-library-card")
                          : null;
                        drag.targetManualId = pointerTarget?.dataset.manualId ?? null;
                        event.currentTarget.setPointerCapture(event.pointerId);
                        event.currentTarget.classList.add("dragging");
                      }}
                      onPointerMove={(event) => {
                        const drag = manualDragRef.current;
                        if (drag.pointerId !== event.pointerId) return;
                        const minimum =
                          -(readyCatalog.manuals.length - 1 - selectedIndex) * 150;
                        const maximum = selectedIndex * 150;
                        drag.deltaX = Math.max(
                          minimum,
                          Math.min(maximum, event.clientX - drag.startX),
                        );
                        applyManualCoverDrag(event.currentTarget, selectedIndex, drag.deltaX);
                      }}
                      onDragStart={(event) => event.preventDefault()}
                      onPointerUp={finishManualDrag}
                      onPointerCancel={finishManualDrag}
                    >
                      {readyCatalog.manuals.map((manual, index) => {
                        const distance = Math.max(-3, Math.min(3, index - selectedIndex));
                        const active = distance === 0;
                        const stageNumber = readyCatalog.journey.stages.find((stage) =>
                          stage.id === manual.stageId)?.number ?? selectedStage.number;
                        return (
                          <button
                            key={manual.id}
                            type="button"
                            class="manual-library-card"
                            data-distance={distance}
                            data-active={String(active)}
                            data-manual-id={manual.id}
                            aria-label={active
                              ? helpCenterText("openManual", { title: manual.title })
                              : manual.title}
                            aria-current={active ? "true" : undefined}
                            aria-hidden={Math.abs(distance) > 1}
                            tabIndex={active ? 0 : -1}
                            onClick={(event) => {
                              if (suppressManualClickRef.current) {
                                event.preventDefault();
                                suppressManualClickRef.current = false;
                                return;
                              }
                              if (!active) {
                                setSelectedManualId(manual.id);
                                return;
                              }
                              window.open(
                                manualOpenUrl(manualStudioUrl, manual.id),
                                "_blank",
                                "noopener,noreferrer",
                              );
                              close();
                            }}
                          >
                            <ManualBookCover
                              manual={manual}
                              imageUrl={manualAssetUrl(manualStudioUrl, manual.coverImage) ?? ""}
                              stageNumber={stageNumber}
                            />
                            <ManualBookCover
                              manual={manual}
                              imageUrl={manualAssetUrl(manualStudioUrl, manual.coverImage) ?? ""}
                              stageNumber={stageNumber}
                              reflection
                            />
                          </button>
                        );
                      })}
                    </div>
                    <button
                      type="button"
                      class="manual-coverflow-arrow"
                      aria-label={helpCenterText("nextManual")}
                      disabled={selectedIndex >= readyCatalog.manuals.length - 1}
                      onClick={() => setSelectedManualId(
                        readyCatalog.manuals[selectedIndex + 1]?.id ?? selectedManual.id
                      )}
                    >
                      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7" /></svg>
                    </button>
                  </div>
                </div>
              ) : (
                <div class="manual-library-grid">
                  {readyCatalog.manuals.map((manual) => (
                    <a
                      key={manual.id}
                      class="manual-library-card"
                      href={manualOpenUrl(manualStudioUrl, manual.id)}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={helpCenterText("openManual", { title: manual.title })}
                      onClick={close}
                    >
                      <span class="manual-library-cover">
                        <img
                          src={manualAssetUrl(manualStudioUrl, manual.coverImage) ?? ""}
                          alt=""
                          referrerPolicy="no-referrer"
                        />
                        <span>
                          <small>FDAI</small>
                          <strong>{manual.coverLabel}</strong>
                        </span>
                      </span>
                      <span class="manual-library-copy">
                        <small>{manual.eyebrow}</small>
                        <strong>{manual.title}</strong>
                        <span>{manual.description}</span>
                        <span>
                          <time dateTime={manual.createdAt}>{formatDate(manual.createdAt)}</time>
                          <i aria-hidden="true" />
                          {helpCenterText("slides", { count: manual.slideCount })}
                        </span>
                      </span>
                    </a>
                  ))}
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

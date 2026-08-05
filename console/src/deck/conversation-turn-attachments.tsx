import { type JSX } from "preact";
import { createPortal } from "preact/compat";
import { useEffect, useRef, useState } from "preact/hooks";

import { t } from "../i18n";
import { fetchConversationImage } from "../user-context-client";
import { conversationImageFetchLimiter } from "./image-fetch-limiter";
import type { TurnAttachment } from "./turn-attachments";

export function releaseFailedAttachmentSource(
  sources: Readonly<Record<string, string>>,
  attachmentId: string,
  revoke: (source: string) => void = URL.revokeObjectURL,
): Readonly<Record<string, string>> {
  const source = sources[attachmentId];
  if (source?.startsWith("blob:")) revoke(source);
  return { ...sources, [attachmentId]: "" };
}

export function ConversationTurnAttachments({
  attachments,
}: {
  readonly attachments: readonly TurnAttachment[];
}) {
  const [sources, setSources] = useState<Readonly<Record<string, string>>>(() =>
    directSources(attachments));
  const [loading, setLoading] = useState(() => attachments.some((item) => !item.src));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previewTriggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    let active = true;
    const requestController = new AbortController();
    const objectUrls: string[] = [];
    setSources(directSources(attachments));
    const pending = attachments.filter((attachment) => !attachment.src);
    setLoading(pending.length > 0);
    if (pending.length === 0) return () => undefined;

    void Promise.all(pending.map(async (attachment) => {
      try {
        const blob = await conversationImageFetchLimiter.run(() =>
          active
            ? fetchConversationImage(
                attachment.conversationId,
                attachment.id,
                requestController.signal,
              )
            : Promise.resolve(null));
        if (!active || blob === null) return;
        const source = URL.createObjectURL(blob);
        objectUrls.push(source);
        setSources((current) => ({ ...current, [attachment.id]: source }));
      } catch {
        if (active) setSources((current) => ({ ...current, [attachment.id]: "" }));
      }
    })).finally(() => {
      if (active) setLoading(false);
    });

    return () => {
      active = false;
      requestController.abort();
      for (const source of objectUrls) URL.revokeObjectURL(source);
    };
  }, [attachments]);

  useEffect(() => {
    if (selectedId !== null) dialogRef.current?.focus();
  }, [selectedId]);

  const selectedIndex = selectedId === null
    ? -1
    : attachments.findIndex((attachment) => attachment.id === selectedId);
  const selectedSource = selectedId === null ? undefined : sources[selectedId];

  function closePreview(): void {
    setSelectedId(null);
    requestAnimationFrame(() => previewTriggerRef.current?.focus());
  }

  function handleDialogKeyDown(event: JSX.TargetedKeyboardEvent<HTMLDivElement>): void {
    if (event.key === "Escape") {
      event.stopPropagation();
      closePreview();
      return;
    }
    if (event.key === "Tab") {
      event.preventDefault();
      event.currentTarget.querySelector<HTMLButtonElement>("button")?.focus();
    }
  }

  function handleImageError(attachmentId: string): void {
    setSources((current) => releaseFailedAttachmentSource(current, attachmentId));
    if (selectedId === attachmentId) closePreview();
  }

  return (
    <div class="deck-turn-attachment-block">
      {loading ? (
        <span class="sr-only" role="status">{t("deck.attach.scanning")}</span>
      ) : null}
      <ul class="deck-turn-attachments" aria-label={t("deck.attach.tray")}>
        {attachments.map((attachment, index) => {
          const source = sources[attachment.id];
          return (
            <li key={attachment.id}>
              {source ? (
                <button
                  type="button"
                  class="deck-turn-attachment-open"
                  aria-label={t("deck.attach.openImage", { index: index + 1 })}
                  onClick={(event) => {
                    previewTriggerRef.current = event.currentTarget;
                    setSelectedId(attachment.id);
                  }}
                >
                  <img
                    src={source}
                    alt={t("deck.attach.image", { index: index + 1 })}
                    onError={() => handleImageError(attachment.id)}
                  />
                </button>
              ) : (
                <span
                  class="deck-turn-attachment-placeholder"
                  role="img"
                  aria-label={`${t("deck.attach.image", { index: index + 1 })}: ${loading ? t("deck.attach.scanning") : t("deck.attach.readFailed")}`}
                />
              )}
            </li>
          );
        })}
      </ul>
      {selectedId !== null && selectedSource && selectedIndex >= 0
        ? createPortal(
            <div class="deck-image-lightbox" onClick={closePreview}>
              <div
                ref={dialogRef}
                class="deck-image-lightbox-dialog"
                role="dialog"
                aria-modal="true"
                aria-label={t("deck.attach.imagePreview")}
                tabIndex={-1}
                onClick={(event) => event.stopPropagation()}
                onKeyDown={handleDialogKeyDown}
              >
                <img
                  src={selectedSource}
                  alt={t("deck.attach.image", { index: selectedIndex + 1 })}
                  onError={() => handleImageError(selectedId)}
                />
                <button
                  type="button"
                  class="deck-image-lightbox-close"
                  aria-label={t("deck.attach.closeImagePreview")}
                  onClick={closePreview}
                >
                  ×
                </button>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

function directSources(
  attachments: readonly TurnAttachment[],
): Readonly<Record<string, string>> {
  return Object.fromEntries(
    attachments.flatMap((attachment) =>
      attachment.src ? [[attachment.id, attachment.src]] : []),
  );
}

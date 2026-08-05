/**
 * ComposerAttachments - the command-deck file-input affordance.
 *
 * Self-contained composer-local UI: the operator stages files as read-only
 * evidence for the narrator to ground an answer on. Staging is entirely
 * client-side - nothing is uploaded or executed here, preserving the
 * read-only-console invariant. A rights-protected (RMS / Purview) Office
 * document is detected and abandoned rather than staged. Backend upload +
 * analysis is a separate, later seam; this pass only renders the picker,
 * the preview tray, and the abandon behavior.
 */
import { useCallback, useEffect, useRef, useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import { t } from "../i18n";
import {
  attachmentOperationIsCurrent,
  clipboardImageFiles,
  detectKind,
  fileExtension,
  formatSize,
  imageMediaType,
  isRightsProtected,
  newAttachmentId,
  normalizeImageDataUrl,
  thumbLabel,
  type StagedAttachment,
} from "./composer-attachments";
import {
  clearComposerAttachments,
  reserveComposerAttachment,
  stageComposerAttachment,
  subscribeComposerAttachmentDrain,
  unstageComposerAttachment,
} from "./composer-attachment-store";
import {
  MAX_VISION_IMAGE_BYTES,
  normalizeVisionImage,
} from "./composer-image-normalization";

const OOXML_PROBE = new Set(["docx", "docm", "xlsx", "xlsm", "pptx", "pptm"]);

/** Read a file as a base64 ``data:`` URL for the vision request payload. */
function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("attachment read failed"));
    reader.readAsDataURL(file);
  });
}

async function readHead(file: File, count = 8): Promise<Uint8Array> {
  const buffer = await file.slice(0, count).arrayBuffer();
  return new Uint8Array(buffer);
}

function statusLabel(status: StagedAttachment["status"]): string {
  if (status === "scanning") return t("deck.attach.scanning");
  if (status === "abandoned") return t("deck.attach.abandoned");
  return t("deck.attach.ready");
}

export function ComposerAttachments() {
  const [items, setItems] = useState<readonly StagedAttachment[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const itemsRef = useRef<readonly StagedAttachment[]>([]);
  const generationRef = useRef(0);
  itemsRef.current = items;

  const patch = useCallback((id: string, next: Partial<StagedAttachment>) => {
    setItems((current) => {
      const updated = current.map((entry) =>
        entry.id === id ? { ...entry, ...next } : entry);
      itemsRef.current = updated;
      return updated;
    });
  }, []);

  const addFiles = useCallback(
    (files: FileList | readonly File[]) => {
      for (const file of Array.from(files)) {
        const generation = generationRef.current;
        const id = newAttachmentId();
        const kind = detectKind(file.name);
        const previewUrl = kind === "image" ? URL.createObjectURL(file) : undefined;
        const staged: StagedAttachment = {
          id,
          name: file.name,
          size: file.size,
          kind,
          status: "scanning",
          ...(previewUrl ? { previewUrl } : {}),
        };
        setItems((current) => {
          const updated = [...current, staged];
          itemsRef.current = updated;
          return updated;
        });
        const isCurrent = () => attachmentOperationIsCurrent(
          generation,
          generationRef.current,
          itemsRef.current.some((entry) => entry.id === id),
        );

        if (OOXML_PROBE.has(fileExtension(file.name))) {
          void readHead(file)
            .then((head) => {
              if (!isCurrent()) return;
              patch(
                id,
                isRightsProtected(file.name, head)
                  ? { kind: "rms", status: "abandoned" }
                  : { status: "ready" },
              );
            })
            .catch(() => {
              if (isCurrent()) patch(id, { status: "ready" });
            });
        } else if (kind === "image") {
          // Stage the image as send-ready vision evidence: read it as a base64
          // data URL (rebuilt with the validated media type so a blank
          // file.type cannot produce a non-image URL the server rejects) into
          // the external store the submit path drains. Anything that cannot be
          // sent is marked non-sendable with a reason instead of a false
          // "ready", so the operator is never misled about what will be sent.
          const media = imageMediaType(file);
          if (media === null) {
            patch(id, { status: "abandoned", note: t("deck.attach.unsupportedImage") });
          } else if (!reserveComposerAttachment(id)) {
            patch(id, { status: "abandoned", note: t("deck.attach.tooMany") });
          } else {
            void normalizeVisionImage(file)
              .then(async (normalized) => {
                // The tile may have been removed, or a send may have drained
                // and cleared the tray, while this read was in flight. Do not
                // stage a now-orphaned image - that would leak it invisibly
                // into a later turn.
                if (!isCurrent()) return;
                if (normalized.size > MAX_VISION_IMAGE_BYTES) {
                  unstageComposerAttachment(id);
                  patch(id, { status: "abandoned", note: t("deck.attach.tooLarge") });
                  return;
                }
                const normalizedMedia = imageMediaType(normalized);
                if (normalizedMedia === null) {
                  unstageComposerAttachment(id);
                  patch(id, { status: "abandoned", note: t("deck.attach.unsupportedImage") });
                  return;
                }
                const raw = await fileToDataUrl(normalized);
                if (!isCurrent()) return;
                const dataUrl = normalizeImageDataUrl(raw, normalizedMedia);
                if (dataUrl === null) {
                  unstageComposerAttachment(id);
                  patch(id, { status: "abandoned", note: t("deck.attach.readFailed") });
                  return;
                }
                const accepted = stageComposerAttachment(id, {
                  id,
                  name: normalized.name,
                  media_type: normalizedMedia,
                  data_url: dataUrl,
                });
                patch(
                  id,
                  accepted
                    ? { name: normalized.name, size: normalized.size, status: "ready" }
                    : { status: "abandoned", note: t("deck.attach.tooMany") },
                );
              })
              .catch((reason: unknown) => {
                if (!isCurrent()) return;
                unstageComposerAttachment(id);
                patch(
                  id,
                  reason instanceof RangeError
                    ? { status: "abandoned", note: t("deck.attach.tooLarge") }
                    : { status: "abandoned", note: t("deck.attach.readFailed") },
                );
              });
          }
        } else {
          patch(id, { status: "ready" });
        }
      }
    },
    [patch],
  );

  const remove = useCallback((id: string) => {
    unstageComposerAttachment(id);
    setItems((current) => {
      const target = current.find((entry) => entry.id === id);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      const updated = current.filter((entry) => entry.id !== id);
      itemsRef.current = updated;
      return updated;
    });
  }, []);

  // Clear the visual tray, revoking any object URLs first. Bound to the store's
  // drain event so the tray empties on both Enter-send and button-send (a form
  // `submit` event fires only for the button), keeping tray and payload in sync.
  const clearTray = useCallback(() => {
    generationRef.current += 1;
    for (const entry of itemsRef.current) {
      if (entry.previewUrl) URL.revokeObjectURL(entry.previewUrl);
    }
    itemsRef.current = [];
    setItems([]);
  }, []);

  useEffect(() => subscribeComposerAttachmentDrain(clearTray), [clearTray]);

  // Drag-and-drop and clipboard images share the same bounded attachment
  // pipeline. Native text paste remains untouched.
  useEffect(() => {
    const form = inputRef.current?.closest("form");
    if (!form) return;
    const onDragOver = (event: DragEvent) => {
      if (event.dataTransfer?.types.includes("Files")) {
        event.preventDefault();
        setDragging(true);
      }
    };
    const onDragLeave = (event: DragEvent) => {
      if (event.target === form) setDragging(false);
    };
    const onDrop = (event: DragEvent) => {
      if (event.dataTransfer?.files.length) {
        event.preventDefault();
        addFiles(event.dataTransfer.files);
      }
      setDragging(false);
    };
    const onPaste = (event: ClipboardEvent) => {
      const files = clipboardImageFiles(Array.from(event.clipboardData?.items ?? []));
      if (files.length > 0) addFiles(files);
    };
    form.addEventListener("dragover", onDragOver);
    form.addEventListener("dragleave", onDragLeave);
    form.addEventListener("drop", onDrop);
    form.addEventListener("paste", onPaste);
    return () => {
      form.removeEventListener("dragover", onDragOver);
      form.removeEventListener("dragleave", onDragLeave);
      form.removeEventListener("drop", onDrop);
      form.removeEventListener("paste", onPaste);
    };
  }, [addFiles]);

  // Revoke any outstanding object URLs on unmount, and drop any staged
  // attachments so a closed/switched deck never carries them into a later turn.
  useEffect(
    () => () => {
      generationRef.current += 1;
      for (const entry of itemsRef.current) {
        if (entry.previewUrl) URL.revokeObjectURL(entry.previewUrl);
      }
      itemsRef.current = [];
      clearComposerAttachments();
    },
    [],
  );

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        multiple
        class="deck-attach-input"
        hidden
        onChange={(event) => {
          const target = event.target as HTMLInputElement;
          if (target.files?.length) addFiles(target.files);
          target.value = "";
        }}
      />
      {items.length > 0 ? (
        <ul
          class={`deck-attach-tray${dragging ? " is-dragging" : ""}`}
          aria-label={t("deck.attach.tray")}
        >
          {items.map((entry) => (
            <li
              key={entry.id}
              class={`deck-attach-item${entry.status === "abandoned" ? " is-abandoned" : ""}`}
            >
              <span
                class={`deck-attach-thumb is-${entry.kind}`}
                style={
                  entry.previewUrl ? { backgroundImage: `url(${entry.previewUrl})` } : undefined
                }
                aria-hidden="true"
              >
                {entry.previewUrl ? "" : thumbLabel(entry.kind)}
              </span>
              <span class="deck-attach-body">
                <Tooltip content={entry.name}>
                  <span class="deck-attach-name">{entry.name}</span>
                </Tooltip>
                <span class="deck-attach-meta">
                  {entry.status === "abandoned"
                    ? (entry.note ?? t("deck.attach.rmsProtected"))
                    : formatSize(entry.size)}{" "}
                  ·{" "}
                  <span class={`deck-attach-status is-${entry.status}`}>
                    {statusLabel(entry.status)}
                  </span>
                </span>
              </span>
              <Tooltip content={t("deck.attach.remove")}>
                <button
                  type="button"
                  class="deck-attach-remove"
                  aria-label={t("deck.attach.remove")}
                  onClick={() => remove(entry.id)}
                >
                  ×
                </button>
              </Tooltip>
            </li>
          ))}
        </ul>
      ) : null}
      <Tooltip content={t("deck.attach.button")}>
        <button
          type="button"
          class="deck-attach-btn"
          aria-label={t("deck.attach.button")}
          onClick={() => inputRef.current?.click()}
        >
          +
        </button>
      </Tooltip>
    </>
  );
}

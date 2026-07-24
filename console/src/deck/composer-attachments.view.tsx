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
  detectKind,
  fileExtension,
  formatSize,
  isRightsProtected,
  newAttachmentId,
  thumbLabel,
  type StagedAttachment,
} from "./composer-attachments";
import {
  clearComposerAttachments,
  stageComposerAttachment,
  subscribeComposerAttachmentDrain,
  unstageComposerAttachment,
} from "./composer-attachment-store";

const OOXML_PROBE = new Set(["docx", "docm", "xlsx", "xlsm", "pptx", "pptm"]);

/** Raster types the vision narrator accepts, mirroring the server allowlist. */
const SENDABLE_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

/** Per-image byte cap, symmetric to the server DEFAULT_MAX_IMAGE_BYTES. */
const MAX_IMAGE_BYTES = 4 * 1024 * 1024;

/** Resolve a sendable image media type from the file, or null when unsupported. */
function imageMediaType(file: File): string | null {
  if (SENDABLE_IMAGE_TYPES.has(file.type)) return file.type;
  const ext = fileExtension(file.name);
  if (ext === "png") return "image/png";
  if (ext === "jpg" || ext === "jpeg") return "image/jpeg";
  if (ext === "gif") return "image/gif";
  if (ext === "webp") return "image/webp";
  return null;
}

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
  itemsRef.current = items;

  const patch = useCallback((id: string, next: Partial<StagedAttachment>) => {
    setItems((current) =>
      current.map((entry) => (entry.id === id ? { ...entry, ...next } : entry)),
    );
  }, []);

  const addFiles = useCallback(
    (files: FileList | readonly File[]) => {
      for (const file of Array.from(files)) {
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
        setItems((current) => [...current, staged]);

        if (OOXML_PROBE.has(fileExtension(file.name))) {
          void readHead(file)
            .then((head) => {
              patch(
                id,
                isRightsProtected(file.name, head)
                  ? { kind: "rms", status: "abandoned" }
                  : { status: "ready" },
              );
            })
            .catch(() => patch(id, { status: "ready" }));
        } else if (kind === "image") {
          // Stage the image as send-ready vision evidence: read it as a base64
          // data URL into the external store the submit path drains. Oversized
          // or unsupported rasters stay visible but are not sent.
          const media = imageMediaType(file);
          if (media !== null && file.size <= MAX_IMAGE_BYTES) {
            void fileToDataUrl(file)
              .then((dataUrl) => {
                stageComposerAttachment(id, {
                  name: file.name,
                  media_type: media,
                  data_url: dataUrl,
                });
              })
              .catch(() => undefined)
              .finally(() => patch(id, { status: "ready" }));
          } else {
            patch(id, { status: "ready" });
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
      return current.filter((entry) => entry.id !== id);
    });
  }, []);

  // Clear the visual tray, revoking any object URLs first. Bound to the store's
  // drain event so the tray empties on both Enter-send and button-send (a form
  // `submit` event fires only for the button), keeping tray and payload in sync.
  const clearTray = useCallback(() => {
    for (const entry of itemsRef.current) {
      if (entry.previewUrl) URL.revokeObjectURL(entry.previewUrl);
    }
    setItems([]);
  }, []);

  useEffect(() => subscribeComposerAttachmentDrain(clearTray), [clearTray]);

  // Drag-and-drop onto the composer, and clear staged files after a send.
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
    form.addEventListener("dragover", onDragOver);
    form.addEventListener("dragleave", onDragLeave);
    form.addEventListener("drop", onDrop);
    return () => {
      form.removeEventListener("dragover", onDragOver);
      form.removeEventListener("dragleave", onDragLeave);
      form.removeEventListener("drop", onDrop);
    };
  }, [addFiles]);

  // Revoke any outstanding object URLs on unmount, and drop any staged
  // attachments so a closed/switched deck never carries them into a later turn.
  useEffect(
    () => () => {
      for (const entry of itemsRef.current) {
        if (entry.previewUrl) URL.revokeObjectURL(entry.previewUrl);
      }
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
                    ? t("deck.attach.rmsProtected")
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

/**
 * Composer attachment logic - pure helpers for the command-deck file input.
 *
 * The console is read-only: an attachment is staged client-side as *evidence*
 * for Bragi to ground a read-only answer on, never an action. This module only
 * classifies a picked file and decides whether it must be abandoned; the actual
 * upload / scan / analysis is a backend concern wired later. Keeping the logic
 * pure makes the classification and the rights-protection (RMS) heuristic
 * testable without a DOM.
 */

/** Visual + processing category for a staged file. */
export type AttachmentKind =
  | "image"
  | "log"
  | "plan"
  | "word"
  | "excel"
  | "ppt"
  | "zip"
  | "data"
  | "doc"
  | "rms";

/** Where a staged file is in the (client-side) pipeline. */
export type AttachmentStatus = "scanning" | "ready" | "abandoned";

export interface StagedAttachment {
  readonly id: string;
  readonly name: string;
  readonly size: number;
  readonly kind: AttachmentKind;
  readonly status: AttachmentStatus;
  /** Object URL for an image preview; caller revokes it on removal. */
  readonly previewUrl?: string;
  /** Human reason a file was abandoned for something other than RMS
   *  (too large, unsupported raster, over the per-turn cap, or a read
   *  failure), shown in place of the RMS-protected label. */
  readonly note?: string;
}

export interface ClipboardFileItem {
  readonly kind: string;
  readonly type: string;
  getAsFile(): File | null;
}

export const MAX_VISION_IMAGE_EDGE = 2048;

export interface VisionImageDimensions {
  readonly width: number;
  readonly height: number;
}

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "heic", "avif"]);
const WORD_EXT = new Set(["doc", "docx", "docm", "rtf"]);
const EXCEL_EXT = new Set(["xls", "xlsx", "xlsm"]);
const PPT_EXT = new Set(["ppt", "pptx", "pptm"]);
const ZIP_EXT = new Set(["zip", "7z", "rar", "tar", "gz", "tgz", "bz2"]);
const DATA_EXT = new Set(["csv", "json", "yaml", "yml", "tsv", "parquet"]);
const LOG_EXT = new Set(["log", "txt", "out", "err"]);
const PLAN_EXT = new Set(["tf", "tfplan", "tfstate", "hcl"]);
const SENDABLE_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

/** OOXML extensions where an OLE (compound-file) header signals RMS / IRM. */
const OOXML_EXT = new Set(["docx", "docm", "xlsx", "xlsm", "pptx", "pptm"]);

/** Leading bytes of an OLE2 compound file: D0 CF 11 E0 A1 B1 1A E1. */
const OLE_MAGIC = [0xd0, 0xcf, 0x11, 0xe0];
let attachmentSequence = 0;

export function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
}

export function detectKind(name: string): AttachmentKind {
  const ext = fileExtension(name);
  if (IMAGE_EXT.has(ext)) return "image";
  if (WORD_EXT.has(ext)) return "word";
  if (EXCEL_EXT.has(ext)) return "excel";
  if (PPT_EXT.has(ext)) return "ppt";
  if (ZIP_EXT.has(ext)) return "zip";
  if (PLAN_EXT.has(ext)) return "plan";
  if (LOG_EXT.has(ext)) return "log";
  if (DATA_EXT.has(ext)) return "data";
  return "doc";
}

/** Short uppercase label shown on the file-type tile. */
export function thumbLabel(kind: AttachmentKind): string {
  switch (kind) {
    case "image": return "IMG";
    case "log": return "LOG";
    case "plan": return "TF";
    case "word": return "DOC";
    case "excel": return "XLS";
    case "ppt": return "PPT";
    case "zip": return "ZIP";
    case "data": return "DAT";
    case "rms": return "RMS";
    default: return "DOC";
  }
}

/**
 * Rights-protection (RMS / Microsoft Purview) heuristic for a modern Office
 * file. An unprotected OOXML document is a ZIP (starts with `50 4B`); a
 * rights-protected one is wrapped as an OLE2 compound file (starts with
 * `D0 CF 11 E0`). Only OOXML extensions are inspected - a legacy `.doc`/`.xls`
 * is natively OLE and is not RMS.
 */
export function isRightsProtected(name: string, head: Uint8Array): boolean {
  if (!OOXML_EXT.has(fileExtension(name))) return false;
  if (head.length < OLE_MAGIC.length) return false;
  return OLE_MAGIC.every((byte, index) => head[index] === byte);
}

/** Human-readable file size, e.g. "42 KB" or "1.8 MB". */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(1)} GB`;
}

export function newAttachmentId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `att-${crypto.randomUUID()}`;
  }
  attachmentSequence += 1;
  return `att-${Date.now()}-${attachmentSequence.toString(36)}`;
}

export function attachmentOperationIsCurrent(
  startedGeneration: number,
  currentGeneration: number,
  attachmentPresent: boolean,
): boolean {
  return startedGeneration === currentGeneration && attachmentPresent;
}

export function shouldCreateImagePreview(
  kind: AttachmentKind,
  mediaType: string | null,
  reserved: boolean,
): boolean {
  return kind === "image" && mediaType !== null && reserved;
}

/** Return only image files from a clipboard payload. Text and HTML items are
 * left to the textarea's native paste behavior. */
export function clipboardImageFiles(items: readonly ClipboardFileItem[]): File[] {
  const files: File[] = [];
  for (const item of items) {
    if (item.kind !== "file" || !item.type.toLowerCase().startsWith("image/")) continue;
    const file = item.getAsFile();
    if (file) files.push(file);
  }
  return files;
}

/** Resolve the browser-declared image type, using the extension only when the
 * browser supplied no MIME type. A conflicting non-image MIME fails closed. */
export function imageMediaType(file: Pick<File, "name" | "type">): string | null {
  const declared = file.type.trim().toLowerCase();
  if (declared) return SENDABLE_IMAGE_TYPES.has(declared) ? declared : null;
  const ext = fileExtension(file.name);
  if (ext === "png") return "image/png";
  if (ext === "jpg" || ext === "jpeg") return "image/jpeg";
  if (ext === "gif") return "image/gif";
  if (ext === "webp") return "image/webp";
  return null;
}

/** Fit a raster inside the model-facing pixel bound without upscaling. */
export function fitVisionImageDimensions(
  width: number,
  height: number,
  maxEdge = MAX_VISION_IMAGE_EDGE,
): VisionImageDimensions {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new RangeError("image dimensions MUST be positive finite numbers");
  }
  if (!Number.isFinite(maxEdge) || maxEdge < 1) {
    throw new RangeError("image max edge MUST be a positive finite number");
  }
  const scale = Math.min(1, maxEdge / Math.max(width, height));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

/**
 * Rebuild an image data URL with the validated media type, keeping only the
 * base64 body. `FileReader.readAsDataURL` labels the payload with the file's
 * `type`, which some platforms leave blank - yielding `data:;base64,...` or
 * `data:application/octet-stream;base64,...`. The server accepts only
 * `data:image/...`, so a correctly-typed data URL is rebuilt here or the
 * attachment is rejected (null). Pure and DOM-free for testing.
 */
export function normalizeImageDataUrl(dataUrl: string, mediaType: string): string | null {
  const comma = dataUrl.indexOf(",");
  if (comma < 0) return null;
  const body = dataUrl.slice(comma + 1).trim();
  if (!body) return null;
  return `data:${mediaType};base64,${body}`;
}

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
}

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "heic", "avif"]);
const WORD_EXT = new Set(["doc", "docx", "docm", "rtf"]);
const EXCEL_EXT = new Set(["xls", "xlsx", "xlsm"]);
const PPT_EXT = new Set(["ppt", "pptx", "pptm"]);
const ZIP_EXT = new Set(["zip", "7z", "rar", "tar", "gz", "tgz", "bz2"]);
const DATA_EXT = new Set(["csv", "json", "yaml", "yml", "tsv", "parquet"]);
const LOG_EXT = new Set(["log", "txt", "out", "err"]);
const PLAN_EXT = new Set(["tf", "tfplan", "tfstate", "hcl"]);

/** OOXML extensions where an OLE (compound-file) header signals RMS / IRM. */
const OOXML_EXT = new Set(["docx", "docm", "xlsx", "xlsm", "pptx", "pptm"]);

/** Leading bytes of an OLE2 compound file: D0 CF 11 E0 A1 B1 1A E1. */
const OLE_MAGIC = [0xd0, 0xcf, 0x11, 0xe0];

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
  return `att-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

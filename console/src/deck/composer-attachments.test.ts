import { describe, expect, it } from "vitest";
import {
  detectKind,
  fileExtension,
  formatSize,
  isRightsProtected,
  newAttachmentId,
  thumbLabel,
} from "./composer-attachments";

describe("composer-attachments", () => {
  it("classifies files by extension", () => {
    expect(detectKind("grafana-restart-rate.png")).toBe("image");
    expect(detectKind("aks-prod-krc-nginx-pods.log")).toBe("log");
    expect(detectKind("widen-cadence.tfplan")).toBe("plan");
    expect(detectKind("incident-runbook.docx")).toBe("word");
    expect(detectKind("cost-attribution.xlsx")).toBe("excel");
    expect(detectKind("q3-resilience-review.pptx")).toBe("ppt");
    expect(detectKind("support-bundle.zip")).toBe("zip");
    expect(detectKind("events.csv")).toBe("data");
    expect(detectKind("README")).toBe("doc");
  });

  it("is case-insensitive on the extension", () => {
    expect(fileExtension("PLAN.TFPLAN")).toBe("tfplan");
    expect(detectKind("SCREENSHOT.PNG")).toBe("image");
  });

  it("maps each kind to a short tile label", () => {
    expect(thumbLabel("image")).toBe("IMG");
    expect(thumbLabel("word")).toBe("DOC");
    expect(thumbLabel("excel")).toBe("XLS");
    expect(thumbLabel("ppt")).toBe("PPT");
    expect(thumbLabel("zip")).toBe("ZIP");
    expect(thumbLabel("rms")).toBe("RMS");
  });

  it("flags a rights-protected OOXML file (OLE header) as RMS", () => {
    const ole = new Uint8Array([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]);
    expect(isRightsProtected("board-confidential.docx", ole)).toBe(true);
    expect(isRightsProtected("sheet.xlsx", ole)).toBe(true);
  });

  it("treats an unprotected OOXML file (ZIP header) as not RMS", () => {
    const zip = new Uint8Array([0x50, 0x4b, 0x03, 0x04]);
    expect(isRightsProtected("incident-runbook.docx", zip)).toBe(false);
  });

  it("does not flag legacy or non-OOXML files as RMS", () => {
    const ole = new Uint8Array([0xd0, 0xcf, 0x11, 0xe0]);
    // Legacy .doc is natively OLE - not RMS.
    expect(isRightsProtected("legacy.doc", ole)).toBe(false);
    expect(isRightsProtected("archive.zip", ole)).toBe(false);
  });

  it("does not read past a truncated header", () => {
    expect(isRightsProtected("board.docx", new Uint8Array([0xd0, 0xcf]))).toBe(false);
  });

  it("formats sizes in B / KB / MB", () => {
    expect(formatSize(512)).toBe("512 B");
    expect(formatSize(43008)).toBe("42 KB");
    expect(formatSize(1_887_437)).toBe("1.8 MB");
  });

  it("mints unique attachment ids", () => {
    expect(newAttachmentId()).not.toBe(newAttachmentId());
  });
});

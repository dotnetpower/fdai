import { describe, expect, it, vi } from "vitest";
import {
  clipboardImageFiles,
  detectKind,
  fileExtension,
  fitVisionImageDimensions,
  formatSize,
  imageMediaType,
  isRightsProtected,
  newAttachmentId,
  normalizeImageDataUrl,
  thumbLabel,
} from "./composer-attachments";
import {
  MAX_VISION_SOURCE_BYTES,
  normalizeVisionImage,
} from "./composer-image-normalization";

describe("composer-attachments", () => {
  it("fits large screenshots inside the vision pixel bound without distortion", () => {
    expect(fitVisionImageDimensions(7680, 4320)).toEqual({ width: 2048, height: 1152 });
    expect(fitVisionImageDimensions(2160, 3840)).toEqual({ width: 1152, height: 2048 });
  });

  it("does not upscale small images and rejects invalid dimensions", () => {
    expect(fitVisionImageDimensions(1280, 720)).toEqual({ width: 1280, height: 720 });
    expect(() => fitVisionImageDimensions(0, 720)).toThrow(RangeError);
  });

  it("extracts pasted image files and ignores text clipboard items", () => {
    const png = new File([new Uint8Array([1, 2, 3])], "clipboard.png", {
      type: "image/png",
    });
    const textFile = vi.fn(() => null);

    expect(clipboardImageFiles([
      { kind: "string", type: "text/plain", getAsFile: textFile },
      { kind: "file", type: "image/png", getAsFile: () => png },
      { kind: "file", type: "application/pdf", getAsFile: () => null },
    ])).toEqual([png]);
    expect(textFile).not.toHaveBeenCalled();
  });

  it("drops clipboard image entries that do not expose a file", () => {
    expect(clipboardImageFiles([
      { kind: "file", type: "IMAGE/PNG", getAsFile: () => null },
    ])).toEqual([]);
  });

  it("rejects a conflicting declared MIME instead of trusting the extension", () => {
    expect(imageMediaType({ name: "report.png", type: "application/pdf" })).toBeNull();
    expect(imageMediaType({ name: "report.png", type: "IMAGE/PNG" })).toBe("image/png");
    expect(imageMediaType({ name: "report.png", type: "" })).toBe("image/png");
  });

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
    expect(thumbLabel("log")).toBe("LOG");
    expect(thumbLabel("plan")).toBe("TF");
    expect(thumbLabel("data")).toBe("DAT");
    expect(thumbLabel("doc")).toBe("DOC");
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

  it("formats sizes in GB for very large files", () => {
    expect(formatSize(2_147_483_648)).toBe("2.0 GB");
  });

  it("mints unique attachment ids", () => {
    expect(newAttachmentId()).not.toBe(newAttachmentId());
  });

  it("keeps fallback ids unique within the same millisecond", () => {
    vi.stubGlobal("crypto", undefined);
    vi.spyOn(Date, "now").mockReturnValue(1234);

    expect(newAttachmentId()).not.toBe(newAttachmentId());

    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("rebuilds an image data URL with the validated media type", () => {
    // A blank or non-image MIME from FileReader is corrected to the real type.
    expect(normalizeImageDataUrl("data:;base64,AAAB", "image/png")).toBe(
      "data:image/png;base64,AAAB",
    );
    expect(
      normalizeImageDataUrl("data:application/octet-stream;base64,QUJD", "image/jpeg"),
    ).toBe("data:image/jpeg;base64,QUJD");
  });

  it("rejects a data URL with no body or no comma", () => {
    expect(normalizeImageDataUrl("data:image/png;base64,", "image/png")).toBeNull();
    expect(normalizeImageDataUrl("not-a-data-url", "image/png")).toBeNull();
    expect(normalizeImageDataUrl("data:image/png;base64,   ", "image/png")).toBeNull();
  });

  it("rejects an oversized source before allocating a bitmap", async () => {
    const createBitmap = vi.fn();
    vi.stubGlobal("createImageBitmap", createBitmap);
    const file = new File(
      [new Uint8Array(MAX_VISION_SOURCE_BYTES + 1)],
      "oversized.png",
      { type: "image/png" },
    );

    await expect(normalizeVisionImage(file)).rejects.toThrow(RangeError);
    expect(createBitmap).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("rejects a canvas codec fallback with mismatched bytes", async () => {
    const close = vi.fn();
    vi.stubGlobal("createImageBitmap", vi.fn(async () => ({
      width: 4096,
      height: 2048,
      close,
    })));
    vi.stubGlobal("document", {
      createElement: () => ({
        width: 0,
        height: 0,
        getContext: () => ({
          imageSmoothingEnabled: false,
          imageSmoothingQuality: "low",
          drawImage: vi.fn(),
        }),
        toBlob: (callback: (blob: Blob) => void) => callback(
          new Blob([new Uint8Array([1])], { type: "image/png" }),
        ),
      }),
    });
    const file = new File([new Uint8Array([1])], "photo.jpg", { type: "image/jpeg" });

    await expect(normalizeVisionImage(file)).rejects.toThrow(
      "image encoder returned image/png for image/webp",
    );
    expect(close).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });
});

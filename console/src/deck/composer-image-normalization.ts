import {
  fitVisionImageDimensions,
  MAX_VISION_IMAGE_EDGE,
} from "./composer-attachments";

export const MAX_VISION_IMAGE_BYTES = 4 * 1024 * 1024;

const RESIZABLE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

export async function normalizeVisionImage(file: File): Promise<File> {
  const mediaType = file.type.toLowerCase();
  if (!RESIZABLE_TYPES.has(mediaType)) return file;

  const bitmap = await createImageBitmap(file);
  try {
    const dimensions = fitVisionImageDimensions(bitmap.width, bitmap.height);
    if (
      dimensions.width === bitmap.width &&
      dimensions.height === bitmap.height &&
      file.size <= MAX_VISION_IMAGE_BYTES
    ) {
      return file;
    }

    const canvas = document.createElement("canvas");
    canvas.width = dimensions.width;
    canvas.height = dimensions.height;
    const context = canvas.getContext("2d", { alpha: true });
    if (!context) throw new Error("image normalization canvas is unavailable");
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    context.drawImage(bitmap, 0, 0, dimensions.width, dimensions.height);

    let outputType = mediaType === "image/png" ? "image/png" : "image/webp";
    let blob = await canvasBlob(canvas, outputType, outputType === "image/png" ? undefined : 0.92);
    if (blob.size > MAX_VISION_IMAGE_BYTES && outputType === "image/png") {
      outputType = "image/webp";
      blob = await canvasBlob(canvas, outputType, 0.9);
    }
    if (blob.size > MAX_VISION_IMAGE_BYTES) {
      throw new RangeError(`normalized image exceeds ${MAX_VISION_IMAGE_BYTES} bytes`);
    }
    return new File([blob], normalizedName(file.name, outputType), {
      type: outputType,
      lastModified: file.lastModified,
    });
  } finally {
    bitmap.close();
  }
}

function canvasBlob(
  canvas: HTMLCanvasElement,
  mediaType: string,
  quality?: number,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("image normalization failed")),
      mediaType,
      quality,
    );
  });
}

function normalizedName(name: string, mediaType: string): string {
  const extension = mediaType === "image/png" ? "png" : "webp";
  const stem = name.replace(/\.[^.]+$/, "") || "image";
  return `${stem.slice(0, 120)}.${extension}`;
}

export const visionNormalizationPolicy = {
  maxEdge: MAX_VISION_IMAGE_EDGE,
  maxBytes: MAX_VISION_IMAGE_BYTES,
} as const;

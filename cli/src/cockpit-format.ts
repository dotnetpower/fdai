const RESET = "\x1b[0m";
const TRACK = "\x1b[38;2;46;54;62m";
const SPARK_CHARS = ["\u2581", "\u2582", "\u2583", "\u2584", "\u2585", "\u2586", "\u2587", "\u2588"];

function charWidth(codePoint: number): number {
  if (
    (codePoint >= 0x0300 && codePoint <= 0x036f) ||
    (codePoint >= 0x1ab0 && codePoint <= 0x1aff) ||
    (codePoint >= 0x1dc0 && codePoint <= 0x1dff) ||
    (codePoint >= 0x20d0 && codePoint <= 0x20ff) ||
    (codePoint >= 0xfe00 && codePoint <= 0xfe0f) ||
    (codePoint >= 0xfe20 && codePoint <= 0xfe2f) ||
    codePoint === 0x200d
  ) {
    return 0;
  }
  if (
    (codePoint >= 0x1100 && codePoint <= 0x115f) ||
    (codePoint >= 0x2e80 && codePoint <= 0xa4cf) ||
    (codePoint >= 0xac00 && codePoint <= 0xd7a3) ||
    (codePoint >= 0xf900 && codePoint <= 0xfaff) ||
    (codePoint >= 0xfe30 && codePoint <= 0xfe4f) ||
    (codePoint >= 0xff00 && codePoint <= 0xff60) ||
    (codePoint >= 0xffe0 && codePoint <= 0xffe6)
  ) {
    return 2;
  }
  return 1;
}

export function strWidth(value: string): number {
  let width = 0;
  for (const character of value) width += charWidth(character.codePointAt(0)!);
  return width;
}

export function clip(value: string, width: number): string {
  let currentWidth = 0;
  let output = "";
  for (const character of value) {
    const characterWidth = charWidth(character.codePointAt(0)!);
    if (currentWidth + characterWidth > width) break;
    output += character;
    currentWidth += characterWidth;
  }
  return output;
}

export function inputViewport(
  input: readonly string[],
  cursor: number,
  width: number,
): { text: string; caretWidth: number } {
  const boundedWidth = Math.max(1, width);
  const before = input.slice(0, cursor);
  const after = input.slice(cursor);
  let visibleBefore = before;
  let clippedLeft = false;
  while (visibleBefore.length > 0 && strWidth(visibleBefore.join("")) > boundedWidth - 1) {
    visibleBefore = visibleBefore.slice(1);
    clippedLeft = true;
  }
  const prefix = clippedLeft ? "<" : "";
  const beforeText = visibleBefore.join("");
  const caretWidth = strWidth(prefix) + strWidth(beforeText);
  const afterText = clip(after.join(""), Math.max(0, boundedWidth - caretWidth));
  return { text: `${prefix}${beforeText}${afterText}`, caretWidth };
}

export function wrap(value: string, width: number, maxLines: number): string[] {
  const words = value.split(/\s+/);
  const lines: string[] = [];
  let current = "";
  for (let word of words) {
    let candidate = current ? `${current} ${word}` : word;
    if (strWidth(candidate) > width && current) {
      lines.push(current);
      current = word;
      if (lines.length >= maxLines) break;
      candidate = word;
    }
    while (strWidth(candidate) > width && lines.length < maxLines) {
      const chunk = clip(candidate, width);
      if (chunk === "") break;
      lines.push(chunk);
      candidate = [...candidate].slice([...chunk].length).join("");
    }
    current = candidate;
  }
  if (current && lines.length < maxLines) lines.push(current);
  return lines.slice(0, maxLines);
}

export function hbar(fraction: number, width: number, color: string): string {
  const filled = Math.round(Math.max(0, Math.min(1, fraction)) * width);
  return `${color}${"\u2588".repeat(filled)}${TRACK}${"\u2591".repeat(Math.max(0, width - filled))}${RESET}`;
}

export function sparkline(data: number[], width: number): string {
  const samples = data.slice(-width);
  if (samples.length === 0) return `${TRACK}${"\u2581".repeat(width)}${RESET}`;
  const maximum = Math.max(1, ...samples);
  return samples
    .map((value) => SPARK_CHARS[Math.min(7, Math.floor((value / maximum) * 7.999))])
    .join("");
}

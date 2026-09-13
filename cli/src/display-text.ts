/** Remove terminal controls while preserving readable, bounded operator text. */

const UNSAFE_TERMINAL_CONTROLS =
  /[\u0000-\u0009\u000b-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g;

function boundedCodePoints(value: string, maximum: number): string {
  const characters = [...value];
  return characters.length <= maximum ? value : characters.slice(0, maximum).join("");
}

/** Normalize untrusted display text without allowing cursor or bidi control. */
export function safeDisplayText(value: string, maximum = 256 * 1024): string {
  const normalized = value
    .replace(/\r\n?/g, "\n")
    .replace(/\t/g, "  ")
    .replace(UNSAFE_TERMINAL_CONTROLS, "");
  return boundedCodePoints(normalized, maximum);
}

/** Normalize one untrusted display field to a bounded single line. */
export function safeDisplayLine(value: string, maximum = 4096): string {
  return boundedCodePoints(safeDisplayText(value, maximum * 2).replace(/\s+/g, " ").trim(), maximum);
}

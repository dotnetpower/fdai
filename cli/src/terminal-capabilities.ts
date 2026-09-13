/** Terminal behavior derived from the current TTY and explicit user preferences. */
export interface TerminalCapabilities {
  interactive: boolean;
  color: boolean;
  motion: boolean;
  columns: number;
  rows: number;
}

export const MIN_TERMINAL_COLUMNS = 80;
export const MIN_TERMINAL_ROWS = 16;

const FALSE_VALUES = new Set(["0", "false", "no", "off"]);

function enabled(value: string | undefined): boolean {
  return value !== undefined && !FALSE_VALUES.has(value.trim().toLowerCase());
}

/** Resolve color, motion, and minimum geometry without changing terminal state. */
export function resolveTerminalCapabilities(
  input: Pick<NodeJS.ReadStream, "isTTY" | "setRawMode">,
  output: Pick<NodeJS.WriteStream, "isTTY" | "columns" | "rows">,
  env: Readonly<Record<string, string | undefined>> = process.env,
): TerminalCapabilities {
  const columns = output.columns && output.columns > 0 ? output.columns : 80;
  const rows = output.rows && output.rows > 0 ? output.rows : 24;
  const terminal = env.TERM?.trim().toLowerCase();
  const interactive = Boolean(
    input.isTTY &&
      output.isTTY &&
      typeof input.setRawMode === "function" &&
      terminal !== "dumb" &&
      columns >= MIN_TERMINAL_COLUMNS &&
      rows >= MIN_TERMINAL_ROWS,
  );
  const color = interactive && env.NO_COLOR === undefined && terminal !== "dumb";
  const motion = interactive && !enabled(env.FDAI_REDUCED_MOTION);
  return { interactive, color, motion, columns, rows };
}

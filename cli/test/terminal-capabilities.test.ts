import { describe, expect, it } from "vitest";

import { resolveTerminalCapabilities } from "../src/terminal-capabilities.js";

const input = (tty: boolean) =>
  ({ isTTY: tty, setRawMode: () => undefined }) as unknown as NodeJS.ReadStream;
const output = (tty: boolean, columns = 100, rows = 30) =>
  ({ isTTY: tty, columns, rows }) as NodeJS.WriteStream;

describe("resolveTerminalCapabilities", () => {
  it("enables the full interface only for a sufficiently sized TTY", () => {
    expect(resolveTerminalCapabilities(input(true), output(true), { TERM: "xterm" })).toEqual({
      interactive: true,
      color: true,
      motion: true,
      columns: 100,
      rows: 30,
    });
    expect(resolveTerminalCapabilities(input(false), output(true), { TERM: "xterm" }).interactive)
      .toBe(false);
    expect(resolveTerminalCapabilities(input(true), output(true, 79, 30), { TERM: "xterm" }).interactive)
      .toBe(false);
  });

  it("respects no-color, reduced-motion, and dumb-terminal preferences", () => {
    const quiet = resolveTerminalCapabilities(input(true), output(true), {
      TERM: "xterm",
      NO_COLOR: "1",
      FDAI_REDUCED_MOTION: "1",
    });
    expect(quiet).toMatchObject({ interactive: true, color: false, motion: false });
    expect(resolveTerminalCapabilities(input(true), output(true), { TERM: "dumb" }).interactive)
      .toBe(false);
  });
});

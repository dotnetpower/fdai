import { describe, expect, it } from "vitest";

import { CLI_HELP, isHelpRequest, parseCliArgs } from "../src/args.js";

describe("parseCliArgs", () => {
  it("returns stable defaults", () => {
    expect(parseCliArgs([])).toEqual({
      surface: "cli",
      source: "sample",
      mode: "needs-me",
      locale: "en",
      apiUrl: "http://127.0.0.1:8010",
    });
  });

  it("parses the documented equals-style flags", () => {
    expect(
      parseCliArgs([
        "--surface=text",
        "--source=api",
        "--mode=all-clear",
        "--locale=ko",
        "--api=http://localhost:9000/base",
      ]),
    ).toEqual({
      surface: "text",
      source: "api",
      mode: "all-clear",
      locale: "ko",
      apiUrl: "http://localhost:9000/base",
    });
  });

  it("parses conventional split flags", () => {
    expect(parseCliArgs(["--surface", "teams", "--source", "api", "--locale", "ko"]))
      .toMatchObject({ surface: "teams", source: "api", locale: "ko" });
  });

  it("rejects a split flag without a value", () => {
    expect(() => parseCliArgs(["--surface", "--source=api"])).toThrow(
      /missing value for --surface/,
    );
  });

  it("rejects unknown and duplicate options", () => {
    expect(() => parseCliArgs(["--soruce=api"])).toThrow(/unknown option --soruce/);
    expect(() => parseCliArgs(["--source=api", "--source", "sample"])).toThrow(
      /duplicate option --source/,
    );
  });

  it("rejects an empty equals-style value", () => {
    expect(() => parseCliArgs(["--api="])).toThrow(/missing value for --api/);
  });

  it("validates the shared Operator API base URL", () => {
    expect(() => parseCliArgs(["--api=not-a-url"])).toThrow(/invalid --api URL/);
    expect(() => parseCliArgs(["--api=ftp://example.com"])).toThrow(/http or https/);
    expect(() => parseCliArgs(["--api=https://user:pass@example.com"])).toThrow(
      /must not contain credentials/,
    );
    expect(() => parseCliArgs(["--api=https://example.com?x=1"])).toThrow(
      /must not contain a query or fragment/,
    );
  });

  it.each([
    ["surface", ["cli", "text", "slack", "teams"]],
    ["source", ["sample", "api"]],
    ["mode", ["needs-me", "all-clear"]],
    ["locale", ["en", "ko"]],
  ] as const)("accepts every documented %s value", (name, values) => {
    for (const value of values) {
      expect(parseCliArgs([`--${name}=${value}`])).toHaveProperty(
        name === "api" ? "apiUrl" : name,
        value,
      );
    }
  });

  it("resolves locale by flag, environment, then English", () => {
    expect(parseCliArgs([], { FDAI_LOCALE: "ko" }).locale).toBe("ko");
    expect(parseCliArgs(["--locale=en"], { FDAI_LOCALE: "ko" }).locale).toBe("en");
    expect(parseCliArgs([], {}).locale).toBe("en");
  });

  it("detects both help spellings and documents the shared backend", () => {
    expect(isHelpRequest(["--help"])).toBe(true);
    expect(isHelpRequest(["-h"])).toBe(true);
    expect(isHelpRequest([])).toBe(false);
    expect(CLI_HELP).toContain("POST /chat");
  });
});

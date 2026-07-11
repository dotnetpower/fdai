import { describe, expect, test } from "vitest";
import { safeExternalHref } from "./ui";

/**
 * ExternalLink is used to render URLs that originate on the read-API wire
 * (rule provenance source_url, generated PR links, etc.). safeExternalHref
 * is the trust boundary: only absolute http(s) URLs pass; a javascript:,
 * data:, or vbscript: URI is dropped (DOM-based XSS, OWASP A03).
 */

describe("safeExternalHref", () => {
  test("passes absolute http(s) URLs through", () => {
    expect(safeExternalHref("https://example.com/x")).toBe("https://example.com/x");
    expect(safeExternalHref("http://localhost:8080/y")).toBe("http://localhost:8080/y");
  });

  test("rejects javascript: / data: / vbscript: URIs", () => {
    expect(safeExternalHref("javascript:alert(1)")).toBeNull();
    expect(safeExternalHref("JavaScript:alert(1)")).toBeNull();
    expect(safeExternalHref("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeExternalHref("vbscript:msgbox(1)")).toBeNull();
  });

  test("rejects unparseable, relative, and empty values", () => {
    expect(safeExternalHref("not a url")).toBeNull();
    expect(safeExternalHref("/relative/path")).toBeNull();
    expect(safeExternalHref("")).toBeNull();
  });
});

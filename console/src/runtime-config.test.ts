import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";

import { parseConsoleRuntimeConfig, type ConsoleRuntimeConfig } from "./runtime-config";

const runtimeConfig: ConsoleRuntimeConfig = {
  schema_version: "fdai.console-runtime.v1",
  operator_api_base_url: "https://operator.example.com/api",
  ingestion_api_base_url: "https://ingestion.example.com",
  tenant_id: "00000000-0000-0000-0000-000000000001",
  spa_client_id: "00000000-0000-0000-0000-000000000002",
  api_scope: "api://00000000-0000-0000-0000-000000000003/access_as_user",
};

describe("Console runtime configuration", () => {
  test.each([undefined, null])("allows absent configuration: %s", (value) => {
    expect(parseConsoleRuntimeConfig(value)).toBeNull();
  });

  test("returns a detached validated public binding without mutating input", () => {
    const input = Object.freeze({ ...runtimeConfig });
    const parsed = parseConsoleRuntimeConfig(input);

    expect(parsed).toEqual(runtimeConfig);
    expect(parsed).not.toBe(input);
    expect(input).toEqual(runtimeConfig);
  });

  test.each([
    { label: "false", value: false },
    { label: "true", value: true },
    { label: "number", value: 0 },
    { label: "empty string", value: "" },
    { label: "JSON string", value: "{}" },
    { label: "empty array", value: [] },
    { label: "config array", value: [runtimeConfig] },
    { label: "function", value: () => runtimeConfig },
  ])(
    "rejects non-object or array configuration: $label",
    ({ value }) => {
      expect(() => parseConsoleRuntimeConfig(value)).toThrow("must be an object");
    },
  );

  test.each(Object.keys(runtimeConfig))("rejects missing field %s", (field) => {
    const input: Record<string, unknown> = { ...runtimeConfig };
    delete input[field];

    expect(() => parseConsoleRuntimeConfig(input)).toThrow("exactly the supported fields");
  });

  test.each(["devMode", "localAzureCliAuth", "localLoginPrompt", "token", "extra"])(
    "rejects unsupported field %s",
    (field) => {
      expect(() => parseConsoleRuntimeConfig({ ...runtimeConfig, [field]: true })).toThrow(
        "exactly the supported fields",
      );
    },
  );

  test("rejects inherited fields and symbol additions", () => {
    expect(() => parseConsoleRuntimeConfig(Object.create(runtimeConfig))).toThrow(
      "exactly the supported fields",
    );
    expect(() => parseConsoleRuntimeConfig({
      ...runtimeConfig,
      [Symbol("extra")]: true,
    })).toThrow("exactly the supported fields");
  });

  test.each([undefined, null, 1, "fdai.console-runtime.v2", "fdai.console-runtime.v1\n"])(
    "rejects unsupported schema version: %s",
    (schema_version) => {
      expect(() => parseConsoleRuntimeConfig({ ...runtimeConfig, schema_version })).toThrow(
        "schema_version is unsupported",
      );
    },
  );

  describe.each(["operator_api_base_url", "ingestion_api_base_url"] as const)("%s", (field) => {
    test.each([
      null,
      1,
      "",
      "/api",
      "//example.com",
      "http://example.com",
      "javascript:alert(1)",
      "https:example.com",
      "https:/example.com",
      "https:///example.com",
      "https://",
      "https://user:password@example.com",
      "https://user@example.com",
      "https://@example.com",
      "https://example.com?token=value",
      "https://example.com?",
      "https://example.com/#fragment",
      "https://example.com/#",
      "https://example.com\\path",
      "https://example.com\n",
      " https://example.com",
      "https://example.com:invalid",
      "https://example.com:65536",
      "https://example.com/설정",
    ])("rejects unsafe base URL: %s", (value) => {
      expect(() => parseConsoleRuntimeConfig({ ...runtimeConfig, [field]: value })).toThrow(
        `${field} must be an HTTPS base URL`,
      );
    });

    test.each([...Array.from({ length: 32 }, (_, code) => code), 127])(
      "rejects ASCII control character %i before URL normalization",
      (code) => {
        const value = `https://example.com/api${String.fromCharCode(code)}path`;

        expect(() => parseConsoleRuntimeConfig({ ...runtimeConfig, [field]: value })).toThrow(
          `${field} must be an HTTPS base URL`,
        );
      },
    );

    test.each(["https://example.com", "https://example.com/api/v1/", "https://example.com:8443/api"])(
      "preserves an HTTPS base URL: %s",
      (value) => {
        expect(parseConsoleRuntimeConfig({ ...runtimeConfig, [field]: value })?.[field]).toBe(value);
      },
    );
  });

  test.each(["access_as_user", ".default", "1scope", "-scope", "_scope", "access.read-v1"])(
    "accepts the shared ASCII API scope grammar: %s",
    (identifier) => {
      const api_scope = `api://00000000-0000-0000-0000-000000000003/${identifier}`;

      expect(parseConsoleRuntimeConfig({ ...runtimeConfig, api_scope })?.api_scope).toBe(api_scope);
    },
  );

  describe.each(["tenant_id", "spa_client_id"] as const)("%s", (field) => {
    test.each([
      null,
      1,
      "",
      "not-a-uuid",
      "00000000-0000-0000-0000-00000000000z",
      "{00000000-0000-0000-0000-000000000001}",
      "00000000-0000-0000-0000-000000000001\n",
    ])("rejects an invalid UUID: %s", (value) => {
      expect(() => parseConsoleRuntimeConfig({ ...runtimeConfig, [field]: value })).toThrow(
        `${field} must be a UUID`,
      );
    });
  });

  test.each([
    null,
    1,
    "",
    "api://not-a-uuid/access",
    "https://00000000-0000-0000-0000-000000000003/access",
    "api://00000000-0000-0000-0000-000000000003/",
    "api://00000000-0000-0000-0000-000000000003/access/more",
    "api://00000000-0000-0000-0000-000000000003/access other",
    "api://00000000-0000-0000-0000-000000000003/access?query",
    "api://00000000-0000-0000-0000-000000000003/access#fragment",
    "api://00000000-0000-0000-0000-000000000003/*",
    "api://00000000-0000-0000-0000-000000000003/읽기",
    "api://00000000-0000-0000-0000-000000000003/access\n",
  ])("rejects an invalid API scope: %s", (api_scope) => {
    expect(() => parseConsoleRuntimeConfig({ ...runtimeConfig, api_scope })).toThrow(
      "api_scope must use api://UUID/ASCII_scope_identifier",
    );
  });

  test("ships the exact null placeholder used by the installer", () => {
    const source = readFileSync(new URL("../public/fdai-config.js", import.meta.url), "utf8");

    expect(source).toBe("globalThis.__FDAI_CONSOLE_CONFIG__ = null;\n");
    expect(parseConsoleRuntimeConfig(null)).toBeNull();
  });

  test("loads the same-origin classic configuration script before the module entry", () => {
    const index = readFileSync(new URL("../index.html", import.meta.url), "utf8");
    const configTag = '<script src="/fdai-config.js"></script>';
    const mainTag = '<script type="module" src="/src/main.tsx"></script>';

    expect(index.match(/<script\b[^>]*src="\/fdai-config\.js"[^>]*><\/script>/g)).toEqual([configTag]);
    expect(index.indexOf(configTag)).toBeLessThan(index.indexOf(mainTag));
    expect(index).toContain(mainTag);
  });

  test("prevents the hosting layer from caching installation-specific bindings", () => {
    const hosting = JSON.parse(
      readFileSync(new URL("../public/staticwebapp.config.json", import.meta.url), "utf8"),
    );
    expect(hosting.routes).toContainEqual({
      route: "/fdai-config.js",
      headers: { "Cache-Control": "no-store" },
    });
  });
});

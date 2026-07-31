import { describe, expect, it } from "vitest";

import { formatJsonValue } from "./json-code-block";

describe("formatJsonValue", () => {
  it("pretty-prints nested object and array JSON", () => {
    expect(formatJsonValue('{"status":"ready","items":[1,{"ok":true}]}')).toEqual({
      isJson: true,
      text: [
        "{",
        '  "status": "ready",',
        '  "items": [',
        "    1,",
        "    {",
        '      "ok": true',
        "    }",
        "  ]",
        "}",
      ].join("\n"),
    });
  });

  it("formats structured values without converting through a string parser", () => {
    expect(formatJsonValue({ count: 2 })).toEqual({
      isJson: true,
      text: '{\n  "count": 2\n}',
    });
  });

  it("keeps non-string primitives in the plain-text path", () => {
    expect(formatJsonValue(null)).toEqual({ text: "null", isJson: false });
    expect(formatJsonValue(42)).toEqual({ text: "42", isJson: false });
  });

  it.each([
    "query_inventory --status running",
    "{malformed",
    "true",
    '"plain string"',
  ])("preserves non-object JSON or plain text exactly", (value) => {
    expect(formatJsonValue(value)).toEqual({ text: value, isJson: false });
  });
});

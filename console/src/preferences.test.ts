import { describe, expect, test } from "vitest";
import {
  acceptStoredConsolePreference,
  readConsolePreferences,
  resetConsolePreferences,
  setConsolePreference,
} from "./preferences";

function storage(values: Readonly<Record<string, string>>): Pick<Storage, "getItem"> {
  return { getItem: (key) => values[key] ?? null };
}

describe("console preferences", () => {
  test("uses stable defaults without browser state", () => {
    expect(readConsolePreferences("", null)).toEqual({
      theme: "light",
      locale: "en",
      motion: "system",
      showTokenUsage: true,
    });
  });

  test("loads validated browser-local preferences", () => {
    expect(readConsolePreferences("", storage({
      "fdai:console:theme": "dark",
      "fdai:console:locale": "ko",
      "fdai:console:motion": "reduced",
      "fdai:console:show-token-usage": "false",
    }))).toEqual({
      theme: "dark",
      locale: "ko",
      motion: "reduced",
      showTokenUsage: false,
    });
  });

  test("lets an explicit URL locale override stored locale", () => {
    expect(readConsolePreferences("?locale=en", storage({
      "fdai:console:locale": "ko",
    })).locale).toBe("en");
  });

  test("rejects invalid stored values", () => {
    expect(readConsolePreferences("", storage({
      "fdai:console:theme": "system",
      "fdai:console:locale": "fr",
      "fdai:console:motion": "full",
      "fdai:console:show-token-usage": "maybe",
    }))).toEqual({
      theme: "light",
      locale: "en",
      motion: "system",
      showTokenUsage: true,
    });
  });

  test("uses an in-memory fallback when browser storage is unavailable", () => {
    setConsolePreference("theme", "dark");
    expect(readConsolePreferences("", null).theme).toBe("dark");
    resetConsolePreferences();
    expect(readConsolePreferences("", null).theme).toBe("light");
  });

  test("accepts a newer preference written by another tab", () => {
    setConsolePreference("theme", "light");
    expect(acceptStoredConsolePreference("fdai:console:theme")).toBe(true);
    expect(readConsolePreferences("", storage({ "fdai:console:theme": "dark" })).theme).toBe("dark");
    expect(acceptStoredConsolePreference("unrelated")).toBe(false);
    resetConsolePreferences();
  });
});

import { describe, expect, test } from "vitest";
import { UserContextRequestError } from "../user-context-client";
import { conversationHydrationFailureStatus } from "./use-command-deck-sessions";

describe("conversation history hydration", () => {
  test.each([404, 501, 503])("classifies HTTP %s as unavailable", (status) => {
    expect(conversationHydrationFailureStatus(
      new UserContextRequestError("unavailable", status),
    )).toBe("unavailable");
  });

  test("keeps unexpected and transport failures visible as errors", () => {
    expect(conversationHydrationFailureStatus(
      new UserContextRequestError("failed", 500),
    )).toBe("error");
    expect(conversationHydrationFailureStatus(new Error("network failed"))).toBe("error");
  });
});

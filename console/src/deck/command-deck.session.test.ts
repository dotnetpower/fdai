import { describe, expect, test } from "vitest";
import { sessionIdFor } from "./command-deck";

describe("Deck backend session IDs", () => {
  test("isolates transcripts and restores an existing session ID", () => {
    const sessions = new Map<string, string>();
    let next = 0;
    const create = () => `session-${++next}`;

    const general = sessionIdFor(sessions, "screen", create);
    const forseti = sessionIdFor(sessions, "agent:Forseti", create);

    expect(general).not.toBe(forseti);
    expect(sessionIdFor(sessions, "screen", create)).toBe(general);
    expect(next).toBe(2);
  });
});
import { describe, expect, it } from "vitest";
import { parseTurns, serializeTurns, type PersistedTurn } from "./transcript-store";

describe("serializeTurns", () => {
  it("round-trips completed turns", () => {
    const turns = [
      { id: "1", role: "operator" as const, text: "what is the tier mix?", at: "10:00:00" },
      { id: "2", role: "deck" as const, text: "T0 78%", at: "10:00:01", source: "llm:x" },
    ];
    const parsed = parseTurns(serializeTurns(turns));
    expect(parsed).toHaveLength(2);
    expect(parsed[0]!.text).toBe("what is the tier mix?");
    expect(parsed[1]!.source).toBe("llm:x");
  });

  it("drops a still-streaming turn", () => {
    const turns = [
      { id: "1", role: "operator" as const, text: "hi", at: "10:00:00" },
      { id: "2", role: "deck" as const, text: "partial", at: "10:00:01", streaming: true },
    ];
    const parsed = parseTurns(serializeTurns(turns));
    expect(parsed).toHaveLength(1);
    expect(parsed[0]!.id).toBe("1");
  });

  it("drops empty-text turns", () => {
    const turns = [
      { id: "1", role: "operator" as const, text: "   ", at: "10:00:00" },
      { id: "2", role: "deck" as const, text: "real", at: "10:00:01" },
    ];
    const parsed = parseTurns(serializeTurns(turns));
    expect(parsed).toHaveLength(1);
    expect(parsed[0]!.id).toBe("2");
  });

  it("caps to the most recent maxTurns", () => {
    const turns: PersistedTurn[] = Array.from({ length: 5 }, (_, i) => ({
      id: String(i),
      role: "operator" as const,
      text: `q${i}`,
      at: "10:00:00",
    }));
    const parsed = parseTurns(serializeTurns(turns, 2));
    expect(parsed.map((t) => t.id)).toEqual(["3", "4"]);
  });
});

describe("parseTurns", () => {
  it("returns [] for null, empty, or malformed JSON", () => {
    expect(parseTurns(null)).toEqual([]);
    expect(parseTurns("")).toEqual([]);
    expect(parseTurns("not json")).toEqual([]);
    expect(parseTurns("{}")).toEqual([]);
  });

  it("skips entries missing required fields or with a bad role", () => {
    const raw = JSON.stringify([
      { id: "1", role: "operator", text: "ok", at: "10:00:00" },
      { id: "2", role: "system", text: "bad role", at: "10:00:00" },
      { role: "deck", text: "no id", at: "10:00:00" },
      { id: "4", role: "deck", at: "10:00:00" },
    ]);
    const parsed = parseTurns(raw);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]!.id).toBe("1");
  });
});

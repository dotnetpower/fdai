import { describe, expect, it } from "vitest";
import { OperatorApiError } from "../api";
import {
  decodeStewardshipCandidates,
  stewardshipActivationIdempotencyKey,
  type StewardshipCandidate,
} from "../api-stewardship";
import { submitActivation } from "./stewardship-candidates";

const candidate: StewardshipCandidate = {
  candidate_id: "0123456789abcdef",
  candidate_digest: "a".repeat(64),
  title: "Ownership revision",
  body: "Freyr steward",
  yaml: "agents: []",
  state: "open",
  recorded_at: "2026-10-22T00:00:00+00:00",
};

describe("stewardship candidate projection", () => {
  it("decodes a Core projection and rejects a malformed item as a whole", () => {
    expect(decodeStewardshipCandidates({ items: [candidate] })).toEqual([candidate]);
    expect(() => decodeStewardshipCandidates({ items: [{ ...candidate, candidate_digest: "short" }] })).toThrow();
    expect(() => decodeStewardshipCandidates({ items: [{ ...candidate, state: "merged" }] })).toThrow();
    expect(() => decodeStewardshipCandidates({})).toThrow();
  });
});

describe("stewardship activation", () => {
  it("sends only the id and digest the Owner reviewed, under a nonce-scoped key", async () => {
    const calls: Array<{ body: unknown; key: string }> = [];
    const result = await submitActivation(
      {
        postJson: async <T,>(_path: string, body: Record<string, unknown>, key: string) => {
          calls.push({ body, key });
          return { request_id: "operator-1", dispatch_status: "pending" } as T;
        },
      },
      candidate,
      "nonce-1",
    );
    expect(result).toBe("queued");
    expect(calls).toEqual([
      {
        body: { candidate_id: candidate.candidate_id, candidate_digest: candidate.candidate_digest },
        key: stewardshipActivationIdempotencyKey(
          { candidate_id: candidate.candidate_id, candidate_digest: candidate.candidate_digest },
          "nonce-1",
        ),
      },
    ]);
  });

  it("classifies a 403 as forbidden and any other failure as failed", async () => {
    const reject = (status: number) => ({
      postJson: async <T,>(): Promise<T> => { throw new OperatorApiError(status, "denied"); },
    });
    expect(await submitActivation(reject(403), candidate, "n")).toBe("forbidden");
    expect(await submitActivation(reject(503), candidate, "n")).toBe("failed");
  });
});

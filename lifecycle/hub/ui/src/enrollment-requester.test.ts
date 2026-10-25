import { describe, expect, it } from "vitest";
import { enrollmentRequester } from "./enrollment-requester";

describe("enrollment requester", () => {
  it("names the installation Agent with a short object id", () => {
    expect(
      enrollmentRequester({
        requested_by: "00000000-0000-0000-0000-000000000000",
        requested_via: "agent",
      }),
    ).toEqual({ label: "Requested by installation Agent 00000000", fromAgent: true });
  });

  it("distinguishes an operator submission", () => {
    expect(enrollmentRequester({ requested_by: "approved-human", requested_via: "operator" })).toEqual({
      label: "Requested by operator",
      fromAgent: false,
    });
  });

  it.each([
    { requested_by: null, requested_via: null },
    {},
    { requested_by: "agent-object", requested_via: null },
    { requested_by: null, requested_via: "agent" as const },
  ])("does not claim an Agent or operator without both facts: %j", (request) => {
    expect(enrollmentRequester(request)).toEqual({
      label: "Requested from a signed file",
      fromAgent: false,
    });
  });
});

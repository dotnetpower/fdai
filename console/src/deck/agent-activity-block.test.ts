import { describe, expect, it } from "vitest";

import { parseAnswer } from "./rich-parse";

describe("recorded agent activity rich block", () => {
  it("parses the deterministic English activity list", () => {
    expect(parseAnswer([
      "Recorded agent activity:",
      "",
      "- Forseti: rca.hypothesis at 2026-08-03T22:46:54.615337+00:00",
      "- Heimdall: incident.open at 2026-08-03T22:25:41.577957+00:00",
    ].join("\n"))).toEqual([{
      kind: "agent-activity",
      locale: "en",
      items: [
        {
          agent: "Forseti",
          event: "rca.hypothesis",
          at: "2026-08-03T22:46:54.615337+00:00",
        },
        {
          agent: "Heimdall",
          event: "incident.open",
          at: "2026-08-03T22:25:41.577957+00:00",
        },
      ],
    }]);
  });

  it("parses the deterministic Korean activity list", () => {
    expect(parseAnswer([
      "기록된 에이전트 활동:",
      "- Forseti: 2026-08-03T22:46:54.615337+00:00에 rca.hypothesis 기록",
    ].join("\n"))).toEqual([{
      kind: "agent-activity",
      locale: "ko",
      items: [{
        agent: "Forseti",
        event: "rca.hypothesis",
        at: "2026-08-03T22:46:54.615337+00:00",
      }],
    }]);
  });

  it("leaves malformed activity content as ordinary prose and list content", () => {
    expect(parseAnswer([
      "Recorded agent activity:",
      "- Forseti: unsupported text",
    ].join("\n")).map((segment) => segment.kind)).toEqual(["text", "list"]);
  });
});

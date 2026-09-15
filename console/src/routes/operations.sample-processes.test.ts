import { describe, expect, it } from "vitest";
import { sampleProcessResponse } from "./operations.sample-processes";
import { decodeProcessJournal, decodeProcessList } from "./processes.model";

describe("Process sample presentation", () => {
  it("provides three selectable runs with consistent journals and no transition authority", () => {
    const list = decodeProcessList(sampleProcessResponse("/views/process"));
    expect(list.synthetic).toBe(true);
    expect(list.items.map((item) => item.status)).toEqual(["waiting", "waiting", "failed"]);
    for (const item of list.items) {
      const journal = decodeProcessJournal(sampleProcessResponse(`/views/process/${item.id}/events`));
      expect(journal.process.id).toBe(item.id);
      expect(journal.control.permitted_transitions).toEqual([]);
      expect(journal.events).toHaveLength(journal.count);
    }
  });

  it("includes inspectable investigation and planning evidence without claiming selection", () => {
    const journal = decodeProcessJournal(sampleProcessResponse("/views/process/sample-process-1/events"));
    expect(journal.investigation?.round_count).toBe(2);
    expect(journal.planning?.plan?.selected_option_id).toBeNull();
    expect(journal.planning?.plan?.complete).toBe(false);
    expect(journal.process.correlation_id).toBe("sample-correlation-1");
  });

  it("does not substitute a record for unknown process identities or mutation paths", () => {
    expect(sampleProcessResponse("/views/process/missing/events")).toBeUndefined();
    expect(sampleProcessResponse("/workflows/sample-process-1/resume")).toBeUndefined();
  });
});

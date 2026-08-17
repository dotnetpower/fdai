import { describe, expect, it } from "vitest";
import {
  presentationActivity,
  presentationActor,
  presentationActors,
  presentationDuration,
  presentationSeverity,
  presentationTimeZoneLabel,
  presentationTimestamp,
} from "./presentation-value";

describe("presentation values", () => {
  it("renders an RFC 3339 instant in an explicit operator timezone", () => {
    expect(presentationTimestamp(
      "2026-08-16T04:11:50.373225+00:00",
      "en-US",
      "Asia/Seoul",
    )).toEqual({
      kind: "timestamp",
      date: "Aug 16, 2026",
      time: "13:11:50 KST",
      dateTime: "2026-08-16T04:11:50.373225+00:00",
    });
  });

  it("leaves malformed and date-only values unformatted", () => {
    expect(presentationTimestamp("2026-08-16", "en-US", "UTC")).toBeNull();
    expect(presentationTimestamp("not-a-date", "en-US", "UTC")).toBeNull();
  });

  it("derives a bounded elapsed duration from verified timestamps", () => {
    expect(presentationDuration(
      "2026-08-16T04:11:50.373225+00:00",
      "2026-08-16T04:32:56.538200+00:00",
    )).toBe("21m 6s");
    expect(presentationDuration(
      "2026-08-16T04:32:56.538200+00:00",
      "2026-08-16T04:11:50.373225+00:00",
    )).toBeNull();
  });

  it("summarizes long actor lists without losing the raw value", () => {
    expect(presentationActors("Heimdall, fdai.notifications.hil_sink, operator-b")).toEqual({
      visible: ["Heimdall", "fdai.notifications.hil_sink"],
      hiddenCount: 1,
    });
  });

  it("renders service actors and severities as display labels", () => {
    expect(presentationActor("fdai.core.notifications.router")).toBe("Notifications Router");
    expect(presentationActor("fdai.notifications.hil_sink")).toBe("Approval Sink");
    expect(presentationSeverity("sev2")).toBe("SEV 2");
    expect(presentationTimeZoneLabel("Asia/Seoul")).toBe("KST");
  });

  it("turns canonical activity tokens into readable labels", () => {
    expect(presentationActivity("notification.escalation")).toBe("Notification escalation");
  });
});

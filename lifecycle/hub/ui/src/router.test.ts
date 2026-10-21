import { describe, expect, test } from "vitest";
import { enrollmentPath, installationPath, parseRoute, planPath } from "./router";

describe("parseRoute", () => {
  test("root and /installations list the installations screen", () => {
    expect(parseRoute("/")).toEqual({ kind: "installations" });
    expect(parseRoute("/installations")).toEqual({ kind: "installations" });
  });

  test("read-only inventory routes are distinct from catalog mutation", () => {
    expect(parseRoute("/available-releases")).toEqual({ kind: "releases" });
    expect(parseRoute("/configuration-packages")).toEqual({ kind: "configurations" });
    expect(parseRoute("/catalog")).toEqual({ kind: "catalog" });
  });

  test("an installation id selects the detail screen", () => {
    expect(parseRoute("/installations/prod")).toEqual({
      kind: "installation",
      installationId: "prod",
    });
  });

  test("a Plan id under an installation selects the Plan screen", () => {
    expect(parseRoute("/installations/prod/plans/prod-00000001")).toEqual({
      kind: "plan",
      installationId: "prod",
      planId: "prod-00000001",
    });
  });

  test("/enrollments lists pending requests and an id selects one", () => {
    expect(parseRoute("/enrollments")).toEqual({ kind: "enrollments" });
    expect(parseRoute("/enrollments/analytics-prod")).toEqual({
      kind: "enrollment",
      installationId: "analytics-prod",
    });
  });

  test("an unrecognized path falls back to not-found", () => {
    expect(parseRoute("/installations/prod/plans")).toEqual({
      kind: "not-found",
      path: "/installations/prod/plans",
    });
    expect(parseRoute("/vendor/releases")).toEqual({
      kind: "not-found",
      path: "/vendor/releases",
    });
  });
});

describe("path builders round-trip through parseRoute", () => {
  test("installationPath", () => {
    expect(parseRoute(installationPath("dr-standby"))).toEqual({
      kind: "installation",
      installationId: "dr-standby",
    });
  });

  test("planPath", () => {
    expect(parseRoute(planPath("prod", "prod-00000002"))).toEqual({
      kind: "plan",
      installationId: "prod",
      planId: "prod-00000002",
    });
  });

  test("enrollmentPath", () => {
    expect(parseRoute(enrollmentPath("enr-7"))).toEqual({
      kind: "enrollment",
      installationId: "enr-7",
    });
  });
});

import { describe, expect, test } from "vitest";

import {
  environmentDeploymentHref,
  environmentDeploymentTabFromSegment,
  nextEnvironmentDeploymentTab,
} from "./environment-deployment";

describe("environment and deployment navigation", () => {
  test("uses readiness as the default and rejects unknown views", () => {
    expect(environmentDeploymentTabFromSegment(undefined)).toBe("readiness");
    expect(environmentDeploymentTabFromSegment("deployment")).toBe("deployment");
    expect(environmentDeploymentTabFromSegment("history")).toBeNull();
  });

  test("builds canonical Settings routes for both tabs", () => {
    expect(environmentDeploymentHref("readiness"))
      .toBe("/settings/environment-and-deployment");
    expect(environmentDeploymentHref("deployment"))
      .toBe("/settings/environment-and-deployment/deployment");
  });

  test("cycles keyboard focus and honors boundary keys", () => {
    expect(nextEnvironmentDeploymentTab("readiness", "ArrowLeft")).toBe("observers");
    expect(nextEnvironmentDeploymentTab("deployment", "ArrowRight")).toBe("observers");
    expect(nextEnvironmentDeploymentTab("deployment", "Home")).toBe("readiness");
    expect(nextEnvironmentDeploymentTab("readiness", "End")).toBe("observers");
  });
});

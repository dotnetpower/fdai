import { describe, expect, test } from "vitest";

import {
  environmentDeploymentHref,
  environmentDeploymentTabFromSegment,
  environmentDeploymentViewFromSearch,
  nextEnvironmentDeploymentTab,
} from "./environment-deployment";

describe("environment and deployment navigation", () => {
  test("uses readiness as the default and rejects unknown views", () => {
    expect(environmentDeploymentTabFromSegment(undefined)).toBe("readiness");
    expect(environmentDeploymentTabFromSegment("deployment")).toBe("deployment");
    expect(environmentDeploymentTabFromSegment("version")).toBe("version");
    expect(environmentDeploymentTabFromSegment("history")).toBeNull();
  });

  test("builds canonical Settings routes for tabs", () => {
    expect(environmentDeploymentHref("readiness"))
      .toBe("/settings/environment-and-deployment");
    expect(environmentDeploymentHref("deployment"))
      .toBe("/settings/environment-and-deployment/deployment");
    expect(environmentDeploymentHref("version"))
      .toBe("/settings/environment-and-deployment/version");
  });

  test.each(["stages", "readiness", "resources"])("restores only a valid deployment subview: %s", (value) => {
    expect(environmentDeploymentViewFromSearch(new URLSearchParams({ "deployment-view": value }))).toBe(value);
  });

  test.each(["", "unknown", "Resources", "../resources", "execute"])("defaults an invalid deployment subview safely: %s", (value) => {
    expect(environmentDeploymentViewFromSearch(new URLSearchParams({ "deployment-view": value }))).toBe("stages");
  });

  test("keeps the validated subview, locale and data mode through each parent tab", () => {
    const search = new URLSearchParams("locale=ko&deployment-view=resources");
    expect(environmentDeploymentHref("readiness", "sample", search))
      .toBe("/settings/environment-and-deployment?data=sample&locale=ko&deployment-view=resources");
    expect(environmentDeploymentHref("deployment", "sample", search))
      .toBe("/settings/environment-and-deployment/deployment?data=sample&locale=ko&deployment-view=resources");
    expect(environmentDeploymentHref("observers", "sample", search))
      .toBe("/settings/environment-and-deployment/observers?data=sample&locale=ko&deployment-view=resources");
    expect(environmentDeploymentHref("version", "sample", search))
      .toBe("/settings/environment-and-deployment/version?data=sample&locale=ko&deployment-view=resources");
  });

  test("omits default or untrusted subviews and unsupported locale overrides", () => {
    expect(environmentDeploymentHref("deployment", "live", new URLSearchParams("locale=unsupported&deployment-view=execute")))
      .toBe("/settings/environment-and-deployment/deployment");
    expect(environmentDeploymentHref("deployment", "live", new URLSearchParams("locale=en&deployment-view=stages")))
      .toBe("/settings/environment-and-deployment/deployment?locale=en");
  });

  test("cycles keyboard focus and honors boundary keys", () => {
    expect(nextEnvironmentDeploymentTab("readiness", "ArrowLeft")).toBe("version");
    expect(nextEnvironmentDeploymentTab("deployment", "ArrowRight")).toBe("observers");
    expect(nextEnvironmentDeploymentTab("observers", "ArrowRight")).toBe("version");
    expect(nextEnvironmentDeploymentTab("deployment", "Home")).toBe("readiness");
    expect(nextEnvironmentDeploymentTab("readiness", "End")).toBe("version");
  });
});

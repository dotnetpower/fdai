import { describe, expect, it } from "vitest";
import { EnrollmentsPage } from "./enrollments";

describe("enrollment detail identity", () => {
  it("remounts request data and decision inputs together when the target changes", () => {
    const alpha = EnrollmentsPage({ selectedId: "alpha" });
    const beta = EnrollmentsPage({ selectedId: "beta" });

    expect(alpha.key).toBe("alpha");
    expect(beta.key).toBe("beta");
  });
});

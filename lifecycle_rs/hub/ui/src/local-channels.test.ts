import { describe, expect, it } from "vitest";
import { localChannelConfirmation } from "./routes/local-channels";

describe("local channel approval is separate from installation approval", () => {
  it("binds the exact Release and destination without normalization", () => {
    expect(localChannelConfirmation("1.6.0", "local-reviewed")).toBe("add 1.6.0 to local-reviewed");
    expect(localChannelConfirmation("1.6.0", "local-other")).not.toBe("add 1.6.0 to local-reviewed");
    expect(localChannelConfirmation("1.5.0", "local-reviewed")).not.toBe("add 1.6.0 to local-reviewed");
  });
});

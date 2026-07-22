import { describe, expect, it } from "vitest";

import { commandDeckLayoutStyle } from "./use-command-deck-layout";

describe("commandDeckLayoutStyle", () => {
  it("uses a custom property for dock width so mobile CSS can override width", () => {
    expect(commandDeckLayoutStyle("dock", { x: 10, y: 20 }, 440)).toEqual({
      "--deck-dock-width": "440px",
    });
  });

  it("keeps floating position and leaves workspace unstyled", () => {
    expect(commandDeckLayoutStyle("floating", { x: 10, y: 20 }, 440)).toEqual({
      left: "10px",
      top: "20px",
    });
    expect(commandDeckLayoutStyle("workspace", { x: 10, y: 20 }, 440)).toBeUndefined();
  });
});

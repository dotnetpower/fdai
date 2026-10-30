import { describe, expect, test } from "vitest";
import { guidanceEdgeRoute, type RouteBox } from "./wara-guidance-routing";

const box = (x: number, y: number, width = 200, height = 100): RouteBox => ({ x, y, width, height });

describe("WARA connector routing", () => {
  test("connects side-by-side nodes with one smooth curve and no right angles", () => {
    const route = guidanceEdgeRoute(box(40, 0), box(312, 120));
    expect(route.detour).toBeNull();
    expect(route.path).toMatch(/^M 240 50 C /);
    expect(route.path).not.toMatch(/[HV] /);
  });

  test("uses the direct curve when it passes between other nodes", () => {
    const route = guidanceEdgeRoute(box(0, 150), box(600, 150), { obstacles: [box(300, 0, 200, 100), box(300, 220, 200, 100)] });
    expect(route.detour).toBeNull();
  });

  test("detours over the top only when the direct curve would cross a node", () => {
    const middle = box(300, 0, 200, 300);
    const route = guidanceEdgeRoute(box(0, 100), box(600, 100), { obstacles: [middle] });
    expect(route.detour).toBe("top");
    expect(route.path).toContain(" H ");
    const lane = Number(route.path.match(/ (-?\d+(?:\.\d+)?) H /)![1]);
    expect(lane).toBeLessThan(middle.y);
  });

  test("stacks detour lanes eight pixels apart and routes returns into the target's right side", () => {
    const options = { obstacles: [box(300, 0, 200, 300)], canvasBottom: 300 };
    const first = guidanceEdgeRoute(box(600, 100), box(0, 100), { ...options, topRank: 0 });
    const second = guidanceEdgeRoute(box(600, 100), box(0, 100), { ...options, topRank: 1 });
    expect(Number(first.path.match(/ (-?\d+(?:\.\d+)?) H /)![1]) - Number(second.path.match(/ (-?\d+(?:\.\d+)?) H /)![1])).toBe(8);
    expect(first.path).toMatch(/ 203 150$/);
    expect(first.path.startsWith("M 600 ")).toBe(true);
  });

  test("passes just beside the blocking node on the nearer side and only below when it fits", () => {
    const blocker = box(300, 120, 200, 100);
    const around = guidanceEdgeRoute(box(0, 150), box(600, 150), { obstacles: [blocker], canvasBottom: 400 });
    expect(around.detour).toBe("bottom");
    expect(Number(around.path.match(/ (-?\d+(?:\.\d+)?) H /)![1])).toBe(234);
    const confined = guidanceEdgeRoute(box(0, 150), box(600, 150), { obstacles: [blocker], canvasBottom: 240 });
    expect(confined.detour).toBe("top");
    expect(Number(confined.path.match(/ (-?\d+(?:\.\d+)?) H /)![1])).toBe(106);
  });

  test("joins stacked neighbors straight and bulges around a column when a node is between", () => {
    const direct = guidanceEdgeRoute(box(40, 0), box(40, 124));
    expect(direct.detour).toBeNull();
    expect(direct.path).toBe("M 140 100 C 140 110.5, 140 110.5, 140 121");
    const blocked = guidanceEdgeRoute(box(40, 0), box(40, 248), { obstacles: [box(40, 124)] });
    expect(blocked.detour).toBe("left");
    expect(blocked.path.startsWith("M 40 50 C ")).toBe(true);
  });

  test("keeps edge numbers beside the start of each connection", () => {
    const route = guidanceEdgeRoute(box(40, 0), box(312, 120));
    expect([route.labelX, route.labelY]).toEqual([248, 45]);
  });
});

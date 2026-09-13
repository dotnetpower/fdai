import assert from "node:assert/strict";
import { test } from "node:test";
import { sampleTour, tourShotAt, type Point3, type TourSubjects } from "../src/camera/tour";
import { placeLabels, type LabelCandidate } from "../src/scene/label-layout";
import { approachLabelOpacity, functionLabelOpacity, LABEL_INTERACTION_OPACITY } from "../src/scene/label-visibility";
import { DEFAULT_ACTIVITY_CAMERA } from "../src/camera/director";

const subjects: TourSubjects = { bus: [0, 0, -2], source: [-18, 2, 5], azure: [-31, 24, 6] };
const distance = (a: Point3, b: Point3) => Math.hypot(...a.map((value, index) => value - b[index]!));

test("Activity camera starts in Follow while overview remains an explicit control", () => {
  assert.equal(DEFAULT_ACTIVITY_CAMERA, "follow");
});

test("tour includes each source-grounded shot and closes every scenario loop", () => {
  assert.deepEqual([0, 9, 18, 27].map((time) => tourShotAt(time, 72)), ["overview", "broadcast", "function", "azure"]);
  for (const duration of [56, 60, 72]) {
    assert.deepEqual(sampleTour(duration, duration, 1.6, subjects), sampleTour(0, duration, 1.6, subjects));
    assert.deepEqual(sampleTour(duration / 2, duration, 1.6, subjects), sampleTour(0, duration, 1.6, subjects));
  }
});

test("tour transitions are continuous at every cut and at the loop boundary", () => {
  for (const time of [9, 18, 27, 36, 45, 54, 63, 72]) {
    const before = sampleTour(time - 0.00001, 72, 1.6, subjects);
    const after = sampleTour(time + 0.00001, 72, 1.6, subjects);
    assert.ok(distance(before.position, after.position) < 0.001);
    assert.ok(distance(before.target, after.target) < 0.001);
  }
});

test("pause and reverse seeks reproduce the same camera pose without frame state", () => {
  const pose = sampleTour(22, 72, 1.6, subjects);
  sampleTour(65, 72, 1.6, subjects);
  assert.deepEqual(sampleTour(22, 72, 1.6, subjects), pose);
  assert.deepEqual(sampleTour(18, 72, 1.6, subjects).target, subjects.source);
  assert.throws(() => sampleTour(0, 0, 1, subjects), /positive duration/);
  assert.throws(() => sampleTour(0, 72, Number.NaN, subjects), /positive aspect/);
});

test("label packing is deterministic, bounded and overlap-free under crowding", () => {
  const candidates: LabelCandidate[] = Array.from({ length: 17 }, (_, index) => ({
    id: `agent-${index}`, x: 150, y: 160, width: 72, height: 26, priority: index === 12 ? 1000 : 0,
  }));
  const placed = placeLabels(candidates, 320, 390);
  assert.ok(placed.some((label) => label.id === "agent-12"));
  assert.deepEqual(placed, placeLabels([...candidates].reverse(), 320, 390));
  for (const label of placed) {
    assert.ok(label.left >= 0 && label.top >= 0);
    assert.ok(label.left + label.width <= 320 && label.top + label.height <= 390);
    for (const other of placed) {
      if (label.id === other.id) continue;
      const overlap = label.left < other.left + other.width && label.left + label.width > other.left
        && label.top < other.top + other.height && label.top + label.height > other.top;
      assert.equal(overlap, false);
    }
  }
});

test("edge labels stay inside the viewport and oversized labels are not falsely placed", () => {
  const candidates: LabelCandidate[] = [
    { id: "left", x: -100, y: -50, width: 80, height: 25, priority: 10 },
    { id: "right", x: 500, y: 600, width: 80, height: 25, priority: 10 },
    { id: "too-large", x: 100, y: 100, width: 500, height: 25, priority: 0 },
  ];
  const placed = placeLabels(candidates, 320, 390);
  assert.equal(placed.length, 2);
  assert.equal(candidates[0]!.x, -100);
  assert.ok(placed.every((label) => label.left >= 4 && label.left + label.width <= 316));
});

test("function annotations reveal monotonically with proximity, not just a binary zoom threshold", () => {
  assert.equal(functionLabelOpacity(70), 0);
  assert.equal(functionLabelOpacity(44), 0);
  assert.equal(functionLabelOpacity(22), 1);
  assert.equal(functionLabelOpacity(10), 1);
  assert.equal(functionLabelOpacity(33), 0.5);
  let previous = 0;
  for (let distance = 60; distance >= 10; distance -= 0.2) {
    const opacity = functionLabelOpacity(distance);
    assert.ok(opacity >= previous && opacity <= 1);
    previous = opacity;
  }
  assert.equal(functionLabelOpacity(66, 2), functionLabelOpacity(33));
  assert.ok(functionLabelOpacity(43.999) < 0.001);
});

test("fade is gradual, frame-rate independent, and immediate only with reduced motion", () => {
  const first = approachLabelOpacity(0, 1, 1 / 60, false);
  assert.ok(first > 0 && first < LABEL_INTERACTION_OPACITY);
  const second = approachLabelOpacity(first, 1, 1 / 60, false);
  assert.ok(second > first && second < 1);
  assert.ok(approachLabelOpacity(1, 0, 1 / 60, false) > 0);
  assert.ok(Math.abs(second - approachLabelOpacity(0, 1, 1 / 30, false)) < 0.00001);
  assert.equal(approachLabelOpacity(0, 1, 0, false), 0);
  assert.equal(approachLabelOpacity(0, 0.4, 0.1, true), 0.4);
});

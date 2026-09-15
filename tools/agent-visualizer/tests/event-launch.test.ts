import assert from "node:assert/strict";
import { test } from "node:test";
import { scenarios } from "../scenarios";
import { BUS_FANOUT_DELAY, eventFlowAt } from "../src/playback/event-flow";
import { BUS_LAUNCH_LABEL, LAUNCH_LABEL_SECONDS, eventLaunchAnnotations, launchOpacity } from "../src/playback/event-launch";
import { placeLabels } from "../src/scene/label-layout";

test("departure text fades in, holds and fades out on the scenario clock", () => {
  assert.equal(launchOpacity(-1), 0);
  assert.equal(launchOpacity(0), 0);
  assert.ok(launchOpacity(0.06) > 0 && launchOpacity(0.06) < 1);
  assert.equal(launchOpacity(0.3), 1);
  assert.ok(launchOpacity(1.4) > 0 && launchOpacity(1.4) < 1);
  assert.equal(launchOpacity(LAUNCH_LABEL_SECONDS), 0);
  assert.throws(() => launchOpacity(NaN));
});

test("topic text starts at the publisher, then the actual bus fan-out origin", () => {
  const before = eventLaunchAnnotations(eventFlowAt(BUS_FANOUT_DELAY - 0.01, scenarios[0]!), false);
  const publisher = before.find((annotation) => annotation.id === "event-launch:object.event");
  assert.equal(publisher?.origin, "Huginn");
  assert.equal(publisher?.text, "object.event");
  assert.ok(!before.find((annotation) => annotation.id === BUS_LAUNCH_LABEL)?.text.includes("object.event"));
  const after = eventLaunchAnnotations(eventFlowAt(BUS_FANOUT_DELAY + 0.1, scenarios[0]!), false);
  const bus = after.find((annotation) => annotation.id === BUS_LAUNCH_LABEL);
  assert.equal(bus?.origin, "EVENT BUS");
  assert.ok(bus?.text.includes("object.event"));
});

test("annotations are bounded, rewindable, quiet after launch and disabled with reduced motion", () => {
  const project = (time: number) => eventLaunchAnnotations(eventFlowAt(time, scenarios[0]!), false);
  const initial = project(0.4);
  assert.ok(initial.length > 0);
  project(12);
  assert.deepEqual(project(0.4), initial);
  assert.deepEqual(project(2.6), []);
  assert.deepEqual(eventLaunchAnnotations(eventFlowAt(0.4, scenarios[0]!), true), []);
  for (let time = 0; time < 72; time += 0.1) {
    const annotations = project(time);
    assert.ok(annotations.length <= 6);
    assert.ok(annotations.every((annotation) => annotation.opacity > 0 && annotation.opacity <= 1));
    assert.ok((annotations.find((annotation) => annotation.id === BUS_LAUNCH_LABEL)?.text.split("\n").length ?? 0) <= 3);
  }
});

test("crowded departure labels are suppressed rather than detached from their source", () => {
  const obstacle = { id: "node", x: 200, y: 200, width: 300, height: 300, priority: 100 };
  const departure = { id: "launch", x: 200, y: 200, width: 80, height: 20, priority: -20 };
  assert.ok(placeLabels([obstacle, departure], 400, 400).some((label) => label.id === "launch"));
  assert.ok(!placeLabels([obstacle, { ...departure, nearOrigin: true }], 400, 400).some((label) => label.id === "launch"));
});

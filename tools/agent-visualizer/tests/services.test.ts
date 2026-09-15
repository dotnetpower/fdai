import assert from "node:assert/strict";
import { test } from "node:test";
import * as THREE from "three";
import { codeGraph, functionById, homeAgent, pythonFunctions, serviceFor, sourceServices } from "../src/source-graph";
import { makeNeuralGeometry } from "../src/scene/geometry";
import { serviceLayouts, servicePortPositions } from "../src/scene/service-layout";
import { ExternalServices } from "../src/scene/external-services";
import { DEMO_STREAM_HZ, servicePacketsAt } from "../src/playback/service-traffic";

test("enriched API groups contain real functions without assigning adapter ownership to agents", () => {
  assert.ok(pythonFunctions.length > 1000);
  for (const service of sourceServices) {
    const members = pythonFunctions.filter((fn) => serviceFor(fn) === service.id);
    assert.ok(members.length > 0);
    assert.ok(members.every((fn) => homeAgent(fn) === null));
    for (const port of service.ports) {
      assert.ok(functionById.has(port.function_id));
      assert.equal(serviceFor(functionById.get(port.function_id)!), service.id);
      assert.ok(servicePortPositions[port.id]);
    }
  }
  assert.equal(codeGraph.agents.length, 15);
});

test("OpenAI is to the right and channels have their own lower-left function region", () => {
  const graph = makeNeuralGeometry();
  for (const id of ["azure-openai", "channels"] as const) {
    const points = pythonFunctions.filter((fn) => serviceFor(fn) === id).map((fn) => graph.functionPositions.get(fn.id)!);
    const average = points.reduce((sum, point) => sum.add(point), new THREE.Vector3()).divideScalar(points.length);
    assert.ok(average.distanceTo(serviceLayouts[id].center) < 1.5);
  }
  assert.ok(servicePortPositions.openai!.x > 0);
  assert.ok(servicePortPositions.console!.x < 0);
  assert.ok(serviceLayouts.channels.center.y < serviceLayouts["azure-resource-graph"].center.y);
  assert.equal(graph.points.length, pythonFunctions.length + 15);
  graph.lines.dispose();
});

test("fast chunks and message pulses are distinct, bounded and deterministic", () => {
  assert.equal(DEMO_STREAM_HZ, 24);
  const chunks = servicePacketsAt(1.5, "stream");
  assert.ok(chunks.length >= 10 && chunks.length <= 12);
  assert.ok(chunks.every((packet) => packet.direction === "outbound" && packet.progress >= 0 && packet.progress <= 1));
  assert.ok(servicePacketsAt(1.5, "model").every((packet) => packet.direction === "inbound"));
  assert.equal(servicePacketsAt(0.2, "message").length, 1);
  assert.equal(servicePacketsAt(1.5, "message").length, 0);
  assert.deepEqual(servicePacketsAt(1.5, "stream"), chunks);
  assert.throws(() => servicePacketsAt(NaN, "model"));
});

test("service traffic stays within its GPU budget and stops under reduced motion", () => {
  const graph = makeNeuralGeometry();
  const services = new ExternalServices(graph.functionPositions, 1);
  const frame = services.update(1.5, false);
  assert.ok(frame.count > 0 && frame.count < 512);
  assert.ok(frame.channelStreamCount >= 20);
  assert.deepEqual(services.update(1.5, false), frame);
  assert.deepEqual(services.update(3, true), { count: 0, channelStreamCount: 0 });
  services.group.traverse((object) => {
    if (object instanceof THREE.Line || object instanceof THREE.Points) {
      object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach((material) => material.dispose());
    }
  });
  graph.lines.dispose();
});

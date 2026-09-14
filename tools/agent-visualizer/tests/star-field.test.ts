import assert from "node:assert/strict";
import { test } from "node:test";
import { makeStars, StarField, STAR_COUNT } from "../src/scene/star-field";
import { createPointOcclusionMaterial, makeNeuralGeometry } from "../src/scene/geometry";
import { pythonFunctions } from "../src/source-graph";

test("decorative stars are bounded, deterministic, slow, and unrelated to graph identities", () => {
  const stars = makeStars();
  assert.equal(stars.length, STAR_COUNT);
  assert.deepEqual(stars, makeStars());
  assert.ok(new Set(stars.map((star) => star.phase)).size > 300);
  for (const star of stars) {
    assert.ok(star.x >= -1 && star.x <= 1 && star.y >= -1 && star.y <= 1);
    assert.ok(star.size >= 0.9 && star.size <= 2.4);
    assert.ok(star.frequency >= 0.12 && star.frequency <= 0.3);
    assert.ok(star.brightness >= 0 && star.brightness <= 0.75);
    assert.equal("functionId" in star, false);
  }
  const graph = makeNeuralGeometry();
  assert.equal(graph.points.length, pythonFunctions.length + 15);
  graph.lines.dispose();
});

test("stars render after node depth masks, freeze at repeated time, and respect reduced motion and visibility", () => {
  const field = new StarField(1);
  assert.equal(field.object.geometry.getAttribute("position").count, STAR_COUNT);
  assert.equal(field.object.renderOrder, 100);
  assert.equal(field.object.material.depthTest, true);
  assert.equal(field.object.material.depthWrite, false);
  const occlusion = createPointOcclusionMaterial(1);
  assert.equal(occlusion.colorWrite, false);
  assert.equal(occlusion.depthTest, true);
  assert.equal(occlusion.depthWrite, true);
  occlusion.dispose();
  field.update(3, true, false);
  assert.equal(field.object.material.uniforms.time!.value, 3);
  field.update(3, true, false);
  assert.equal(field.object.material.uniforms.time!.value, 3);
  field.update(10, true, true);
  assert.equal(field.object.material.uniforms.time!.value, 0);
  field.update(11, false, false);
  assert.equal(field.object.visible, false);
  field.object.geometry.dispose();
  field.object.material.dispose();
});

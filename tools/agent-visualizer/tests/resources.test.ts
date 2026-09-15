import assert from "node:assert/strict";
import { test } from "node:test";
import * as THREE from "three";
import { SceneResources, disposeSceneObjects } from "../src/scene/resources";

test("partial initialization unwinds every acquired resource once even if one cleanup fails", () => {
  const resources = new SceneResources();
  const order: number[] = [];
  resources.add(() => { order.push(1); });
  resources.add(() => { order.push(2); throw new Error("cleanup failure"); });
  resources.add(() => { order.push(3); });
  assert.throws(() => resources.dispose(), AggregateError);
  assert.deepEqual(order, [3, 2, 1]);
  resources.dispose();
  assert.deepEqual(order, [3, 2, 1]);
});

test("shared render geometry and material are disposed once and detached from the scene", () => {
  const root = new THREE.Group();
  const geometry = new THREE.BoxGeometry();
  const material = new THREE.MeshBasicMaterial();
  let geometryDisposals = 0;
  let materialDisposals = 0;
  geometry.addEventListener("dispose", () => { geometryDisposals++; });
  material.addEventListener("dispose", () => { materialDisposals++; });
  root.add(new THREE.Mesh(geometry, material), new THREE.Mesh(geometry, material));
  disposeSceneObjects(root);
  assert.equal(geometryDisposals, 1);
  assert.equal(materialDisposals, 1);
  assert.equal(root.children.length, 0);
  disposeSceneObjects(root);
  assert.equal(geometryDisposals, 1);
});

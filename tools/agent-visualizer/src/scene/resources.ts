import * as THREE from "three";

/** Reverse acquisition order on success or partial construction failure, without hiding cleanup errors. */
export class SceneResources {
  private readonly cleanups: Array<() => void> = [];

  add(cleanup: () => void) { this.cleanups.push(cleanup); }

  dispose() {
    const errors: unknown[] = [];
    for (const cleanup of this.cleanups.splice(0).reverse()) {
      try { cleanup(); } catch (error) { errors.push(error); }
    }
    if (errors.length) throw new AggregateError(errors, "Scene resource cleanup failed.");
  }
}

/** Release shared geometry/material identities once and drop references to the retired object tree. */
export function disposeSceneObjects(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  root.traverse((object) => {
    if (object instanceof THREE.InstancedMesh) object.dispose();
    if (object instanceof THREE.Mesh || object instanceof THREE.Points || object instanceof THREE.Line) {
      geometries.add(object.geometry);
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) materials.add(material);
    }
  });
  geometries.forEach((geometry) => geometry.dispose());
  materials.forEach((material) => material.dispose());
  root.clear();
}

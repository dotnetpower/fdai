import * as THREE from "three";
import { connectionCurve } from "../scene/geometry";

/** Self-typed relations need a visible loop; distinct predicates get stable separated curvature. */
export function mapCurve(start: THREE.Vector3, end: THREE.Vector3, predicate: string): THREE.Curve<THREE.Vector3> {
  let hash = 0;
  for (const character of predicate) hash = (Math.imul(hash, 31) + character.charCodeAt(0)) | 0;
  if (start.distanceToSquared(end) < 0.001) {
    const angle = Math.abs(hash % 12) / 12 * Math.PI * 2;
    const offset = new THREE.Vector3(Math.cos(angle), Math.sin(angle), 0.3);
    const side = new THREE.Vector3(-offset.y, offset.x, 0);
    return new THREE.CatmullRomCurve3([
      start.clone(),
      start.clone().addScaledVector(offset, 2).addScaledVector(side, 1.4),
      start.clone().addScaledVector(offset, 3.5),
      start.clone().addScaledVector(offset, 2).addScaledVector(side, -1.4),
      start.clone(),
    ]);
  }
  return connectionCurve(start, end, ((Math.abs(hash) % 7) - 3) * 0.045);
}

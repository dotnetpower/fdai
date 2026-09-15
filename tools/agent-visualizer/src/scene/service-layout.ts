import * as THREE from "three";

export type ServiceId = "azure-resource-graph" | "azure-openai" | "channels";

export const serviceLayouts: Record<ServiceId, { center: THREE.Vector3; color: string }> = {
  "azure-resource-graph": { center: new THREE.Vector3(-26, 21, -4), color: "#70b9ff" },
  "azure-openai": { center: new THREE.Vector3(27, 20, -4), color: "#ac9cda" },
  channels: { center: new THREE.Vector3(-29, -8, -5), color: "#7ebfc1" },
};

export const servicePortPositions: Readonly<Record<string, THREE.Vector3>> = {
  "resource-graph": new THREE.Vector3(-31, 24, 6),
  openai: new THREE.Vector3(33, 21, 6),
  console: new THREE.Vector3(-36, -1, 8),
  teams: new THREE.Vector3(-37, -9, 8),
  slack: new THREE.Vector3(-32, -16, 8),
};

/** The same small wireframe marker is used for every external API/channel surface. */
export function serviceMarker(position: THREE.Vector3, color = "#85a9c5") {
  const box = new THREE.BoxGeometry(2.8, 1.7, 0.5);
  const marker = new THREE.LineSegments(new THREE.EdgesGeometry(box),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.8 }));
  box.dispose();
  marker.position.copy(position);
  return marker;
}

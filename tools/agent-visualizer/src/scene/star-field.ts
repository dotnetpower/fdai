import * as THREE from "three";
import { seededRandom } from "./geometry";

export const STAR_COUNT = 360;

/** Decorative sky samples, not function nodes, evidence, resource counts, or activity. */
export function makeStars() {
  const random = seededRandom(7319);
  return Array.from({ length: STAR_COUNT }, () => {
    const x = random() * 2 - 1;
    const y = random() * 2 - 1;
    const peripheral = Math.min(1, Math.hypot(x, y) / 0.8);
    return {
      x, y,
      size: 0.9 + random() * 1.5,
      phase: random() * Math.PI * 2,
      frequency: 0.12 + random() * 0.18,
      brightness: (0.3 + random() * 0.45) * (0.45 + peripheral * 0.55),
    };
  });
}

/** One background-only GPU draw call. It is intentionally excluded from graph picking. */
export class StarField {
  readonly object: THREE.Points<THREE.BufferGeometry, THREE.ShaderMaterial>;

  constructor(pixelRatio: number) {
    const samples = makeStars();
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(samples.flatMap((star) => [star.x, star.y, 0]), 3));
    geometry.setAttribute("size", new THREE.Float32BufferAttribute(samples.map((star) => star.size), 1));
    geometry.setAttribute("phase", new THREE.Float32BufferAttribute(samples.map((star) => star.phase), 1));
    geometry.setAttribute("frequency", new THREE.Float32BufferAttribute(samples.map((star) => star.frequency), 1));
    geometry.setAttribute("brightness", new THREE.Float32BufferAttribute(samples.map((star) => star.brightness), 1));
    const material = new THREE.ShaderMaterial({
      uniforms: { time: { value: 0 }, pixelRatio: { value: pixelRatio } },
      vertexShader: `
        attribute float size;
        attribute float phase;
        attribute float frequency;
        attribute float brightness;
        uniform float time;
        uniform float pixelRatio;
        varying float intensity;
        void main() {
          float shimmer = 0.65 + 0.35 * sin(time * frequency * 6.2831853 + phase);
          intensity = brightness * shimmer;
          gl_Position = vec4(position.xy, 0.999, 1.0);
          gl_PointSize = size * pixelRatio;
        }
      `,
      fragmentShader: `
        varying float intensity;
        void main() {
          float radius = length(gl_PointCoord - vec2(0.5)) * 2.0;
          float falloff = 1.0 - smoothstep(0.1, 1.0, radius);
          gl_FragColor = vec4(vec3(0.58, 0.69, 0.78), intensity * falloff);
        }
      `,
      transparent: true,
      depthTest: false,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      toneMapped: false,
    });
    this.object = new THREE.Points(geometry, material);
    this.object.name = "decorative-star-backdrop";
    this.object.renderOrder = -100;
    this.object.frustumCulled = false;
  }

  update(time: number, enabled: boolean, reduced: boolean) {
    this.object.visible = enabled;
    this.object.material.uniforms.time!.value = reduced ? 0 : time;
  }
}

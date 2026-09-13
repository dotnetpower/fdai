import * as THREE from "three";

/** Per-node size/opacity preserves a readable declaration layer over thousands of real instances. */
export function mapPointMaterial(pixelRatio: number) {
  return new THREE.ShaderMaterial({
    uniforms: { pixelRatio: { value: pixelRatio } },
    vertexShader: `
      attribute float size;
      attribute float alpha;
      attribute vec3 color;
      uniform float pixelRatio;
      varying vec3 tint;
      varying float opacity;
      void main() {
        vec4 view = modelViewMatrix * vec4(position, 1.0);
        tint = color;
        opacity = alpha;
        gl_PointSize = clamp(size * pixelRatio * 240.0 / -view.z, 1.0, 28.0);
        gl_Position = projectionMatrix * view;
      }
    `,
    fragmentShader: `
      varying vec3 tint;
      varying float opacity;
      void main() {
        float radius = length(gl_PointCoord - vec2(0.5)) * 2.0;
        if (radius > 1.0) discard;
        float core = exp(-radius * radius * 24.0);
        float halo = exp(-radius * radius * 4.0);
        gl_FragColor = vec4(tint + vec3(core * 0.3), opacity * halo);
      }
    `,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
}

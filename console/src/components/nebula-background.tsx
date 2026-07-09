import { useEffect, useRef } from "preact/hooks";

/**
 * Procedural, image-free WebGL nebula - a Preact port of the landing
 * site's `NebulaBackground.astro`. A single fragment shader draws
 * domain-warped FBM clouds tinted with real-nebula emission colours
 * (H-alpha red, O-III teal, gold dust, magenta, Azure/cyan) plus three
 * layers of softly twinkling stars, with an Orion-style core bloom.
 *
 * Decorative + progressive:
 *   - No WebGL              -> canvas stays transparent; the caller's CSS
 *                             background shows through (graceful).
 *   - prefers-reduced-motion -> one static frame, no rAF.
 *   - Unmount               -> the render loop + listeners are torn down.
 *
 * The canvas fills its positioned parent (inset: 0); the parent must
 * establish a positioning context. There is no scroll coupling here (the
 * sign-in screen does not scroll), so `u_scroll` is always 0.
 */
interface NebulaBackgroundProps {
  /** Overall brightness multiplier for the nebula clouds (0.5 - 1.5). */
  readonly intensity?: number;
  /** Drift speed multiplier (0 = still, 1 = default slow drift). */
  readonly speed?: number;
  /** Extra class names for the canvas. */
  readonly class?: string;
}

const VERT = `
  attribute vec2 a;
  void main() { gl_Position = vec4(a, 0.0, 1.0); }
`;

const FRAG = `
  precision highp float;
  uniform vec2  u_res;
  uniform float u_time;
  uniform float u_intensity;
  uniform float u_scroll;

  float hash(vec2 p){
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
  }
  vec2 hash2(vec2 p){
    return fract(sin(vec2(dot(p, vec2(127.1, 311.7)),
                          dot(p, vec2(269.5, 183.3)))) * 43758.5453);
  }
  float noise(vec2 p){
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
  }
  float fbm(vec2 p){
    float v = 0.0;
    float amp = 0.5;
    for (int i = 0; i < 6; i++){
      v += amp * noise(p);
      p *= 2.02;
      amp *= 0.5;
    }
    return v;
  }

  vec3 starLayer(vec2 uv, float scale, float density, float seed, float twMul){
    vec2 g  = uv * scale + seed;
    vec2 id = floor(g);
    vec2 f  = fract(g);
    vec3 acc = vec3(0.0);
    for (int y = -1; y <= 1; y++){
      for (int x = -1; x <= 1; x++){
        vec2 o   = vec2(float(x), float(y));
        vec2 cid = id + o;
        float present = hash(cid + seed * 3.7);
        if (present > 1.0 - density){
          vec2 pos   = hash2(cid + 1.3);
          float b    = hash(cid + 2.1);
          float ph   = hash(cid + 3.4) * 6.2831;
          float sp   = (0.08 + hash(cid + 4.7) * 0.64) * twMul;
          float temp = hash(cid + 5.9);
          float tw   = 0.55 + 0.45 * sin(u_time * sp + ph);
          vec2 d     = f - (o + pos);
          float dist = length(d);
          float core = smoothstep(0.06 * (0.5 + b), 0.0, dist);
          float halo = smoothstep(0.22 * (0.4 + b), 0.0, dist) * 0.25;
          vec3 warm  = vec3(1.0, 0.82, 0.62);
          vec3 cool  = vec3(0.70, 0.84, 1.0);
          vec3 sc    = mix(warm, cool, temp);
          acc += (core + halo) * tw * (0.35 + b) * sc;
        }
      }
    }
    return acc;
  }

  void main(){
    vec2 uv = gl_FragCoord.xy / u_res.xy;
    float scrollOff = u_scroll / u_res.y;
    vec2 p  = (gl_FragCoord.xy - 0.5 * u_res.xy) / u_res.y;
    p.y -= scrollOff;
    float heroFade  = mix(0.22, 1.0, 1.0 - smoothstep(0.25, 1.05, scrollOff));
    float fieldCalm = mix(1.0, 0.80, smoothstep(0.35, 1.20, scrollOff));
    float t = u_time * 0.006;

    vec2 q = vec2(fbm(p * 2.6 + t), fbm(p * 2.6 - t + 5.2));
    vec2 r = vec2(fbm(p * 2.6 + q * 1.8 + t * 1.3),
                  fbm(p * 2.6 + q * 1.8 - t * 0.7));
    float f = fbm(p * 2.6 + r * 2.0);

    float mHa   = fbm(p * 2.2 + r + vec2( 3.1,  t));
    float mOiii = fbm(p * 2.5 + r + vec2(-4.0, -t * 0.8));
    float mDust = fbm(p * 1.8 + q + vec2( 8.0,  t * 0.5));
    float mMag  = fbm(p * 2.7 + r + vec2(-1.5,  t * 1.1));
    float mBlue = fbm(p * 2.3 + q + vec2( 5.5, -t));

    vec2  coreCentre = vec2(0.50, 0.78);
    float coreAspect = u_res.x / u_res.y;
    vec2  coreOff    = (uv - coreCentre) * vec2(coreAspect * 0.55, 1.0);
    float coreDist   = length(coreOff);
    float coreWisp   = fbm(p * 1.4 + vec2(t * 0.4, -t * 0.3));
    float coreShape  = coreDist * (0.72 + coreWisp * 0.35);
    float coreBloom  = smoothstep(0.55, 0.0, coreShape);
    float coreHalo   = smoothstep(0.95, 0.10, coreShape)
                     * smoothstep(0.30, 0.85, f);

    vec2  loCentre = vec2(0.16, 0.14);
    vec2  loOff    = (uv - loCentre) * vec2(coreAspect * 0.60, 1.0);
    float loWisp   = fbm(p * 1.6 + vec2(-t * 0.30, t * 0.45));
    float loShape  = length(loOff) * (0.80 + loWisp * 0.40);
    float loGlow   = smoothstep(0.85, 0.05, loShape)
                   * smoothstep(0.25, 0.80, f);

    vec3 space   = vec3(0.010, 0.013, 0.030);
    vec3 hAlpha  = vec3(0.50, 0.20, 0.16);
    vec3 oIII    = vec3(0.06, 0.52, 0.48);
    vec3 dust    = vec3(0.60, 0.45, 0.16);
    vec3 amber   = vec3(0.72, 0.52, 0.18);
    vec3 azure   = vec3(0.00, 0.34, 0.60);
    vec3 cyan    = vec3(0.26, 0.68, 0.82);
    vec3 coreCol = vec3(0.66, 0.48, 0.18);
    vec3 reflectCol = vec3(0.38, 0.58, 1.00);
    vec3 loCol   = vec3(0.82, 0.22, 0.34);

    vec3 col = space;
    col = mix(col, azure,  smoothstep(0.48, 0.92, mBlue) * 0.42);
    col = mix(col, dust,   smoothstep(0.50, 0.92, mDust) * 0.55);
    col = mix(col, amber,  smoothstep(0.60, 0.95, mMag)  * 0.40);
    col = mix(col, oIII,   smoothstep(0.60, 0.96, mOiii) * 0.32);
    col = mix(col, hAlpha, smoothstep(0.66, 0.97, mHa)   * 0.22);
    col = mix(col, cyan,   pow(smoothstep(0.74, 1.0, f), 2.0) * 0.28);

    col = mix(col, reflectCol, coreHalo * 0.32 * heroFade);
    col += dust * coreHalo * smoothstep(0.30, 0.85, mDust) * 0.45 * heroFade;
    col += coreCol * coreBloom * (0.40 + coreWisp * 0.20) * heroFade;
    col = mix(col, loCol, loGlow * 0.45 * heroFade);

    col *= 0.42 + 0.70 * f;
    col *= u_intensity;

    vec2 suv = vec2(uv.x, uv.y - scrollOff);
    col += starLayer(suv * vec2(u_res.x / u_res.y, 1.0), 120.0, 0.10, 11.0, 6.0);
    col += starLayer(suv * vec2(u_res.x / u_res.y, 1.0),  70.0, 0.07, 47.0, 1.0);
    col += starLayer(suv * vec2(u_res.x / u_res.y, 1.0),  38.0, 0.05, 91.0, 0.7) * 1.4;
    vec3 coreStars = starLayer(suv * vec2(u_res.x / u_res.y, 1.0),
                               22.0, 0.14, 137.0, 0.35);
    col += coreStars * smoothstep(0.75, 0.05, coreShape) * 1.6 * heroFade;

    float vig = smoothstep(1.25, 0.35, length(uv - 0.5) * 1.4);
    col *= mix(0.55, 1.0, vig);
    col *= fieldCalm;

    col = col / (col + 0.55);
    col = pow(col, vec3(0.85));

    gl_FragColor = vec4(col, 1.0);
  }
`;

export function NebulaBackground({
  intensity = 1,
  speed = 1,
  class: className = "",
}: NebulaBackgroundProps) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl", { antialias: false, alpha: true });
    if (!gl) return; // graceful: leave the canvas transparent

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;

    const compile = (type: number, src: string): WebGLShader => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        console.warn("nebula shader:", gl.getShaderInfoLog(s));
      }
      return s;
    };

    const prog = gl.createProgram()!;
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]),
      gl.STATIC_DRAW
    );
    const loc = gl.getAttribLocation(prog, "a");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(prog, "u_res");
    const uTime = gl.getUniformLocation(prog, "u_time");
    const uIntensity = gl.getUniformLocation(prog, "u_intensity");
    const uScroll = gl.getUniformLocation(prog, "u_scroll");

    let dpr = Math.min(window.devicePixelRatio || 1, 2);
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas.clientWidth || window.innerWidth;
      const h = canvas.clientHeight || window.innerHeight;
      canvas.width = Math.max(1, Math.floor(w * dpr));
      canvas.height = Math.max(1, Math.floor(h * dpr));
      gl.viewport(0, 0, canvas.width, canvas.height);
    };
    window.addEventListener("resize", resize);
    resize();

    const draw = (timeSeconds: number) => {
      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform1f(uTime, timeSeconds);
      gl.uniform1f(uIntensity, intensity);
      gl.uniform1f(uScroll, 0);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };

    if (reduceMotion) {
      draw(8.0);
      return () => {
        window.removeEventListener("resize", resize);
      };
    }

    const start = performance.now();
    let rafId = 0;
    const frame = (now: number) => {
      draw(((now - start) / 1000) * speed);
      rafId = requestAnimationFrame(frame);
    };
    rafId = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", resize);
    };
  }, [intensity, speed]);

  return (
    <canvas ref={ref} class={`nebula-bg ${className}`.trim()} aria-hidden="true" />
  );
}

"use client";
import { useEffect, useRef } from "react";
import {
  BoxGeometry,
  Mesh,
  OrthographicCamera,
  PerspectiveCamera,
  PlaneGeometry,
  Scene,
  ShaderMaterial,
  Vector2,
  Vector3,
  WebGLRenderer,
  WebGLRenderTarget,
} from "three";

/**
 * The hero: a dependency package (three crates) rendered as halftone dots.
 *
 * Pass 1 draws the crates into a small render target, one or two texels per dot cell, with
 * light in red, the scanning line in green and the "Breaks you" mark in blue. Pass 2 draws
 * one dot per cell, sized by that light and coloured by the other two channels.
 */

type Props = {
  /** Render one frame and stop (prefers-reduced-motion). */
  still: boolean;
  /** The stage element: receives --mx/--my/--mo for the leader line from the mark. */
  stage: HTMLElement;
  onReady: () => void;
  onFail: () => void;
};

const INK = new Vector3(0.93, 0.92, 0.89);
const SCAN = new Vector3(0.42, 0.89, 1.0);
const BREAK = new Vector3(1.0, 0.29, 0.24);
const LIGHT = new Vector3(-0.45, 1.0, 0.5).normalize();
const SCAN_NORMAL = new Vector3(0.22, 1.0, 0.12).normalize();
const PERIOD = 10;
const SWEEP = 4.2;
const SCAN_TOP = 1.75;
const SCAN_BOTTOM = -0.35;
/** The mark on the big crate's +x face, in that crate's unit-box coordinates. */
const MARK_LOCAL = new Vector3(0.5, 0.06, -0.08);

const sceneVertex = /* glsl */ `
  varying vec3 vLocal;
  varying vec3 vNormalL;
  varying vec3 vWorld;
  varying vec3 vNormalW;
  void main() {
    vLocal = position;
    vNormalL = normal;
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    vNormalW = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

const crateFragment = /* glsl */ `
  uniform vec3 uSize;
  uniform vec3 uLight;
  uniform vec3 uScanN;
  uniform float uScan;
  uniform float uMark;
  uniform vec2 uMarkAt;
  varying vec3 vLocal;
  varying vec3 vNormalL;
  varying vec3 vWorld;
  varying vec3 vNormalW;
  void main() {
    vec3 p = vLocal * uSize;
    vec3 e = uSize * 0.5 - abs(p);
    float m1 = min(e.x, min(e.y, e.z));
    float m3 = max(e.x, max(e.y, e.z));
    float m2 = e.x + e.y + e.z - m1 - m3;
    float edge = 1.0 - smoothstep(0.016, 0.05, m2);
    vec3 n = normalize(vNormalW);
    float lum = 0.07 + 0.82 * max(dot(n, uLight), 0.0);
    // The lid: a groove around the sides just under the top.
    float side = 1.0 - abs(vNormalL.y);
    float seam = side * (1.0 - smoothstep(0.012, 0.026, abs(p.y - (uSize.y * 0.5 - 0.17))));
    lum = lum * (1.0 - 0.75 * seam) + edge * 0.5;
    float d = dot(vWorld, uScanN) - uScan;
    // A bright line, and a short fading trail on the part it has just passed.
    float scan = exp(-d * d / 0.0035) + 0.22 * step(0.0, d) * exp(-d / 0.12);
    float face = step(0.5, vNormalL.x);
    float mark = face * uMark * (1.0 - smoothstep(0.1, 0.118, length(vec2(p.z, p.y) - uMarkAt)));
    gl_FragColor = vec4(clamp(lum, 0.0, 1.0), scan, mark, 1.0);
  }
`;

const floorFragment = /* glsl */ `
  uniform vec3 uScanN;
  uniform float uScan;
  uniform vec3 uShadow;
  varying vec3 vWorld;
  float box(vec2 p, vec2 b) {
    vec2 d = abs(p) - b;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
  }
  void main() {
    vec2 q = vWorld.xz;
    float fall = exp(-dot(q - vec2(0.0, 0.25), q - vec2(0.0, 0.25)) / 1.1);
    // A soft shadow from the crates, cast away from the light.
    float s = box(q - uShadow.xy, vec2(uShadow.z));
    float shade = 1.0 - 0.9 * (1.0 - smoothstep(-0.25, 0.55, s));
    float lum = 0.13 * fall * shade;
    float d = dot(vWorld, uScanN) - uScan;
    float scan = exp(-d * d / 0.0035) * fall;
    gl_FragColor = vec4(lum, scan, 0.0, 1.0);
  }
`;

const dotVertex = /* glsl */ `
  void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

const dotFragment = /* glsl */ `
  uniform sampler2D tScene;
  uniform vec2 uRes;
  uniform float uCell;
  uniform vec3 uInk;
  uniform vec3 uScanC;
  uniform vec3 uBreak;
  void main() {
    vec2 cell = floor(gl_FragCoord.xy / uCell);
    vec2 c = (cell + 0.5) * uCell;
    vec4 s = texture2D(tScene, c / uRes);
    float scan = clamp(s.g * 1.3, 0.0, 1.0);
    float level = clamp(s.r + scan * 0.5, 0.0, 1.0);
    level = max(level, s.b * 0.92);
    // Fade towards the stage edge so nothing is ever cut by the canvas border.
    vec2 uv = c / uRes - 0.5;
    level *= 1.0 - smoothstep(0.36, 0.5, length(uv));
    float r = 0.5 * uCell * pow(level, 0.72) * 0.96;
    float a = (1.0 - smoothstep(r - 0.7, r + 0.7, length(gl_FragCoord.xy - c)));
    a *= step(0.03, level) * s.a;
    vec3 col = mix(uInk, uScanC, scan);
    col = mix(col, uBreak, clamp(s.b * 1.6, 0.0, 1.0));
    gl_FragColor = vec4(col * a, a);
  }
`;

export default function HeroScene({ still, stage, onReady, onFail }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const callbacks = useRef({ onReady, onFail });
  useEffect(() => {
    callbacks.current = { onReady, onFail };
  }, [onReady, onFail]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({
        canvas,
        alpha: true,
        antialias: false,
        powerPreference: "low-power",
      });
    } catch {
      callbacks.current.onFail();
      return;
    }
    renderer.setClearColor(0x000000, 0);
    renderer.autoClear = false;

    const camera = new PerspectiveCamera(24, 1, 0.1, 40);
    const scene = new Scene();
    const box = new BoxGeometry(1, 1, 1);
    const shared = { uLight: { value: LIGHT }, uScanN: { value: SCAN_NORMAL } };
    const scan = { value: SCAN_TOP };
    const markLevel = { value: 0 };

    const crate = (size: Vector3, withMark = false) => {
      const material = new ShaderMaterial({
        vertexShader: sceneVertex,
        fragmentShader: crateFragment,
        uniforms: {
          ...shared,
          uScan: scan,
          uSize: { value: size },
          uMark: withMark ? markLevel : { value: 0 },
          uMarkAt: {
            value: new Vector2(MARK_LOCAL.z * size.z, MARK_LOCAL.y * size.y),
          },
        },
      });
      const mesh = new Mesh(box, material);
      mesh.scale.copy(size);
      return mesh;
    };
    const main = crate(new Vector3(1.05, 0.9, 1.05), true);
    main.position.set(0, 0.45, 0);
    const top = crate(new Vector3(0.62, 0.5, 0.62));
    top.position.set(-0.1, 1.15, 0.05);
    top.rotation.y = 0.32;
    const side = crate(new Vector3(0.55, 0.48, 0.55));
    side.position.set(-0.55, 0.24, 1.0);
    side.rotation.y = -0.22;
    const group = [main, top, side];
    scene.add(...group);

    const floorGeometry = new PlaneGeometry(9, 9);
    const floorMaterial = new ShaderMaterial({
      vertexShader: sceneVertex,
      fragmentShader: floorFragment,
      uniforms: {
        uScanN: shared.uScanN,
        uScan: scan,
        uShadow: { value: new Vector3(0.32, -0.1, 0.42) },
      },
    });
    const floor = new Mesh(floorGeometry, floorMaterial);
    floor.rotation.x = -Math.PI / 2;
    scene.add(floor);

    const target = new WebGLRenderTarget(2, 2);
    const dotMaterial = new ShaderMaterial({
      vertexShader: dotVertex,
      fragmentShader: dotFragment,
      depthTest: false,
      depthWrite: false,
      uniforms: {
        tScene: { value: target.texture },
        uRes: { value: new Vector2(1, 1) },
        uCell: { value: 6 },
        uInk: { value: INK },
        uScanC: { value: SCAN },
        uBreak: { value: BREAK },
      },
    });
    const quadGeometry = new PlaneGeometry(2, 2);
    const quad = new Scene();
    quad.add(new Mesh(quadGeometry, dotMaterial));
    const flat = new OrthographicCamera(-1, 1, 1, -1, 0, 1);

    // Layout: measured on resize only.
    let width = 1,
      height = 1,
      shift = 0,
      card = { left: 0, top: 0, right: 0, bottom: 0, ok: false };
    // The canvas fills the stage's art box; on small screens the cards sit below that box.
    const art = canvas.parentElement || stage;
    const measure = () => {
      const rect = art.getBoundingClientRect();
      width = Math.max(1, Math.round(rect.width));
      height = Math.max(1, Math.round(rect.height));
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      renderer.setPixelRatio(ratio);
      renderer.setSize(width, height, false);
      const cell = (width < 520 ? 5 : 6) * ratio;
      const buffer = renderer.getDrawingBufferSize(new Vector2());
      dotMaterial.uniforms.uRes.value.copy(buffer);
      dotMaterial.uniforms.uCell.value = cell;
      target.setSize(
        Math.ceil(buffer.x / cell) * 2,
        Math.ceil(buffer.y / cell) * 2,
      );
      camera.aspect = width / height;
      shift = width > 640 && width / height > 1.05 ? 0.62 : 0;
      camera.updateProjectionMatrix();
      const comment = stage.querySelector<HTMLElement>("[data-leader-anchor]");
      const area = comment?.getBoundingClientRect();
      card =
        comment &&
        area &&
        area.width > 0 &&
        getComputedStyle(comment).position === "absolute"
          ? {
              left: area.left - rect.left,
              top: area.top - rect.top,
              right: area.right - rect.left,
              bottom: area.bottom - rect.top,
              ok: true,
            }
          : { left: 0, top: 0, right: 0, bottom: 0, ok: false };
    };

    const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
    const onPointer = (event: PointerEvent) => {
      pointer.tx = (event.clientX / window.innerWidth) * 2 - 1;
      pointer.ty = (event.clientY / window.innerHeight) * 2 - 1;
    };
    const fine = window.matchMedia("(pointer: fine)").matches;
    if (!still && fine)
      window.addEventListener("pointermove", onPointer, { passive: true });

    const mark = new Vector3();
    const facing = new Vector3();
    const toCamera = new Vector3();
    const markScan = () => {
      main.updateMatrixWorld();
      return main.localToWorld(mark.copy(MARK_LOCAL)).dot(SCAN_NORMAL);
    };

    let clock = 0.6,
      cycle = -1,
      hit = Infinity;
    const update = (dt: number) => {
      clock += dt;
      const t = clock % PERIOD;
      if (Math.floor(clock / PERIOD) !== cycle) {
        cycle = Math.floor(clock / PERIOD);
        hit = Infinity;
      }
      pointer.x += (pointer.tx - pointer.x) * Math.min(1, dt * 2.5);
      pointer.y += (pointer.ty - pointer.y) * Math.min(1, dt * 2.5);
      const yaw = (still ? 0 : 0.11 * Math.sin(clock * 0.21)) + pointer.x * 0.1;
      const angle = 0.78 + yaw;
      // Closer on small, square stages, where the cards sit below instead of beside.
      const radius = shift ? 8 : 6.9;
      camera.position.set(
        Math.sin(angle) * radius,
        3.05 - pointer.y * 0.25,
        Math.cos(angle) * radius,
      );
      // On wide stages the object sits left of centre, leaving the right for the comment card.
      camera.lookAt(0.05 + shift * 0.7, 0.66, 0.3 - shift * 0.7);
      if (still) {
        // One composed frame: the line just past the mark, the mark showing.
        scan.value = markScan() - 0.22;
        markLevel.value = 1;
        return;
      }
      const k = Math.min(t / SWEEP, 1);
      const eased = 1 - Math.pow(1 - k, 1.6);
      scan.value = t < SWEEP ? SCAN_TOP + (SCAN_BOTTOM - SCAN_TOP) * eased : -9;
      const at = markScan();
      if (scan.value <= at && hit === Infinity) hit = t;
      const rise = t >= hit ? Math.min((t - hit) / 0.5, 1) : 0;
      const fall = t > PERIOD - 1.1 ? Math.max((PERIOD - t) / 0.9, 0) : 1;
      markLevel.value = rise * Math.min(fall, 1);
    };

    const render = () => {
      renderer.setRenderTarget(target);
      renderer.clear();
      renderer.render(scene, camera);
      renderer.setRenderTarget(null);
      renderer.clear();
      renderer.render(quad, flat);
      // Where the mark is on screen, for the leader line to the comment card.
      main.localToWorld(mark.copy(MARK_LOCAL));
      facing.set(1, 0, 0).transformDirection(main.matrixWorld);
      toCamera.copy(camera.position).sub(mark).normalize();
      const front = facing.dot(toCamera) > 0.15 ? 1 : 0;
      const projected = mark.clone().project(camera);
      const mx = ((projected.x + 1) / 2) * width;
      const my = ((1 - projected.y) / 2) * height;
      // The line runs to the nearest point of the card's edge, inset past its rounded corners.
      const ax = Math.min(Math.max(mx, card.left + 18), card.right - 18);
      const ay = Math.min(Math.max(my, card.top + 18), card.bottom - 18);
      const inside = ax === mx && ay === my;
      const visible = card.ok && !inside ? markLevel.value * front : 0;
      const dx = ax - mx,
        dy = ay - my;
      stage.style.setProperty("--mx", `${mx.toFixed(1)}px`);
      stage.style.setProperty("--my", `${my.toFixed(1)}px`);
      stage.style.setProperty("--mo", visible.toFixed(3));
      stage.style.setProperty(
        "--ml",
        `${Math.max(0, Math.hypot(dx, dy)).toFixed(1)}px`,
      );
      stage.style.setProperty("--ma", `${Math.atan2(dy, dx).toFixed(4)}rad`);
    };

    let frame = 0,
      last = 0,
      running = false,
      onScreen = true,
      ready = false;
    const tick = (now: number) => {
      const dt = last ? Math.min((now - last) / 1000, 0.05) : 0;
      last = now;
      update(dt);
      render();
      if (!ready) {
        ready = true;
        callbacks.current.onReady();
      }
      frame = running ? requestAnimationFrame(tick) : 0;
    };
    const sync = () => {
      const should =
        !still && onScreen && document.visibilityState === "visible";
      if (should && !running) {
        running = true;
        last = 0;
        frame = requestAnimationFrame(tick);
      } else if (!should && running) {
        running = false;
        cancelAnimationFrame(frame);
        frame = 0;
      }
    };

    measure();
    const resize = new ResizeObserver(() => {
      measure();
      if (!running) render();
    });
    resize.observe(art);
    const seen = new IntersectionObserver(([entry]) => {
      onScreen = entry.isIntersecting;
      sync();
    });
    seen.observe(stage);
    document.addEventListener("visibilitychange", sync);
    const lost = (event: Event) => {
      event.preventDefault();
      running = false;
      cancelAnimationFrame(frame);
      callbacks.current.onFail();
    };
    canvas.addEventListener("webglcontextlost", lost);

    if (still) {
      update(0);
      render();
      ready = true;
      callbacks.current.onReady();
    } else sync();

    return () => {
      running = false;
      cancelAnimationFrame(frame);
      resize.disconnect();
      seen.disconnect();
      document.removeEventListener("visibilitychange", sync);
      window.removeEventListener("pointermove", onPointer);
      canvas.removeEventListener("webglcontextlost", lost);
      for (const mesh of group) (mesh.material as ShaderMaterial).dispose();
      box.dispose();
      floorGeometry.dispose();
      floorMaterial.dispose();
      quadGeometry.dispose();
      dotMaterial.dispose();
      target.dispose();
      renderer.dispose();
    };
  }, [still, stage]);

  return <canvas ref={canvasRef} className="ci-stage-canvas" />;
}

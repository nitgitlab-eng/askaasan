/**
 * Procedural, stylised 3D bust of the role-play character (three.js only — no
 * model files). Lazy-loaded by AvatarStage so three.js stays out of the main
 * bundle. Idles (breathing, blinking, glances), lip-syncs from a 0..1 audio
 * level and eases between simple emotions.
 */
import { useEffect, useRef } from "react";
import {
  ACESFilmicToneMapping,
  BoxGeometry,
  CanvasTexture,
  CapsuleGeometry,
  CatmullRomCurve3,
  CircleGeometry,
  Color,
  CylinderGeometry,
  DirectionalLight,
  DoubleSide,
  Group,
  HemisphereLight,
  LatheGeometry,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PerspectiveCamera,
  Scene,
  SphereGeometry,
  SRGBColorSpace,
  TorusGeometry,
  TubeGeometry,
  Vector2,
  Vector3,
  WebGLRenderer,
  type BufferGeometry,
  type Material,
  type Object3D,
} from "three";

import type { AvatarLook, Emotion } from "./avatarLook";

export interface Avatar3DProps {
  look: AvatarLook;
  emotion: Emotion;
  /** Character is "talking" (reply streaming) — used when no live audio level is available. */
  speaking: boolean;
  /** Live 0..1 speech loudness (voice playback); null/undefined = no audio. */
  getLevel?: () => number | null | undefined;
  reducedMotion: boolean;
  /** WebGL failed (creation or context loss) — caller should fall back to chat. */
  onError?: () => void;
  className?: string;
}

interface Pose {
  smile: number;
  browTilt: number;
  browY: number;
  browAsym: number;
  lid: number;
  blush: number;
  tilt: number;
  gazeX: number;
  gazeY: number;
}

const POSES: Record<Emotion, Pose> = {
  neutral: { smile: 0.2, browTilt: 0, browY: 0, browAsym: 0, lid: -0.42, blush: 0, tilt: 0, gazeX: 0, gazeY: 0 },
  happy: { smile: 0.62, browTilt: -0.06, browY: 0.035, browAsym: 0, lid: -0.22, blush: 0.4, tilt: 0.05, gazeX: 0, gazeY: 0 },
  concerned: { smile: -0.22, browTilt: 0.3, browY: 0.02, browAsym: 0, lid: -0.32, blush: 0, tilt: -0.07, gazeX: 0, gazeY: -0.1 },
  thinking: { smile: 0.04, browTilt: -0.04, browY: 0.01, browAsym: 0.07, lid: -0.2, blush: 0, tilt: 0.13, gazeX: 0.45, gazeY: 0.5 },
};

const LID_CLOSED = 0.95;

function std(color: string, roughness = 0.65, extra: Partial<ConstructorParameters<typeof MeshStandardMaterial>[0]> = {}) {
  return new MeshStandardMaterial({ color, roughness, metalness: 0, ...extra });
}

function mesh(geo: BufferGeometry, mat: Material, pos?: [number, number, number], scale?: [number, number, number], rot?: [number, number, number]) {
  const m = new Mesh(geo, mat);
  if (pos) m.position.set(...pos);
  if (scale) m.scale.set(...scale);
  if (rot) m.rotation.set(...rot);
  return m;
}

function shadeHex(hex: string, k: number) {
  const c = new Color(hex);
  return k < 0 ? c.lerp(new Color("#000000"), -k) : c.lerp(new Color("#ffffff"), k);
}

/** Builds the whole bust; returns handles for the animated parts. */
function buildAvatar(look: AvatarLook) {
  const root = new Group();
  const skin = std(look.skin, 0.58, { emissive: new Color(look.skin), emissiveIntensity: 0.06 });
  const skinDark = std(`#${shadeHex(look.skin, -0.12).getHexString()}`, 0.6);
  const hair = std(look.hair, 0.78);
  const top = std(look.top, 0.82);
  const trim = std(look.trim, 0.7, { side: DoubleSide });
  const dark = std("#1d1a1a", 0.35, { metalness: 0.4 });
  const gold = std("#d4a017", 0.3, { metalness: 0.85 });

  // ── Body: a lathed bust, flattened front-to-back ──────────────────────
  const profile = [
    [0.0, -1.7], [1.12, -1.7], [1.24, -1.0], [1.26, -0.55], [1.16, -0.18], [0.92, 0.02], [0.55, 0.1], [0.36, 0.13], [0.0, 0.14],
  ].map(([x, y]) => new Vector2(x, y));
  const torso = mesh(new LatheGeometry(profile, 40), top, [0, 0, 0], [1, 1, 0.62]);
  root.add(torso);
  const neck = mesh(new CylinderGeometry(0.27, 0.32, 0.7, 24), skin, [0, 0.38, -0.02]);
  root.add(neck);

  if (look.collar) {
    root.add(mesh(new TorusGeometry(0.36, 0.07, 10, 28), std("#f8fafc", 0.6), [0, 0.15, -0.02], [1, 1, 0.85], [Math.PI / 2 - 0.15, 0, 0]));
    if (!look.earrings && !look.bindi) root.add(mesh(new CylinderGeometry(0.06, 0.13, 0.75, 4), std(look.trim, 0.55), [0, -0.3, 0.67], [1, 1, 0.35], [-0.12, Math.PI / 4, 0]));
  } else {
    root.add(mesh(new TorusGeometry(0.4, 0.035, 8, 28), std(`#${shadeHex(look.top, -0.25).getHexString()}`, 0.8), [0, 0.11, 0], [1, 1, 0.8], [Math.PI / 2 - 0.1, 0, 0]));
  }
  if (look.dupatta) {
    const curve = new CatmullRomCurve3([
      new Vector3(0.95, -0.7, -0.4), new Vector3(0.92, -0.05, -0.15), new Vector3(0.78, 0.08, 0.22),
      new Vector3(0.42, -0.35, 0.6), new Vector3(-0.2, -0.95, 0.74), new Vector3(-0.85, -1.6, 0.66),
    ]);
    root.add(mesh(new TubeGeometry(curve, 48, 0.13, 10, false), trim, undefined, [1, 1, 1]));
    const border = new CatmullRomCurve3(curve.points.map((p) => p.clone().add(new Vector3(0.0, -0.11, 0.06))));
    root.add(mesh(new TubeGeometry(border, 48, 0.035, 6, false), gold));
  }
  if (look.scarf) {
    root.add(mesh(new TorusGeometry(0.42, 0.13, 12, 32), trim, [0, 0.12, 0], [1, 1, 0.85], [Math.PI / 2 - 0.12, 0, 0]));
    root.add(mesh(new CapsuleGeometry(0.11, 0.55, 6, 12), trim, [0.24, -0.32, 0.6], [1.3, 1, 0.5], [0.1, 0, 0.12]));
  }

  // ── Head (pivots at the neck) ───────────────────────────────────────────
  const head = new Group();
  head.position.set(0, 0.55, 0);
  root.add(head);
  const C = 0.75; // skull centre height inside the head group
  head.add(mesh(new SphereGeometry(1, 48, 40), skin, [0, C, 0], [0.9, 1.02, 0.92]));
  for (const s of [-1, 1]) head.add(mesh(new SphereGeometry(0.18, 20, 16), skin, [s * 0.87, C - 0.03, -0.02], [0.5, 1, 0.7]));
  head.add(mesh(new SphereGeometry(0.11, 20, 16), skinDark, [0, C - 0.15, 0.9], [0.95, 1, 1.15]));

  // Eyes: sclera + gaze pivot (iris, pupil) + fixed highlight + upper lid.
  const sclera = std("#fbf7f2", 0.25);
  const irisMat = std(look.iris, 0.3);
  const pupilMat = new MeshBasicMaterial({ color: "#0b0706" });
  const shine = new MeshBasicMaterial({ color: "#ffffff" });
  const eyes: { gaze: Group; lid: Group }[] = [];
  for (const s of [-1, 1]) {
    const eye = new Group();
    eye.position.set(s * 0.31, C + 0.12, 0.8);
    eye.add(mesh(new SphereGeometry(0.15, 28, 20), sclera));
    const gaze = new Group();
    gaze.add(mesh(new SphereGeometry(0.095, 24, 16), irisMat, [0, 0, 0.113], [1, 1, 0.45]));
    gaze.add(mesh(new SphereGeometry(0.05, 16, 12), pupilMat, [0, 0, 0.138], [1, 1, 0.4]));
    eye.add(gaze);
    eye.add(mesh(new SphereGeometry(0.026, 10, 8), shine, [0.04, 0.045, 0.16]));
    const lid = new Group();
    lid.add(mesh(new SphereGeometry(0.163, 28, 14, 0, Math.PI * 2, 0, Math.PI / 2), std(look.skin, 0.58, { side: DoubleSide })));
    lid.add(mesh(new TorusGeometry(0.163, 0.012, 6, 32, Math.PI), dark, [0, 0, 0], [1, 1, 1], [Math.PI / 2, 0, Math.PI]));
    eye.add(lid);
    head.add(eye);
    eyes.push({ gaze, lid });
  }

  const brows: Mesh[] = [];
  for (const s of [-1, 1]) {
    const b = mesh(new CapsuleGeometry(0.034, 0.2, 4, 10), hair, [s * 0.31, C + 0.36, 0.82], [1, 1, 0.7], [0, 0, Math.PI / 2]);
    head.add(b);
    brows.push(b);
  }

  // Mouth: tilted to follow the face; dark opening + teeth + smile line.
  const mouth = new Group();
  mouth.position.set(0, C - 0.37, 0.84);
  mouth.rotation.x = 0.37;
  head.add(mouth);
  const inner = mesh(new SphereGeometry(1, 24, 16), std("#4a1820", 0.8), [0, 0, 0], [0.16, 0.012, 0.07]);
  const teeth = mesh(new BoxGeometry(0.2, 0.04, 0.04), std("#fbfaf7", 0.4), [0, -0.01, 0.045]);
  const smile = mesh(new TorusGeometry(0.15, 0.019, 8, 28, Math.PI), std(look.lips, 0.5, { side: DoubleSide }), [0, 0.035, 0.05], [1, 0.2, 1], [0, 0, Math.PI]);
  mouth.add(inner, teeth, smile);

  const blushMat = new MeshBasicMaterial({ color: "#ff6f7f", transparent: true, opacity: 0, depthWrite: false });
  for (const s of [-1, 1]) head.add(mesh(new CircleGeometry(0.12, 24), blushMat, [s * 0.52, C - 0.18, 0.75], [1, 0.7, 1], [0, s * 0.62, 0]));

  if (look.moustache) {
    for (const s of [-1, 1]) head.add(mesh(new CapsuleGeometry(0.038, 0.12, 4, 8), hair, [s * 0.075, C - 0.27, 0.88], [1, 1, 0.7], [0, 0, Math.PI / 2 + s * 0.35]));
  }
  if (look.beard) {
    head.add(mesh(new SphereGeometry(1.03, 40, 20, 0, Math.PI * 2, 2.2, Math.PI - 2.2), hair, [0, C, 0], [0.92, 1.03, 0.94]));
  }
  if (look.bindi) head.add(mesh(new SphereGeometry(0.032, 12, 8), new MeshBasicMaterial({ color: "#c81d3a" }), [0, C + 0.27, 0.89], [1, 1, 0.4]));
  if (look.earrings) for (const s of [-1, 1]) head.add(mesh(new SphereGeometry(0.06, 14, 10), gold, [s * 0.86, C - 0.25, 0.02]));

  // Hair.
  const capTheta = look.hairStyle === "side" ? 1.28 : 1.33;
  if (look.hairStyle === "bald") {
    head.add(mesh(new SphereGeometry(1.035, 40, 20, Math.PI * 0.85, Math.PI * 1.3, 1.05, 0.8), hair, [0, C, 0], [0.9, 1.02, 0.92]));
  } else {
    head.add(mesh(new SphereGeometry(1.05, 48, 24, 0, Math.PI * 2, 0, capTheta), hair, [0, C + 0.02, -0.02], [0.92, 1.03, 0.94], [-0.38, 0, 0]));
  }
  if (look.hairStyle === "side") head.add(mesh(new SphereGeometry(0.42, 24, 16), hair, [0.28, C + 0.82, 0.38], [1.2, 0.45, 0.8], [0.4, 0, -0.25]));
  if (look.hairStyle === "curly") {
    const n = 46;
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 0.95; // upper hemisphere (fibonacci sphere)
      const r = Math.sqrt(1 - y * y);
      const a = i * 2.399963;
      const p = new Vector3(Math.cos(a) * r, y, Math.sin(a) * r);
      if (p.z > 0.55 && p.y < 0.6) continue; // keep the face clear
      head.add(mesh(new SphereGeometry(0.2, 12, 10), hair, [p.x * 0.95, C + 0.05 + p.y * 1.0, p.z * 0.95 - 0.04]));
    }
  }
  if (look.hairStyle === "bun") head.add(mesh(new SphereGeometry(0.34, 24, 18), hair, [0, C + 0.72, -0.62]));
  if (look.hairStyle === "long" || look.hairStyle === "braid") {
    head.add(mesh(new CapsuleGeometry(0.55, 0.9, 8, 20), hair, [0, C - 0.55, -0.42], [1.45, 1, 0.5]));
    if (look.hairStyle === "long") for (const s of [-1, 1]) head.add(mesh(new CapsuleGeometry(0.15, 0.85, 6, 12), hair, [s * 0.8, C - 0.42, 0.06], [1, 1, 0.75], [0.05, 0, s * 0.08]));
  }
  if (look.hairStyle === "braid") {
    const pts = new CatmullRomCurve3([new Vector3(0.62, C - 0.25, -0.35), new Vector3(0.78, C - 0.75, 0.05), new Vector3(0.72, C - 1.3, 0.48), new Vector3(0.6, C - 1.95, 0.62)]);
    for (let i = 0; i <= 9; i++) {
      const p = pts.getPoint(i / 9);
      head.add(mesh(new SphereGeometry(0.13 - i * 0.004, 14, 10), hair, [p.x, p.y, p.z], [1, 1.2, 0.9]));
    }
    head.add(mesh(new SphereGeometry(0.06, 10, 8), trim, (() => { const p = pts.getPoint(1); return [p.x, p.y - 0.12, p.z] as [number, number, number]; })()));
  }

  if (look.glasses) {
    for (const s of [-1, 1]) {
      head.add(mesh(new TorusGeometry(0.17, 0.02, 8, 32), dark, [s * 0.31, C + 0.12, 0.98]));
      head.add(mesh(new BoxGeometry(0.03, 0.03, 0.85), dark, [s * 0.47, C + 0.15, 0.55], undefined, [0, s * 0.12, 0]));
    }
    head.add(mesh(new CylinderGeometry(0.016, 0.016, 0.28, 8), dark, [0, C + 0.15, 1.0], undefined, [0, 0, Math.PI / 2]));
  }
  if (look.cap) {
    const capMat = std(look.trim, 0.75, { side: DoubleSide });
    head.add(mesh(new SphereGeometry(1.08, 40, 20, 0, Math.PI * 2, 0, Math.PI / 2), capMat, [0, C + 0.18, -0.02], [0.92, 0.78, 0.96], [-0.12, 0, 0]));
    head.add(mesh(new CylinderGeometry(0.62, 0.62, 0.04, 32, 1, false, -Math.PI / 2, Math.PI), capMat, [0, C + 0.28, 0.62], [0.95, 1, 0.9], [0.18, 0, 0]));
    head.add(mesh(new SphereGeometry(0.06, 10, 8), capMat, [0, C + 0.98, -0.1]));
  }

  return { root, torso, head, eyes, brows, inner, teeth, smile, blushMat };
}

function themeColours() {
  const cs = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string) => {
    const v = cs.getPropertyValue(name).trim();
    try {
      return v ? new Color(v) : new Color(fallback);
    } catch {
      return new Color(fallback);
    }
  };
  return { bg: read("--bg", "#fff8f0"), surface: read("--surface", "#ffffff"), accent: read("--accent", "#f97316") };
}

function gradientTexture(top: Color, bottom: Color, accent: Color) {
  const c = document.createElement("canvas");
  c.width = 4;
  c.height = 256;
  const g = c.getContext("2d");
  if (g) {
    const grad = g.createLinearGradient(0, 0, 0, 256);
    grad.addColorStop(0, `#${top.getHexString()}`);
    grad.addColorStop(1, `#${bottom.clone().lerp(accent, 0.12).getHexString()}`);
    g.fillStyle = grad;
    g.fillRect(0, 0, 4, 256);
  }
  const tex = new CanvasTexture(c);
  tex.colorSpace = SRGBColorSpace;
  return tex;
}

export default function Avatar3D({ look, emotion, speaking, getLevel, reducedMotion, onError, className }: Avatar3DProps) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef({ emotion, speaking, getLevel, reducedMotion, onError });
  useEffect(() => {
    live.current = { emotion, speaking, getLevel, reducedMotion, onError };
  });

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ antialias: true, alpha: false, powerPreference: "low-power" });
    } catch {
      live.current.onError?.();
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = SRGBColorSpace;
    renderer.toneMapping = ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    const canvas = renderer.domElement;
    canvas.setAttribute("aria-hidden", "true");
    canvas.style.display = "block";
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    el.appendChild(canvas);

    const scene = new Scene();
    const camera = new PerspectiveCamera(28, 1, 0.1, 50);
    const hemi = new HemisphereLight("#fff6ec", "#6b5444", 1.35);
    const key = new DirectionalLight("#fff1e0", 2.3);
    key.position.set(-2.5, 4, 5);
    const fill = new DirectionalLight("#dbe8ff", 0.75);
    fill.position.set(3, 1.5, 4);
    const rim = new DirectionalLight("#ffffff", 1.6);
    rim.position.set(0.5, 3, -4);
    scene.add(hemi, key, fill, rim);

    const halo = mesh(new CircleGeometry(2.05, 64), new MeshBasicMaterial({ transparent: true, opacity: 0.16, depthWrite: false }), [0, 1.2, -1.6]);
    scene.add(halo);

    let bgTex: CanvasTexture | null = null;
    const applyTheme = () => {
      const { bg, surface, accent } = themeColours();
      bgTex?.dispose();
      bgTex = gradientTexture(surface, bg, accent);
      scene.background = bgTex;
      (halo.material as MeshBasicMaterial).color.copy(accent);
      rim.color.copy(accent).lerp(new Color("#ffffff"), 0.45);
    };
    applyTheme();
    const themeObs = new MutationObserver(applyTheme);
    themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "style", "class"] });

    const av = buildAvatar(look);
    scene.add(av.root);

    const resize = () => {
      const w = Math.max(1, el.clientWidth);
      const h = Math.max(1, el.clientHeight);
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      // Frame head + shoulders whatever the aspect (portrait phones included).
      const t = Math.tan((camera.fov * Math.PI) / 360);
      const d = Math.max(1.7 / t, 1.55 / (t * camera.aspect)) * 1.04;
      camera.position.set(0, 1.12, d);
      camera.lookAt(0, 0.95, 0);
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);

    // ── Animation state ────────────────────────────────────────────────
    const pose: Pose = { ...POSES[live.current.emotion] };
    let mouthOpen = 0;
    let blinkAt = performance.now() + 1500;
    let blinkStart = -1;
    let saccadeAt = 0;
    const saccade = { x: 0, y: 0 };
    let last = performance.now();
    let raf = 0;
    let visible = !document.hidden;
    let onScreen = true;

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const t = now / 1000;
      const { emotion: emo, speaking: talking, getLevel: lvl, reducedMotion: calm } = live.current;

      // Ease towards the emotion pose.
      const target = POSES[emo];
      const k = calm ? 1 : 1 - Math.exp(-dt * 5);
      for (const key of Object.keys(pose) as (keyof Pose)[]) pose[key] += (target[key] - pose[key]) * k;

      // Mouth: live audio level wins; otherwise a soft synthetic talk loop while text streams.
      const level = lvl?.();
      let want = 0;
      if (level != null) want = Math.min(1, level * 1.15) * (calm ? 0.6 : 1);
      else if (talking) want = calm ? 0.15 : 0.12 + 0.45 * Math.abs(Math.sin(t * 11)) * (0.55 + 0.45 * Math.sin(t * 2.7));
      mouthOpen += (want - mouthOpen) * (want > mouthOpen ? 0.55 : 0.28);
      const open = Math.max(0, mouthOpen);
      av.inner.scale.y = 0.012 + open * 0.12;
      av.inner.position.y = -open * 0.05;
      av.teeth.visible = open > 0.12;
      av.teeth.scale.y = Math.min(1, open * 2);
      av.smile.scale.y = pose.smile * (1 - open * 0.6) + (pose.smile >= 0 ? 0.04 : -0.04);
      av.smile.position.y = 0.035 + (pose.smile < 0 ? -0.06 : 0);

      // Blink (rarer when reduced motion is on).
      if (blinkStart < 0 && now > blinkAt) blinkStart = now;
      let blink = 0;
      if (blinkStart >= 0) {
        const p = (now - blinkStart) / 150;
        blink = p < 1 ? Math.sin(p * Math.PI) : 0;
        if (p >= 1) {
          blinkStart = -1;
          blinkAt = now + (calm ? 5000 : 2200) + Math.random() * (calm ? 4000 : 3800);
        }
      }
      for (const e of av.eyes) e.lid.rotation.x = pose.lid + (LID_CLOSED - pose.lid) * blink;

      // Gaze: look at the camera, with tiny glances unless reduced motion.
      if (!calm && now > saccadeAt) {
        saccadeAt = now + 1200 + Math.random() * 2800;
        saccade.x = (Math.random() - 0.5) * 0.12;
        saccade.y = (Math.random() - 0.5) * 0.08;
      }
      const gx = pose.gazeX + (calm ? 0 : saccade.x);
      const gy = pose.gazeY + (calm ? 0 : saccade.y);
      for (const e of av.eyes) e.gaze.rotation.set(-gy * 0.45, gx * 0.5, 0);

      // Brows.
      const [bl, br] = av.brows;
      bl.position.y = 0.75 + 0.36 + pose.browY;
      br.position.y = 0.75 + 0.36 + pose.browY + pose.browAsym;
      bl.rotation.z = Math.PI / 2 + pose.browTilt;
      br.rotation.z = Math.PI / 2 - pose.browTilt;
      av.blushMat.opacity = pose.blush * 0.55;

      // Idle life: breathing + gentle head sway (off for reduced motion).
      const sway = calm ? 0 : 1;
      av.torso.scale.y = 1 + sway * 0.012 * Math.sin(t * 1.5);
      av.head.position.y = 0.55 + sway * 0.012 * Math.sin(t * 1.5 - 0.4);
      av.head.rotation.y = sway * (0.07 * Math.sin(t * 0.45) + 0.025 * Math.sin(t * 1.1)) - pose.gazeX * 0.12;
      av.head.rotation.x = sway * (0.03 * Math.sin(t * 0.6) + open * 0.03 * Math.sin(t * 7)) - pose.gazeY * 0.05;
      av.head.rotation.z = pose.tilt + sway * 0.015 * Math.sin(t * 0.37);

      renderer.render(scene, camera);
    };
    const run = () => {
      cancelAnimationFrame(raf);
      if (visible && onScreen) {
        last = performance.now();
        raf = requestAnimationFrame(frame);
      }
    };
    const onVis = () => {
      visible = !document.hidden;
      run();
    };
    document.addEventListener("visibilitychange", onVis);
    const io = typeof IntersectionObserver !== "undefined" ? new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; run(); }) : null;
    io?.observe(el);
    const onLost = (e: Event) => {
      e.preventDefault();
      cancelAnimationFrame(raf);
      live.current.onError?.();
    };
    canvas.addEventListener("webglcontextlost", onLost);
    run();

    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVis);
      canvas.removeEventListener("webglcontextlost", onLost);
      io?.disconnect();
      ro.disconnect();
      themeObs.disconnect();
      const geos = new Set<BufferGeometry>();
      const mats = new Set<Material>();
      scene.traverse((o: Object3D) => {
        const m = o as Mesh;
        if (m.isMesh) {
          geos.add(m.geometry);
          for (const mt of Array.isArray(m.material) ? m.material : [m.material]) mats.add(mt);
        }
      });
      geos.forEach((g) => g.dispose());
      mats.forEach((m) => m.dispose());
      bgTex?.dispose();
      renderer.dispose();
      canvas.remove();
    };
  }, [look]);

  return <div ref={host} className={className} />;
}

import { useEffect, useMemo, useRef } from "react";

/*
 * NAVIRA's living background: a city at dusk. Streets lie on the ground in
 * perspective and drift slowly towards the viewer; soft route pulses travel
 * along them and location pins breathe at a few junctions. A skyline with lit
 * windows sits on the horizon under a low sun, with glass bubbles in front.
 *
 * Decoration only: aria-hidden, no pointer events, paused when the tab is
 * hidden, a single still frame on phones and with reduced motion. All colours
 * come from the theme tokens in glass.css.
 */

function hash(i, j, salt = 0) {
  let h = (i * 374761393 + j * 668265263 + salt * 2147483647) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967295;
}

const GAP_X = 1.3;
const GAP_Z = 1.15;
const NEAR = 0.55;
const FAR = 24;
const SPEED = 0.1;

const streetX = (i, j) => hash(i, j, 1) < 0.7;
const streetZ = (i, j) => hash(i, j, 2) < 0.55;
const node = (i, j) => ({ x: i * GAP_X + (hash(i, j, 3) - 0.5) * 0.35, z: j * GAP_Z + (hash(i, j, 4) - 0.5) * 0.3 });

function readPalette() {
  const css = getComputedStyle(document.documentElement);
  const v = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  return {
    line: v("--bg-line", "80, 50, 64"),
    lineAlpha: parseFloat(v("--bg-line-alpha", "0.18")),
    route: v("--bg-pulse", "199, 94, 121"),
    pin: v("--bg-pulse-2", "120, 90, 200"),
  };
}

function StreetCanvas() {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext?.("2d");
    if (!ctx) return undefined;
    const lowPower = window.matchMedia?.("(pointer: coarse)").matches || window.innerWidth < 768;
    const still = lowPower || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let palette = readPalette();
    let w = 0;
    let h = 0;
    let dpr = 1;
    let raf = 0;
    let last = performance.now();
    let travel = 0;
    const pulses = [];

    const horizon = () => h * 0.34;
    const focal = () => (h - horizon()) * 0.62;
    const project = (x, z) => ({ sx: w / 2 + (x * focal()) / z, sy: horizon() + focal() / z });
    const depthAlpha = (z) => {
      const near = Math.min(1, Math.max(0, (z - NEAR) / 2));
      const far = Math.min(1, Math.max(0, (FAR - z) / (FAR * 0.65)));
      return near * far * far;
    };

    const spawn = () => {
      const base = Math.floor(travel / GAP_Z);
      for (let tries = 0; tries < 30; tries += 1) {
        const j = base + 2 + Math.floor(Math.random() * 10);
        const halfCols = Math.floor(((w / 2 / focal()) * (j * GAP_Z - travel)) / GAP_X) + 1;
        const i = Math.floor((Math.random() * 2 - 1) * halfCols * 0.8);
        const dir = Math.random() < 0.65 ? 0 : 1;
        if (dir === 0 ? streetX(i, j) : streetZ(i, j)) return { i, j, dir, p: 0, speed: 0.3 + Math.random() * 0.4 };
      }
      return { i: 0, j: base + 5, dir: 0, p: 1, speed: 1 };
    };

    function draw(dt) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const f = focal();
      const jStart = Math.floor((travel + NEAR) / GAP_Z) - 1;
      const jEnd = Math.ceil((travel + FAR) / GAP_Z);

      for (let j = jEnd; j >= jStart; j -= 1) {
        const zRow = j * GAP_Z - travel;
        if (zRow <= NEAR * 0.6) continue;
        const a = depthAlpha(zRow) * palette.lineAlpha;
        if (a < 0.004) continue;
        const half = Math.ceil(((w / 2) * zRow) / f / GAP_X) + 2;
        ctx.beginPath();
        for (let i = -half; i <= half; i += 1) {
          const n = node(i, j);
          const p = project(n.x, n.z - travel);
          if (streetX(i, j)) {
            const m = node(i + 1, j);
            const q = project(m.x, m.z - travel);
            ctx.moveTo(p.sx, p.sy);
            ctx.lineTo(q.sx, q.sy);
          }
          if (streetZ(i, j)) {
            const m = node(i, j + 1);
            const zz = m.z - travel;
            if (zz > NEAR * 0.5) {
              const q = project(m.x, zz);
              ctx.moveTo(p.sx, p.sy);
              ctx.lineTo(q.sx, q.sy);
            }
          }
        }
        ctx.strokeStyle = `rgba(${palette.line}, ${a})`;
        ctx.lineWidth = Math.max(0.6, Math.min(1.4, 2.4 / zRow));
        ctx.stroke();

        // Location pins: a dot with a breathing ring at a few junctions.
        for (let i = -half; i <= half; i += 1) {
          if (hash(i, j, 5) > 0.035) continue;
          const n = node(i, j);
          const z = n.z - travel;
          if (z <= NEAR + 0.6) continue;
          const p = project(n.x, z);
          const size = Math.max(1.2, 6 / z);
          const breathe = still ? 0.5 : (Math.sin(performance.now() / 900 + hash(i, j, 6) * 6.28) + 1) / 2;
          const pa = Math.min(1, depthAlpha(z) * 1.6);
          ctx.beginPath();
          ctx.arc(p.sx, p.sy, size * (1.8 + breathe * 1.6), 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(${palette.pin}, ${pa * (0.45 - breathe * 0.3)})`;
          ctx.lineWidth = 1;
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(p.sx, p.sy, size, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${palette.pin}, ${pa * 0.85})`;
          ctx.fill();
        }
      }

      // Route pulses: short glowing segments travelling along streets.
      if (!still) {
        while (pulses.length < 14) pulses.push(spawn());
        for (let k = pulses.length - 1; k >= 0; k -= 1) {
          const pulse = pulses[k];
          pulse.p += pulse.speed * dt;
          if (pulse.p >= 1 || pulse.j * GAP_Z - travel < NEAR) { pulses.splice(k, 1); continue; }
          const from = node(pulse.i, pulse.j);
          const to = pulse.dir === 0 ? node(pulse.i + 1, pulse.j) : node(pulse.i, pulse.j + 1);
          const t0 = Math.max(0, pulse.p - 0.28);
          const at = (t) => ({ x: from.x + (to.x - from.x) * t, z: from.z + (to.z - from.z) * t - travel });
          const head = at(pulse.p);
          const tail = at(t0);
          if (head.z <= NEAR || tail.z <= NEAR) continue;
          const ph = project(head.x, head.z);
          const pt = project(tail.x, tail.z);
          const pa = depthAlpha(head.z);
          const grad = ctx.createLinearGradient(pt.sx, pt.sy, ph.sx, ph.sy);
          grad.addColorStop(0, `rgba(${palette.route}, 0)`);
          grad.addColorStop(1, `rgba(${palette.route}, ${0.9 * pa})`);
          ctx.beginPath();
          ctx.moveTo(pt.sx, pt.sy);
          ctx.lineTo(ph.sx, ph.sy);
          ctx.strokeStyle = grad;
          ctx.lineWidth = Math.max(1.2, Math.min(3, 5 / head.z));
          ctx.lineCap = "round";
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(ph.sx, ph.sy, Math.max(1.4, 4 / head.z), 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${palette.route}, ${pa})`;
          ctx.fill();
        }
      }
    }

    const resize = () => {
      if (w && window.innerWidth === w && Math.abs(window.innerHeight - h) < 160) return;
      dpr = Math.min(window.devicePixelRatio || 1, lowPower ? 1 : 1.75);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      draw(0);
    };

    const frame = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      travel += SPEED * dt;
      draw(dt);
      raf = requestAnimationFrame(frame);
    };
    const start = () => { if (!still && !raf && document.visibilityState === "visible") { last = performance.now(); raf = requestAnimationFrame(frame); } };
    const stop = () => { cancelAnimationFrame(raf); raf = 0; };
    const onVisibility = () => (document.visibilityState === "visible" ? start() : stop());

    // Recolour when the theme or light/dark mode changes.
    const observer = typeof MutationObserver === "function"
      ? new MutationObserver(() => { requestAnimationFrame(() => { palette = readPalette(); draw(0); }); })
      : null;
    observer?.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-mode"] });

    resize();
    start();
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      observer?.disconnect();
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return <canvas ref={ref} className="city-backdrop__streets"/>;
}

/** Deterministic skyline: towers with lit windows, a dome and a gateway arch. */
function Skyline() {
  const buildings = useMemo(() => {
    const items = [];
    let x = 0;
    let k = 0;
    while (x < 1600) {
      const width = 34 + Math.floor(hash(k, 7) * 56);
      const height = 40 + Math.floor(hash(k, 8) * hash(k, 9) * 150);
      items.push({ x, width, height, k });
      x += width + 4 + Math.floor(hash(k, 10) * 10);
      k += 1;
    }
    return items;
  }, []);

  return <svg className="city-backdrop__skyline" viewBox="0 0 1600 200" preserveAspectRatio="xMidYMax slice">
    <g fill="var(--skyline)">
      {buildings.map(({ x, width, height, k }) => <rect key={k} x={x} y={200 - height} width={width} height={height} rx="2"/>)}
      {/* a dome with a short spire */}
      <path d="M520 200v-62h96v62Z M526 138a42 42 0 0 1 84 0Z M566 96h4v-18h-4Z"/>
      {/* a gateway arch */}
      <path d="M1050 200v-118h120v118h-34v-62a26 26 0 0 0-52 0v62Z M1042 82h136v-10h-136Z"/>
    </g>
    <g fill="var(--window)">
      {buildings.flatMap(({ x, width, height, k }) => {
        const windows = [];
        for (let row = 0; row < Math.floor((height - 12) / 14); row += 1) {
          for (let col = 0; col < Math.floor((width - 8) / 12); col += 1) {
            if (hash(k * 31 + row, col, 11) < 0.28) windows.push(<rect key={`${k}-${row}-${col}`} x={x + 6 + col * 12} y={200 - height + 8 + row * 14} width="5" height="6" rx="1"/>);
          }
        }
        return windows;
      })}
    </g>
  </svg>;
}

const bubbles = [
  { left: "8%", top: "58%", size: 120, delay: "0s" },
  { left: "82%", top: "62%", size: 86, delay: "-6s" },
  { left: "64%", top: "14%", size: 54, delay: "-11s" },
  { left: "22%", top: "18%", size: 38, delay: "-3s" },
  { left: "46%", top: "80%", size: 70, delay: "-15s" },
];

export default function CityBackdrop() {
  return <div className="city-backdrop" aria-hidden="true">
    <div className="city-backdrop__glow city-backdrop__glow--sun"/>
    <div className="city-backdrop__glow city-backdrop__glow--haze"/>
    <div className="city-backdrop__sun"/>
    <div className="city-backdrop__horizon"/>
    <Skyline/>
    <StreetCanvas/>
    {bubbles.map((bubble) => <span key={bubble.left} className="city-backdrop__bubble" style={{ left: bubble.left, top: bubble.top, width: bubble.size, height: bubble.size, animationDelay: bubble.delay }}/>)}
    <div className="city-backdrop__vignette"/>
    <div className="city-backdrop__grain"/>
  </div>;
}

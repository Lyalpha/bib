/* Binary-system visualiser: a live canvas rendering of the current track state.
 *
 * Stars are drawn to a common physical scale (a dynamic scale bar shows R☉).
 * Temperature sets colour (blackbody → sRGB), radius sets size, the pair
 * revolves at the true orbital period accelerated by a display factor, and:
 *   - strong winds grow a soft halo,
 *   - near Roche-lobe filling the star distorts into a teardrop and, when
 *     overflowing, sheds a particle stream through L1 onto the companion,
 *   - common-envelope phases wrap both stars in a shared translucent envelope,
 *   - compact companions (secondary tracks) render as a white-dwarf/NS point.
 *
 * The page pushes state with setState(); the viz runs its own rAF loop so the
 * orbit keeps turning even while track playback is paused (unless frozen).
 */
"use strict";

/* Blackbody temperature -> approximate sRGB (anchors after Mitchell Charity). */
const TEFF_ANCHORS = [
  [1000, [255, 56, 0]],
  [2000, [255, 137, 18]],
  [3000, [255, 180, 107]],
  [4000, [255, 209, 163]],
  [5000, [255, 228, 206]],
  [6000, [255, 243, 239]],
  [7000, [245, 243, 255]],
  [8000, [227, 233, 255]],
  [10000, [204, 216, 255]],
  [15000, [170, 196, 255]],
  [20000, [155, 184, 255]],
  [30000, [141, 180, 255]],
  [50000, [133, 172, 255]],
];

export function teffToRgb(teff) {
  if (!isFinite(teff) || teff <= 0) return "rgb(200,200,200)";
  const t = Math.min(Math.max(teff, TEFF_ANCHORS[0][0]), TEFF_ANCHORS.at(-1)[0]);
  let i = 0;
  while (i < TEFF_ANCHORS.length - 2 && TEFF_ANCHORS[i + 1][0] < t) i++;
  const [t0, c0] = TEFF_ANCHORS[i];
  const [t1, c1] = TEFF_ANCHORS[i + 1];
  const w = (t - t0) / (t1 - t0);
  const mix = c0.map((v, k) => Math.round(v + (c1[k] - v) * w));
  return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
}

export class BinaryViz {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.state = null;
    this.angle = 0;
    this.scale = 1; // px per Rsun (smoothed)
    this.orbitBoost = 1; // user speed multiplier
    this.orbitFrozen = false;
    this.fitMode = "auto"; // 'auto' | 'true'
    this.particles = [];
    this.envelopePulse = 0;
    this._last = null;
    this._running = true;
    this._resize = this._resize.bind(this);
    window.addEventListener("resize", this._resize);
    this._resize();
    requestAnimationFrame(this._loop);
  }

  destroy() {
    this._running = false;
    window.removeEventListener("resize", this._resize);
  }

  _resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    this.canvas.width = Math.max(10, Math.round(rect.width * dpr));
    this.canvas.height = Math.max(10, Math.round(rect.height * dpr));
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.width = rect.width;
    this.height = rect.height;
  }

  /** Push the current physical state (all lengths in R☉, temperatures in K). */
  setState(s) {
    this.state = s;
  }

  _loop = (now) => {
    if (!this._running) return;
    const dt = this._last ? Math.min((now - this._last) / 1000, 0.1) : 0.016;
    this._last = now;
    this._step(dt);
    this._draw();
    requestAnimationFrame(this._loop);
  };

  _step(dt) {
    const s = this.state;
    if (!s) return;
    if (
      !this.orbitFrozen &&
      this.orbitBoost > 0 &&
      s.mode === "binary" &&
      isFinite(s.periodYr) &&
      s.periodYr > 0
    ) {
      // Real period, sped up: aim for visible rotation (~1/40 yr of model time
      // per second of wall time at boost 1), clamped to a watchable range.
      let revPerSec = 0.025 / s.periodYr;
      revPerSec = Math.min(Math.max(revPerSec * this.orbitBoost, 0.02), 1.6);
      this.angle += 2 * Math.PI * revPerSec * dt;
    }
    this.envelopePulse += dt * 2.2;

    // particle stream during RLOF
    if (s.mode === "binary" && s.rlofActive && this.particles.length < 70) {
      for (let n = 0; n < 3; n++) this.particles.push(this._spawnParticle());
    }
    for (const p of this.particles) {
      p.t += dt * (0.6 + 0.5 * Math.random() * 0);
    }
    this.particles = this.particles.filter((p) => p.t < 1);
  }

  _spawnParticle() {
    return { t: Math.random() * 0.15, jitter: (Math.random() - 0.5) * 0.16, size: 1 + Math.random() * 1.6 };
  }

  _targetScale(s) {
    const pad = 0.86;
    const half = Math.min(this.width, this.height) * 0.5 * pad;
    if (s.mode !== "binary" || !isFinite(s.sep)) {
      const r = Math.max(s.r1 || 1, 0.05);
      return (half * 0.62) / r;
    }
    let extent = s.sep * 0.62 + Math.max(s.r1 || 0, s.r2 || 0); // COM offsets + radius
    if (this.fitMode === "auto") {
      // keep the *smaller* star at least ~2.5 px so it never vanishes
      const rMin = Math.max(Math.min(s.r1 || 1e9, s.r2 || 1e9), 0.05);
      const scaleFit = half / extent;
      if (rMin * scaleFit < 2.5) {
        return Math.min(2.5 / rMin, (half * 0.9) / Math.max(s.r1 || 1, s.r2 || 1, 1));
      }
      return scaleFit;
    }
    return half / extent;
  }

  _draw() {
    const ctx = this.ctx;
    const s = this.state;
    ctx.clearRect(0, 0, this.width, this.height);
    if (!s) return;

    const cx = this.width / 2;
    const cy = this.height / 2;
    const target = this._targetScale(s);
    this.scale += (target - this.scale) * 0.08;
    const px = (r) => Math.max(r * this.scale, 0.6);

    if (s.mode !== "binary") {
      this._drawStar(cx, cy, s.r1, s.t1, s.mdot1, s.windHalo, null, s);
      this._drawScaleBar();
      return;
    }

    // centre-of-mass offsets (star 1 at distance a1 = a·m2/(m1+m2))
    const mTot = (s.m1 || 1) + (s.m2 || 1);
    const a1 = (s.sep * (s.m2 || 1)) / mTot;
    const a2 = (s.sep * (s.m1 || 1)) / mTot;
    const cosA = Math.cos(this.angle);
    const sinA = Math.sin(this.angle) * 0.42; // mild inclination for depth
    const x1 = cx - a1 * this.scale * cosA;
    const y1 = cy - a1 * this.scale * sinA;
    const x2 = cx + a2 * this.scale * cosA;
    const y2 = cy + a2 * this.scale * sinA;

    // orbit paths
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.10)";
    ctx.lineWidth = 1;
    for (const [ax, ecc] of [[a1, 1], [a2, 1]]) {
      ctx.beginPath();
      ctx.ellipse(cx, cy, ax * this.scale, ax * this.scale * 0.42 * ecc, 0, 0, 2 * Math.PI);
      ctx.stroke();
    }
    ctx.restore();

    // Engulfment: companion orbits *inside* the primary's envelope (CEE, or a
    // giant simply larger than the orbit). Draw the envelope translucent with
    // the hot core and the companion visible inside — the physics is the point.
    const engulfed =
      s.ceeActive || (isFinite(s.sep) && s.sep + Math.max(s.r2 || 0, 0.5) < (s.r1 || 0));

    if (engulfed) {
      const pulse = s.ceeActive ? 1 + 0.04 * Math.sin(this.envelopePulse) : 1;
      const rEnv = Math.max(s.r1 * this.scale * pulse, 8);
      const colour = teffToRgb(s.t1);
      const grad = ctx.createRadialGradient(x1, y1, rEnv * 0.02, x1, y1, rEnv);
      grad.addColorStop(0, "rgba(255,252,240,0.34)");
      grad.addColorStop(0.12, colour.replace("rgb", "rgba").replace(")", ",0.26)"));
      grad.addColorStop(0.8, colour.replace("rgb", "rgba").replace(")", ",0.15)"));
      grad.addColorStop(1, colour.replace("rgb", "rgba").replace(")", ",0)"));
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(x1, y1, rEnv, 0, 2 * Math.PI);
      ctx.fill();

      // hot core of the giant
      ctx.fillStyle = "#fff6e8";
      ctx.beginPath();
      ctx.arc(x1, y1, 3, 0, 2 * Math.PI);
      ctx.fill();

      // companion inside, with a trailing drag arc
      ctx.save();
      ctx.strokeStyle = "rgba(255,255,255,0.35)";
      ctx.lineWidth = 2;
      const rOrbit = Math.hypot(x2 - cx, (y2 - cy) / 0.42);
      const a2now = Math.atan2((y2 - cy) / 0.42, x2 - cx);
      ctx.beginPath();
      for (let k = 0; k <= 20; k++) {
        const th = a2now - (k / 20) * 1.2;
        const xx = cx + rOrbit * Math.cos(th);
        const yy = cy + rOrbit * Math.sin(th) * 0.42;
        if (k === 0) ctx.moveTo(xx, yy);
        else ctx.lineTo(xx, yy);
      }
      ctx.stroke();
      ctx.restore();
      if (s.compact2) this._drawCompact(x2, y2, s);
      else this._drawStar(x2, y2, Math.max(s.r2 || 0.5, 0.5), s.t2, 0, 0, null, s);
    } else {
      // depth ordering: draw the star further "behind" first
      const star1First = y1 <= y2;
      const one = () =>
        this._drawStar(x1, y1, s.r1, s.t1, s.mdot1, s.windHalo, { x: x2, y: y2, rl: s.rl1, fill: s.fill1 }, s);
      const two = () => {
        if (s.compact2) this._drawCompact(x2, y2, s);
        else if (isFinite(s.r2) && s.r2 > 0) {
          this._drawStar(x2, y2, s.r2, s.t2, 0, 0, { x: x1, y: y1, rl: s.rl2, fill: s.fill2 }, s);
        }
      };
      if (star1First) {
        one();
        two();
      } else {
        two();
        one();
      }
    }

    // RLOF stream: particles from L1 towards the companion (not during engulfment)
    if (s.rlofActive && !engulfed && this.particles.length) {
      const q = (s.m2 || 1) / (s.m1 || 1);
      let f = 0.5 - 0.227 * Math.log10(q); // Plavec–Kratochvíl L1 position
      f = Math.min(Math.max(f, 0.15), 0.85);
      const lx = x1 + (x2 - x1) * f;
      const ly = y1 + (y2 - y1) * f;
      ctx.save();
      for (const p of this.particles) {
        const px_ = lx + (x2 - lx) * p.t + (y2 - y1) * p.jitter * Math.sin(p.t * Math.PI);
        const py_ = ly + (y2 - ly) * p.t - (x2 - x1) * p.jitter * Math.sin(p.t * Math.PI);
        ctx.globalAlpha = 0.75 * (1 - p.t * 0.6);
        ctx.fillStyle = teffToRgb(s.t1);
        ctx.beginPath();
        ctx.arc(px_, py_, p.size, 0, 2 * Math.PI);
        ctx.fill();
      }
      ctx.restore();
    }

    // centre of mass
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.35)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cx - 4, cy);
    ctx.lineTo(cx + 4, cy);
    ctx.moveTo(cx, cy - 4);
    ctx.lineTo(cx, cy + 4);
    ctx.stroke();
    ctx.restore();

    // mass labels
    ctx.save();
    ctx.fillStyle = "rgba(255,255,255,0.75)";
    ctx.font = "11px ui-monospace, monospace";
    ctx.textAlign = "center";
    if (isFinite(s.m1)) ctx.fillText(`${s.m1.toFixed(1)} M☉`, x1, y1 + px(s.r1) + 14);
    if (isFinite(s.m2)) ctx.fillText(`${s.m2.toFixed(1)} M☉`, x2, y2 + px(Math.max(s.r2 || 0, 0.5)) + 14);
    ctx.restore();

    this._drawScaleBar();
  }

  _drawStar(x, y, rRsun, teff, mdot, windHalo, roche, s) {
    const ctx = this.ctx;
    const r = Math.max(rRsun * this.scale, 1.2);
    const colour = teffToRgb(teff);

    // wind halo
    if (windHalo > 0) {
      const rw = r * (1.8 + 1.4 * windHalo);
      const grad = ctx.createRadialGradient(x, y, r * 0.9, x, y, rw);
      grad.addColorStop(0, colour.replace("rgb", "rgba").replace(")", `,${0.28 * windHalo})`));
      grad.addColorStop(1, colour.replace("rgb", "rgba").replace(")", ",0)"));
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(x, y, rw, 0, 2 * Math.PI);
      ctx.fill();
    }

    // Roche teardrop distortion when close to filling the lobe
    const fill = roche && isFinite(roche.fill) ? roche.fill : 0;
    ctx.save();
    if (roche && fill > 0.82) {
      const towards = Math.atan2(roche.y - y, roche.x - x);
      const k = Math.min((fill - 0.82) / 0.22, 1) * 0.55;
      ctx.translate(x, y);
      ctx.rotate(towards);
      ctx.beginPath();
      const steps = 44;
      for (let i = 0; i <= steps; i++) {
        const th = (i / steps) * 2 * Math.PI;
        const stretch = 1 + k * Math.pow(Math.max(Math.cos(th), 0), 2.4);
        const rr = r * stretch;
        const xx = rr * Math.cos(th);
        const yy = r * Math.sin(th) * (1 - 0.12 * k);
        if (i === 0) ctx.moveTo(xx, yy);
        else ctx.lineTo(xx, yy);
      }
      ctx.closePath();
      ctx.fillStyle = this._sphereFill(-r * 0.18, -r * 0.18, r * (1 + k), colour);
      ctx.fill();
      ctx.restore();
      return;
    }
    ctx.restore();

    ctx.fillStyle = this._sphereFill(x, y, r, colour);
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fill();
  }

  /** Soft limb-darkening, no specular highlight — a matte sphere. */
  _sphereFill(x, y, r, colour) {
    const lit = this._mix(colour, [255, 255, 255], 0.16);
    const limb = this._darken(colour, 0.7);
    const grad = this.ctx.createRadialGradient(
      x - r * 0.18, y - r * 0.2, r * 0.12,
      x, y, r,
    );
    grad.addColorStop(0, lit);
    grad.addColorStop(0.58, colour);
    grad.addColorStop(1, limb);
    return grad;
  }

  _drawCompact(x, y, s) {
    const ctx = this.ctx;
    const r = 2.6;
    if (s.rlofActive) {
      // accretion glow
      const rg = 14;
      const grad = ctx.createRadialGradient(x, y, r, x, y, rg);
      grad.addColorStop(0, "rgba(190,225,255,0.85)");
      grad.addColorStop(1, "rgba(190,225,255,0)");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(x, y, rg, 0, 2 * Math.PI);
      ctx.fill();
    }
    ctx.fillStyle = "#eef4ff";
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fill();
  }

  _darken(rgb, factor) {
    const m = rgb.match(/\d+/g).map(Number);
    return `rgb(${m.map((v) => Math.round(v * factor)).join(",")})`;
  }

  _mix(rgb, other, t) {
    const a = rgb.match(/\d+/g).map(Number);
    return `rgb(${a.map((v, i) => Math.round(v + (other[i] - v) * t)).join(",")})`;
  }

  _drawScaleBar() {
    const ctx = this.ctx;
    // pick a nice round R☉ length that maps to 40–120 px
    const targets = [0.1, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000];
    let best = targets[0];
    for (const t of targets) {
      const px = t * this.scale;
      if (px >= 34 && px <= 130) {
        best = t;
        break;
      }
      if (px < 34) best = t;
    }
    const lenPx = best * this.scale;
    if (!isFinite(lenPx) || lenPx <= 4) return;
    const x0 = 14;
    const y0 = this.height - 14;
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.9)";
    ctx.shadowBlur = 3;
    ctx.strokeStyle = "rgba(255,255,255,0.75)";
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x0 + lenPx, y0);
    ctx.moveTo(x0, y0 - 4);
    ctx.lineTo(x0, y0 + 4);
    ctx.moveTo(x0 + lenPx, y0 - 4);
    ctx.lineTo(x0 + lenPx, y0 + 4);
    ctx.stroke();
    ctx.font = "10.5px ui-monospace, monospace";
    ctx.fillText(`${best} R☉`, x0 + 4, y0 - 6);
    ctx.restore();
  }
}

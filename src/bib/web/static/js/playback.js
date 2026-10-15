/* Shared playback clock for bib explorers.
 *
 * A PlaybackClock owns a normalised time t in [0, 1] and advances it with
 * requestAnimationFrame while playing. Pages map t onto their own domain
 * (log-age of a population, or the age span of a stellar track) and re-render
 * on every tick. One clock can drive several linked views (HRD marker, SED
 * frame, binary visualiser) so everything stays in sync.
 */
"use strict";

export class PlaybackClock {
  /**
   * @param {Object} opts
   * @param {number} [opts.duration=20]  seconds for one full sweep at speed 1
   * @param {boolean} [opts.loop=false]
   * @param {(t: number) => void} opts.onTick  called with t in [0,1]
   * @param {(playing: boolean) => void} [opts.onPlayState]
   */
  constructor({ duration = 20, loop = false, onTick, onPlayState }) {
    this.duration = duration;
    this.loop = loop;
    this.onTick = onTick;
    this.onPlayState = onPlayState || (() => {});
    this.t = 0;
    this.speed = 1;
    this.playing = false;
    this._raf = null;
    this._last = null;
  }

  _frame = (now) => {
    if (!this.playing) return;
    if (this._last !== null) {
      const dt = (now - this._last) / 1000;
      this.t += (dt / this.duration) * this.speed;
      if (this.t >= 1) {
        if (this.loop) {
          this.t %= 1;
        } else {
          this.t = 1;
          this.pause();
        }
      }
      this.onTick(this.t);
    }
    this._last = now;
    if (this.playing) this._raf = requestAnimationFrame(this._frame);
  };

  play() {
    if (this.playing) return;
    if (this.t >= 1) this.t = 0; // replay from the start
    this.playing = true;
    this._last = null;
    this.onPlayState(true);
    this._raf = requestAnimationFrame(this._frame);
  }

  pause() {
    this.playing = false;
    this._last = null;
    if (this._raf) cancelAnimationFrame(this._raf);
    this.onPlayState(false);
  }

  toggle() {
    this.playing ? this.pause() : this.play();
  }

  rewind() {
    this.t = 0;
    this.onTick(this.t);
  }

  scrub(t) {
    this.t = Math.min(1, Math.max(0, t));
    this.onTick(this.t);
  }

  setSpeed(s) {
    this.speed = s;
  }
}

/**
 * Wire a playback bar to a clock. Expects the container to hold elements with
 * data-role attributes: play, rewind, scrub (input[type=range] 0..1000),
 * speed (input[type=range]), speed-out, readout.
 *
 * @param {HTMLElement} el
 * @param {PlaybackClock} clock
 * @param {(t: number) => string} format  readout text for a given t
 */
/** Paint the blue track fill from a range input's min/max/value. */
export function syncRangeFill(el) {
  if (!el) return;
  const min = Number(el.min);
  const max = Number(el.max);
  const value = Number(el.value);
  const span = max - min || 1;
  el.style.setProperty("--fill", `${((value - min) / span) * 100}%`);
}

export function syncAllRangeFills(root = document) {
  root.querySelectorAll('input[type="range"]').forEach(syncRangeFill);
}

export function attachPlaybar(el, clock, format) {
  const $ = (role) => el.querySelector(`[data-role="${role}"]`);
  const play = $("play");
  const rewind = $("rewind");
  const scrub = $("scrub");
  const speed = $("speed");
  const speedOut = $("speed-out");
  const readout = $("readout");

  const paint = (t) => {
    if (scrub) {
      scrub.value = String(Math.round(t * 1000));
      scrub.style.setProperty("--fill", `${t * 100}%`);
    }
    if (readout) readout.textContent = format(t);
  };

  play.addEventListener("click", () => clock.toggle());
  if (rewind) rewind.addEventListener("click", () => clock.rewind());
  if (scrub) {
    scrub.addEventListener("input", () => {
      clock.pause();
      clock.scrub(Number(scrub.value) / 1000);
    });
  }
  if (speed) {
    const applySpeed = () => {
      const s = Math.pow(2, Number(speed.value)); // slider is log2(speed)
      clock.setSpeed(s);
      syncRangeFill(speed);
      if (speedOut) speedOut.textContent = `${s >= 1 ? s.toFixed(s >= 4 ? 0 : 1) : s.toFixed(2)}×`;
    };
    speed.addEventListener("input", applySpeed);
    applySpeed();
  }

  const prevTick = clock.onTick;
  clock.onTick = (t) => {
    paint(t);
    prevTick(t);
  };
  const prevPlay = clock.onPlayState;
  clock.onPlayState = (playing) => {
    play.textContent = playing ? "⏸" : "▶";
    play.title = playing ? "Pause" : "Play";
    prevPlay(playing);
  };
  paint(clock.t);
}

/** Linear interpolation helpers shared by the explorers. */
export function lerp(a, b, w) {
  return a + (b - a) * w;
}

/**
 * Locate t in a sorted array; returns [i0, i1, w] such that
 * value ≈ lerp(arr[i0], arr[i1], w).
 */
export function locate(arr, value) {
  const n = arr.length;
  if (value <= arr[0]) return [0, 0, 0];
  if (value >= arr[n - 1]) return [n - 1, n - 1, 0];
  let lo = 0,
    hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (arr[mid] <= value) lo = mid;
    else hi = mid;
  }
  const w = (value - arr[lo]) / (arr[hi] - arr[lo] || 1);
  return [lo, hi, w];
}

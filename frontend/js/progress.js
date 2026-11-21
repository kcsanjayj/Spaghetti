// Smooth download progress: the displayed number glides toward the real one, so coarse updates never look jumpy.
const bar = document.querySelector("#dlbar");
export const globalBar = (pct) => {
  bar.classList.toggle("on", pct !== null);
  if (pct !== null) bar.firstElementChild.style.transform = `scaleX(${Math.min(pct, 100) / 100})`;
};
const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export class Progress {
  constructor() { this.target = 0; this.shown = 0; this.phase = 0; this.text = ""; this.t0 = performance.now(); this.els = []; this.raf = 0; this.determinate = false; this.ready = false; this.last = {}; }
  attach(els) { this.els = els; this.last = {}; this.start(); }
  set(pct, phase, text) {
    if (pct != null) { this.target = Math.max(this.target, pct); this.determinate = true; }
    if (phase != null) this.phase = Math.max(this.phase, phase);
    if (text != null) this.text = text;
    this.start();
  }
  finish() { this.target = 100; this.phase = 3; this.ready = true; this.determinate = true; this.start(); }
  start() { if (!this.raf && this.els.length) this.raf = requestAnimationFrame(() => this.tick()); }
  stop() { cancelAnimationFrame(this.raf); this.raf = 0; globalBar(null); }
  tick() {
    this.raf = 0;
    const d = this.target - this.shown;
    this.shown = Math.abs(d) < 0.05 ? this.target : this.shown + d * 0.12;
    this.paint();
    if (!this.ready || this.shown < 100) this.raf = requestAnimationFrame(() => this.tick());
  }
  paint() {
    const secs = (performance.now() - this.t0) / 1000, p = this.shown;
    const rate = p > 2 ? p / secs : 0, eta = rate ? (100 - p) / rate : null;
    const v = { pct: this.determinate ? `${Math.round(p)}%` : "…", phase: ["Preparing", "Downloading", "Verifying", "Ready"][this.phase], meta: `${fmt(secs)} elapsed${eta !== null && !this.ready ? ` · about ${fmt(eta)} left` : ""}`, text: this.text };
    for (const el of this.els) {
      if (!el.isConnected) continue;
      const set = (sel, key, val) => { if (this.last[key] !== val) { const n = el.querySelector(sel); if (n) n.textContent = val; } };
      set(".dl-pct", "pct", v.pct); set(".dl-phase", "phase", v.phase); set(".dl-t", "meta", v.meta); set(".dl-text", "text", v.text);
      el.querySelector(".strand").classList.toggle("ind", !this.determinate);
      el.querySelector(".fill").style.strokeDashoffset = this.determinate ? 100 - p : 100;
      el.querySelectorAll(".steps span").forEach((s, i) => s.classList.toggle("on", i <= this.phase));
      el.classList.toggle("ready", this.ready);
    }
    this.last = { pct: v.pct, phase: v.phase, meta: v.meta, text: v.text };
    globalBar(this.determinate ? p : 0);
  }
}

export const downloadPanel = () => `<div class="dl"><div class="dl-top"><span class="dl-pct">…</span><span class="dl-phase">Preparing</span></div>
  <svg class="strand ind" viewBox="0 0 300 26" preserveAspectRatio="none" aria-hidden="true"><path class="track" pathLength="100" d="M2 13C27 1 52 25 77 13S127 1 152 13 202 25 227 13 277 1 298 13"/><path class="fill" pathLength="100" d="M2 13C27 1 52 25 77 13S127 1 152 13 202 25 227 13 277 1 298 13"/></svg>
  <div class="steps"><span class="on">Prepare</span><span>Download</span><span>Verify</span><span>Ready</span></div>
  <div class="dl-meta"><span><span class="dl-t">0:00 elapsed</span><br><span class="dl-text"></span></span><button class="btn" data-cancel>Cancel</button></div></div>`;

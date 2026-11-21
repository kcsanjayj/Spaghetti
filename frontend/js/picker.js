// The model menu: switch Ollama model, start/install Ollama, download small models, toggle careful mode.
import { api, stream, BASE } from "./api.js";
import { Progress, downloadPanel } from "./progress.js";
import { icon } from "./icons.js";
import * as store from "./store.js";
import { $, $$, escapeHtml, setHTML, toast } from "./util.js";

let data = null, isOpen = false, busy = false;
const active = new Map(); // tag -> { prog, abort }
const PHASE = [/manifest/i, /pulling/i, /verif/i, /writing|success/i];
const nameOf = (tag) => (tag === "mock" ? "Demo model" : data?.catalog.find((m) => m.tag === tag)?.label || tag);

export function paint() {
  const s = store.get();
  $("#modelName").textContent = s.model ? nameOf(s.model) : "Choose a model";
  $("#modelDot").classList.toggle("on", !!s.model && data?.state === "running");
}

export async function load() { try { data = await api.models(); } catch { data = null; } paint(); return data; }

/** First run made easy: use a saved model if it is still installed, else the best installed one, else open the menu. */
export async function ensureModel() {
  await load();
  if (!data) return;
  const have = data.installed, s = store.get();
  const pick = have.includes(s.model) ? s.model : have.includes(data.recommended) ? data.recommended : have.find((t) => data.catalog.some((m) => m.tag === t)) || have[0];
  if (pick) { store.save({ model: pick }); paint(); api.warm(pick); } else if (!s.model) setTimeout(() => open(), 400); // only nag on first run
}

function banner() {
  if (!data) return `<div class="banner"><b>Can't reach Spaghetti</b><span class="mut sm">Start it with <code>python run.py${BASE ? ` --allow-origin ${location.origin}` : ""}</code>, then reopen this menu.</span></div>`;
  if (data.state === "missing") return `<div class="banner"><b>Ollama isn't installed</b><span class="mut sm">One click installs it, starts it and downloads <b>${escapeHtml(data.recommended)}</b>. ${data.hardware.os === "windows" ? "Double-click the file." : "Run: <code>bash spaghetti-setup.sh</code>"} Then press Re-check.</span>
    <div class="row"><a class="btn primary" href="${BASE}/api/setup-script?os=${data.hardware.os}&models=${encodeURIComponent(data.recommended)}" download>${icon("down")} Setup script</a><a class="btn" href="https://ollama.com/download" target="_blank" rel="noopener noreferrer">Install manually</a><button class="btn" data-recheck>${icon("refresh")} Re-check</button></div></div>`;
  if (data.state === "installed") return `<div class="banner"><b>Ollama isn't running</b><span class="mut sm">Start it to use your models.</span><div class="row"><button class="btn primary" data-start>${icon("play")} Start Ollama</button><button class="btn" data-recheck>${icon("refresh")} Re-check</button></div></div>`;
  return "";
}

function render() {
  const s = store.get();
  const mine = (data?.installed || []).map((t) => `<li class="mrow ${t === s.model ? "sel" : ""}" data-tag="${escapeHtml(t)}"><button class="pickrow"><span class="radio"></span><b>${escapeHtml(nameOf(t))}</b><span></span><small>${t === "mock" ? "Offline mock, not an AI" : escapeHtml(t)}</small></button></li>`).join("");
  const add = (data?.catalog || []).filter((m) => !m.installed).map((m) => {
    const run = active.get(m.tag), can = data.state === "running" && m.fit !== "no";
    return `<li class="mrow" data-tag="${m.tag}"><span></span><b>${escapeHtml(m.label)}</b>${run ? "<span></span>" : `<button class="btn" data-get ${can ? "" : "disabled"}>${icon("down")} ${m.size_gb} GB</button>`}
      <div class="chips">${m.recommended ? '<span class="chip solid">Recommended</span>' : ""}<span class="chip">${{ comfortable: "Fits well", tight: "Tight fit", no: "Too big" }[m.fit]}</span>${m.reasoning ? '<span class="chip">reasoning</span>' : ""}</div>
      <small>${escapeHtml(m.blurb)}</small>${run ? downloadPanel() : ""}</li>`;
  }).join("");
  setHTML($("#sheet"), `${banner()}<h2>On this device</h2><ul class="mlist">${mine || `<li class="mut sm" style="padding:.4rem .7rem">${data?.state === "running" ? "No models yet. Download one below." : "Nothing available yet."}</li>`}</ul>
    <h2>Add a small model</h2><ul class="mlist">${add || `<li class="mut sm" style="padding:.4rem .7rem">All menu models are installed.</li>`}</ul>
    <label class="switch"><b>Careful mode</b><input type="checkbox" id="careful" ${s.careful ? "checked" : ""}><i></i><small>An extra AI check of each answer, with one retry. Slower, more accurate.</small></label>
    ${data ? `<p class="mut sm" style="margin-top:1rem">Your device: ${data.hardware.ram_gb} GB RAM · ${data.hardware.cores} cores${data.hardware.gpu ? " · " + escapeHtml(data.hardware.gpu) : ""}</p>` : ""}`);
  for (const [tag, run] of active) run.prog.attach($$(`#sheet .mrow[data-tag="${CSS.escape(tag)}"] .dl`));
}

export async function open() { if (isOpen) return; isOpen = true; setOpen(true); await load(); render(); }
export function close() { if (!isOpen) return; isOpen = false; setOpen(false); }
function setOpen(on) {
  $("#sheet").classList.toggle("open", on); $("#sheetScrim").classList.toggle("on", on);
  $("#modelBtn").setAttribute("aria-expanded", on); $("#sheet").setAttribute("aria-hidden", !on);
}

function select(tag) {
  store.save({ model: tag }); paint(); api.warm(tag); toast(`Using ${nameOf(tag)}`); close();
}

async function download(tag) {
  const prog = new Progress(), abort = new AbortController();
  active.set(tag, { prog, abort }); render();
  try {
    await stream("/api/models/pull", { model: tag }, (ev) => {
      if (ev.type === "progress") prog.set(ev.percent, Math.max(0, PHASE.findIndex((r) => r.test(ev.status))), ev.status);
      else if (ev.type === "error") throw new Error(ev.message);
    }, abort.signal);
    prog.finish();
    await new Promise((r) => setTimeout(r, 800));
    prog.stop(); active.delete(tag); await load(); select(tag);
  } catch (err) {
    prog.stop(); active.delete(tag);
    if (err.name !== "AbortError") toast(`${err.message}`);
    await load(); render();
  }
}

export function init() {
  paint();
  $("#modelBtn").addEventListener("click", () => (isOpen ? close() : open()));
  $("#sheetScrim").addEventListener("click", close);
  addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  addEventListener("pointerdown", (e) => { if (isOpen && innerWidth > 760 && !e.target.closest(".pickwrap")) close(); });
  $("#sheet").addEventListener("change", (e) => { if (e.target.id === "careful") store.save({ careful: e.target.checked }); });
  $("#sheet").addEventListener("click", async (e) => {
    const t = e.target, row = t.closest(".mrow");
    if (t.closest("[data-recheck]")) { toast("Checking…"); await load(); return render(); }
    if (t.closest("[data-start]")) { const b = t.closest("button"); b.disabled = true; b.textContent = "Starting…"; await api.startOllama().catch(() => {}); await load(); return render(); }
    if (!row) return;
    if (t.closest("[data-cancel]")) return active.get(row.dataset.tag)?.abort.abort();
    if (t.closest("[data-get]")) return download(row.dataset.tag);
    if (t.closest(".pickrow")) select(row.dataset.tag);
  });
}

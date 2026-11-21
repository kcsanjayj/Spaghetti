// Chat: live token streaming, five-cook progress, saved conversations, stop / regenerate / copy, shortcuts.
import { api, stream } from "./api.js";
import { $, $$, debounce, escapeHtml, renderAnswer, setHTML, toast } from "./util.js";
import { icon } from "./icons.js";
import * as store from "./store.js";
import * as chats from "./chats.js";
import * as docs from "./docs.js";
import * as picker from "./picker.js";

const COOKS = [["head_chef", "Plan", "Reading the order"], ["sous_chef", "Fetch", "Fetching ingredients from your documents"], ["saucier", "Cook", "Writing your answer"], ["taster", "Taste", "Checking the answer"], ["expediter", "Serve", "Plating"]];
const STARTERS = ["Summarize my documents", "List the key points", "Explain it in simple words"];
const HELP = { ollama_down: "Ollama isn't running right now.", model_missing: "That model isn't downloaded on this device yet.", timeout: "The model took too long. A smaller one will be quicker.", no_model: "Choose a model first." };
let busy = false, abort = null, discardStoppedAnswer = false, lastQuestion = "";
const box = () => $("#messages");
const nearBottom = () => box().scrollHeight - box().scrollTop - box().clientHeight < 150;
const toBottom = (smooth = true) => requestAnimationFrame(() => box().scrollTo({ top: box().scrollHeight, behavior: smooth ? "smooth" : "auto" }));

export function init() {
  chats.load({ startFresh: true });
  renderThread();
  addEventListener("spaghetti:document-deleted", () => {
    if (busy) { discardStoppedAnswer = true; stop(); }
    renderThread();
    renderList();
  });
  const q = $("#question");
  q.addEventListener("input", () => { q.style.height = "auto"; q.style.height = Math.min(q.scrollHeight, 160) + "px"; });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#askForm").requestSubmit(); } });
  $("#askForm").addEventListener("submit", (e) => { e.preventDefault(); if (busy) return stop(); const v = q.value.trim(); if (v) order(v); });
  $("#newBtn").addEventListener("click", newChat);
  $("#thread").addEventListener("click", async (e) => {
    const c = e.target.closest("[data-copy-code]");
    if (c) { await navigator.clipboard.writeText(c.parentElement.querySelector("code").textContent).catch(() => {}); c.textContent = "Copied"; setTimeout(() => (c.textContent = "Copy"), 1500); }
  });
  box().addEventListener("scroll", debounce(() => $("#jumpBtn").classList.toggle("show", !nearBottom()), 60), { passive: true });
  $("#jumpBtn").addEventListener("click", () => toBottom());
  initDrawer();
  addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA/.test(document.activeElement.tagName);
    if (e.key === "/" && !typing) { e.preventDefault(); q.focus(); }
    if (e.key === "Escape") { if ($("#drawer").classList.contains("open")) toggleDrawer(false); else if (busy) stop(); }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); newChat(); }
  });
}

/* ---------- thread ---------- */
function empty() {
  $("#thread").innerHTML = `<div class="empty"><h1 style="--i:0">Hello.<span>What would you like to know?</span></h1><p class="lead" style="--i:1">Ask about your own documents. Five cooks plan, fetch, cook, taste and serve every answer, entirely on your device.</p>
    <div class="starters" style="--i:2">${STARTERS.map((t) => `<button data-ask="${t}"><b>${t}</b><small>Uses your documents</small></button>`).join("")}</div>
    <p class="hint" style="--i:3"><kbd>/</kbd> focus &nbsp; <kbd>Enter</kbd> send &nbsp; <kbd>Esc</kbd> stop &nbsp; <kbd>Ctrl</kbd>+<kbd>K</kbd> new chat</p></div>`;
  $$("#thread [data-ask]").forEach((b) => b.addEventListener("click", () => { if (!docs.count()) return toast("Add a document first with the paperclip."); order(b.dataset.ask); }));
}
function renderThread() {
  const c = chats.current();
  $("#thread").innerHTML = "";
  if (!c.messages.length) return empty();
  c.messages.forEach((m, i) => (m.role === "user" ? bubble("user", escapeHtml(m.content)) : serve(m.ev, { quiet: true, last: i === c.messages.length - 1 })));
  toBottom(false);
}
function bubble(cls, html) {
  const near = nearBottom() || cls.includes("user");
  $("#thread .empty")?.remove();
  const el = document.createElement("div");
  el.className = `msg ${cls}`; el.innerHTML = html;
  $("#thread").appendChild(el);
  if (near) toBottom();
  return el;
}
function setBusy(on) { busy = on; const b = $("#sendBtn"); b.classList.toggle("stop", on); b.setAttribute("aria-label", on ? "Stop" : "Send"); b.innerHTML = icon(on ? "stop" : "arrow"); }

/* ---------- ordering ---------- */
function stop() { abort?.abort(); }

async function order(question, { regen = false } = {}) {
  const s = store.get();
  if (busy || !question) return;
  if (!s.model) { toast("Choose a model first."); return picker.open(); }
  discardStoppedAnswer = false;
  const past = chats.current().messages.slice(-6).map(({ role, content }) => ({ role, content }));
  lastQuestion = question; abort = new AbortController();
  if (!regen) { chats.add({ role: "user", content: question }); bubble("user", escapeHtml(question)); }
  $("#question").value = ""; $("#question").style.height = "auto";
  $$("#thread .meta [data-regen]").forEach((b) => b.remove());
  setBusy(true);
  const el = bubble("bot streaming", `<div class="working"><div class="wave"><i></i><i></i><i></i><i></i></div><div><b class="st">Starting the kitchen</b><br><small class="mut sb"></small><ol class="mini">${COOKS.map(([id]) => `<li data-cook="${id}"></li>`).join("")}</ol></div></div><div class="think"></div><div class="body"></div>`);
  const body = $(".body", el), think = $(".think", el);
  let ans = "", thoughts = "", raf = 0, thinkEl = null, finished = false;
  const paint = () => { raf = 0; const near = nearBottom(); body.innerHTML = renderAnswer((ans.match(/\*\*/g) || []).length % 2 ? ans + "**" : ans); if (near) box().scrollTop = box().scrollHeight; };
  const mark = (id, st) => { const li = $(`.mini [data-cook="${id}"]`, el); li?.classList.toggle("active", st === "active"); li?.classList.toggle("done", st === "done"); };
  try {
    await stream("/api/ask", { question, model: s.model, careful: s.careful, history: past }, (ev) => {
      if (ev.type === "stage") {
        const cook = COOKS.find((c) => c[0] === ev.cook);
        if (ev.status === "start") { mark(ev.cook, "active"); $(".st", el).textContent = cook[2]; $(".sb", el).textContent = ""; } else { mark(ev.cook, "done"); $(".sb", el).textContent = `${cook[1]}: ${ev.detail} · ${ev.ms} ms`; }
      } else if (ev.type === "progress") {
        $(".sb", el).textContent = ev.detail;
      } else if (ev.type === "token") {
        if (ev.kind === "think") {
          thoughts += ev.text;
          if (!thinkEl) { think.innerHTML = `<details open><summary>Thinking…</summary><div class="src thought"></div></details>`; thinkEl = $("details", think); }
          $(".thought", think).textContent = thoughts;
        } else { if (thinkEl && !ans) { thinkEl.open = false; $("summary", thinkEl).textContent = "Thought process"; } ans += ev.text; if (!raf) raf = requestAnimationFrame(paint); }
      } else if (ev.type === "reset") { ans = ""; thoughts = ""; body.innerHTML = ""; think.innerHTML = ""; thinkEl = null; }
      else if (ev.type === "final") { finished = true; cancelAnimationFrame(raf); chats.add({ role: "assistant", content: ev.answer, ev }); el.remove(); serve(ev, { last: true }); }
      else if (ev.type === "error") { finished = true; cancelAnimationFrame(raf); el.remove(); fail(ev.message, ev.code); }
    }, abort.signal);
  } catch (err) {
    cancelAnimationFrame(raf);
    if (!finished) {
      el.remove();
      if (err.name === "AbortError" && ans && !discardStoppedAnswer) { const ev = { answer: ans, thoughts, sources: [], stages: [], mode: "stopped", score: null, attempts: 1, total_ms: 0 }; chats.add({ role: "assistant", content: ans, ev }); serve(ev, { last: true }); }
      else if (err.name === "AbortError") bubble("bot", `<p class="mut sm">${discardStoppedAnswer ? "Stopped because a document was deleted." : "Stopped."}</p>`);
      else fail(err.message, "failed");
    }
  }
  discardStoppedAnswer = false;
  setBusy(false); $("#question").focus();
}
function newChat() { if (busy) stop(); chats.create(); renderThread(); toggleDrawer(false); $("#question").focus(); }

function serve(ev, { quiet = false, last = false } = {}) {
  const chips = [`<span class="chip">${ev.mode}</span>`];
  if (ev.score !== null) chips.push(`<span class="chip ${ev.score >= 7 ? "solid" : ""}">${ev.careful ? "taste" : "overlap"} ${ev.score}/10</span>`);
  if (ev.attempts > 1) chips.push(`<span class="chip">retried (${ev.attempts})</span>`);
  if (ev.tok_s) chips.push(`<span class="chip">≈ ${ev.tok_s} tok/s</span>`);
  if (ev.total_ms) chips.push(`<span class="chip">${(ev.total_ms / 1000).toFixed(1)}s</span>`);
  chips.push(`<button type="button" class="chip" data-copy>${icon("copy")} Copy</button>`);
  if (last) chips.push(`<button type="button" class="chip" data-regen>${icon("refresh")} Regenerate</button>`);
  const thoughts = ev.thoughts ? `<details><summary>Thought process</summary><div class="src thought">${escapeHtml(ev.thoughts)}</div></details>` : "";
  const sources = ev.sources.length ? `<details><summary>${ev.sources.length} source${ev.sources.length > 1 ? "s" : ""}</summary>${ev.sources.map((x) => `<div class="src"><b>[${x.n}] ${escapeHtml(x.doc)}</b><br>${escapeHtml(x.preview)}…</div>`).join("")}</details>` : "";
  const log = ev.stages.length ? `<details><summary>Kitchen log</summary>${ev.stages.map((x) => `<div class="src">${escapeHtml(x.cook.replace("_", " "))}: ${escapeHtml(x.detail)} (${x.ms} ms)</div>`).join("")}</details>` : "";
  const card = bubble("bot", `<div class="body">${renderAnswer(ev.answer)}</div><div class="meta">${chips.join("")}</div>${thoughts}${sources}${log}`);
  if (quiet) card.style.animation = "none";
  card.querySelector("[data-copy]").addEventListener("click", async (e) => { const b = e.currentTarget; try { await navigator.clipboard.writeText(ev.answer); b.innerHTML = `${icon("check")} Copied`; } catch { b.textContent = "Select and copy"; } });
  card.querySelector("[data-regen]")?.addEventListener("click", () => { chats.dropLastAnswer(); card.remove(); order(lastQuestion || chats.current().messages.at(-1)?.content, { regen: true }); });
}

function fail(message, code) {
  const el = bubble("bot error", `<h3>Something stopped the kitchen</h3><p class="mut">${escapeHtml(HELP[code] || message)}</p><div class="row actions"></div>`);
  const add = (text, fn, primary) => { const b = document.createElement("button"); b.className = "btn" + (primary ? " primary" : ""); b.textContent = text; b.addEventListener("click", fn); el.querySelector(".actions").appendChild(b); };
  if (code === "ollama_down") add("Start Ollama and retry", async (e) => {
    e.currentTarget.disabled = true; e.currentTarget.textContent = "Starting…";
    const st = await api.startOllama().catch(() => ({ state: "missing" }));
    if (st.state === "running") { el.remove(); picker.load(); order(lastQuestion, { regen: true }); } else { e.currentTarget.textContent = "Could not start it"; picker.open(); }
  }, true);
  else if (code !== "model_missing" && code !== "no_model" && lastQuestion) add("Try again", () => { el.remove(); order(lastQuestion, { regen: true }); }, true);
  add("Open model menu", () => picker.open(), code === "model_missing" || code === "no_model");
}

/* ---------- history drawer ---------- */
function renderList() {
  const cur = chats.current().id;
  setHTML($("#chatList"), chats.list().filter((c) => c.messages.length).map((c) => `<li class="${c.id === cur ? "on" : ""}" data-id="${c.id}"><button class="t">${escapeHtml(c.title)}</button><button class="x" aria-label="Delete chat" data-del>${icon("trash")}</button></li>`).join("") || `<li><span class="mut sm" style="padding:.6rem .8rem">No conversations yet.</span></li>`);
}
function toggleDrawer(open) { $("#drawer").classList.toggle("open", open); if (open) renderList(); }
function initDrawer() {
  $("#historyBtn").addEventListener("click", () => toggleDrawer(true));
  $("#scrim").addEventListener("click", () => toggleDrawer(false));
  $("#newChat").addEventListener("click", newChat);
  $("#chatList").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-id]"); if (!li) return;
    if (e.target.closest("[data-del]")) { chats.remove(li.dataset.id); renderThread(); renderList(); return; }
    chats.select(li.dataset.id); renderThread(); toggleDrawer(false);
  });
}

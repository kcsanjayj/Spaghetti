// Small helpers. No framework: just the DOM.
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Small, safe markdown: everything is escaped first, then **bold**, *italic*, `code`, links, headings, lists, quotes, ``` fences. */
export function renderAnswer(text) {
  const inline = (raw) =>
    escapeHtml(raw)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>")
      .replace(/\[(\d+)\]/g, '<span class="cite">$1</span>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  const out = [];
  let list = null, quote = false, fence = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } if (quote) { out.push("</blockquote>"); quote = false; } };
  for (const line of text.split("\n")) {
    const f = line.match(/^```(\w*)/);
    if (fence) { if (f) { out.push(`<div class="code${fence.lang ? " has-lang" : ""}">${fence.lang ? `<span class="lang">${escapeHtml(fence.lang)}</span>` : ""}<button type="button" class="chip" data-copy-code>Copy</button><pre><code>${escapeHtml(fence.lines.join("\n"))}</code></pre></div>`); fence = null; } else fence.lines.push(line); continue; }
    if (f) { close(); fence = { lang: f[1], lines: [] }; continue; }
    const li = line.match(/^\s*([-*]|\d+\.)\s+(.*)/);
    if (li) { const tag = /\d/.test(li[1]) ? "ol" : "ul"; if (list !== tag) { close(); out.push(`<${tag}>`); list = tag; } out.push(`<li>${inline(li[2])}</li>`); continue; }
    const q = line.match(/^>\s?(.*)/);
    if (q) { if (list) close(); if (!quote) { out.push("<blockquote>"); quote = true; } out.push(`<p>${inline(q[1])}</p>`); continue; }
    close();
    const hd = line.match(/^(#{1,3})\s+(.*)/);
    if (hd) out.push(`<h${hd[1].length + 2}>${inline(hd[2])}</h${hd[1].length + 2}>`);
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (fence) out.push(`<div class="code"><pre><code>${escapeHtml(fence.lines.join("\n"))}</code></pre></div>`);
  close();
  return out.join("");
}

/** Replace innerHTML only when it really changed, so unchanged parts never repaint or re-animate. */
export function setHTML(el, html) { if (el.__h !== html) { el.innerHTML = html; el.__h = html; return true; } return false; }
export const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

let toastTimer;
export function toast(message) {
  const t = $("#toast");
  t.textContent = message;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

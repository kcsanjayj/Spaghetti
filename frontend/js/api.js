// The only file that talks to the server.
// Served by the Python backend itself: same origin (BASE = ""). Hosted elsewhere (e.g. Cloudflare Pages): talk to the
// user's own local backend, http://127.0.0.1:8000 by default, or ?api=<url> once (remembered).
const asked = new URLSearchParams(location.search).get("api");
if (asked) { try { localStorage.setItem("spaghetti.api", asked); } catch { /* private mode */ } }
const isLocal = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
export const BASE = (isLocal && !asked ? "" : asked || localStorage.getItem("spaghetti.api") || "http://127.0.0.1:8000").replace(/\/$/, "");
async function request(path, options = {}) {
  const res = await fetch(BASE + path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Server error ${res.status}`);
  return data;
}
const post = (path, body) => request(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  models: () => request("/api/models"),
  startOllama: () => post("/api/ollama/start", {}),
  warm: (model) => post("/api/warm", { model }).catch(() => ({})),
  pantry: () => request("/api/pantry").then((d) => d.docs),
  addDoc: (name, text, contentBase64) => post("/api/pantry", contentBase64 ? { name, content_base64: contentBase64 } : { name, text }),
  removeDoc: (id) => request(`/api/pantry/${id}`, { method: "DELETE" }),
};

/** Read a newline-delimited JSON stream and call onEvent for every line as it arrives. */
export async function stream(path, body, onEvent, signal) {
  const res = await fetch(BASE + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `Server error ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    lines.filter(Boolean).forEach((l) => onEvent(JSON.parse(l)));
  }
}

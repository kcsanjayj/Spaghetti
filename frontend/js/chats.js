// Conversations live in localStorage: [{ id, title, updated, messages: [{ role, content, ev? }] }].
const KEY = "spaghetti.chats", CUR = "spaghetti.chat.current";
let chats = [];
let currentId = "";
const uid = () => Math.random().toString(36).slice(2, 10);

export function load({ startFresh = false } = {}) {
  try { chats = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { chats = []; }
  currentId = localStorage.getItem(CUR) || "";
  const selected = chats.find((c) => c.id === currentId);
  if (!selected || (startFresh && selected.messages.length)) create();
  return current();
}
const persist = () => { try { localStorage.setItem(KEY, JSON.stringify(chats.slice(0, 30))); localStorage.setItem(CUR, currentId); } catch { /* storage full: chat keeps working in memory */ } };
export const current = () => chats.find((c) => c.id === currentId);
export const list = () => [...chats].sort((a, b) => b.updated - a.updated);
export function create() {
  const reuse = chats.find((c) => !c.messages.length); // never pile up empty chats
  const chat = reuse || { id: uid(), title: "New chat", updated: Date.now(), messages: [] };
  if (!reuse) chats.unshift(chat);
  currentId = chat.id; persist(); return chat;
}
export function select(id) { if (chats.find((c) => c.id === id)) { currentId = id; persist(); } return current(); }
export function remove(id) { chats = chats.filter((c) => c.id !== id); if (id === currentId) { currentId = ""; if (!chats.length) create(); else currentId = list()[0].id; } persist(); return current(); }
export function add(message) {
  const c = current();
  c.messages.push(message); c.updated = Date.now();
  if (c.title === "New chat" && message.role === "user") c.title = message.content.slice(0, 48);
  c.messages = c.messages.slice(-60); persist();
}
export function redactDocument(docId, docName) {
  const replacement = "This answer was redacted because it referenced a deleted document.";
  let changed = false;
  const updated = chats.map((chat) => ({
    ...chat,
    messages: chat.messages.map((message) => {
      if (message.role !== "assistant" || !message.ev?.sources?.some((source) => {
        const ids = source.ids || (source.id ? [source.id] : []);
        return ids.includes(docId) || source.doc === docName;
      })) return message;
      changed = true;
      return {
        ...message,
        content: replacement,
        ev: { ...message.ev, answer: replacement, thoughts: "", sources: [] },
      };
    }),
  }));
  if (!changed) return false;
  chats = updated;
  try {
    localStorage.setItem(KEY, JSON.stringify(updated.slice(0, 30)));
  } catch {
    throw new Error("The document was deleted, but related saved answers could not be updated in browser storage.");
  }
  return true;
}
export function dropLastAnswer() { const c = current(); if (c.messages.at(-1)?.role === "assistant") { c.messages.pop(); persist(); } }

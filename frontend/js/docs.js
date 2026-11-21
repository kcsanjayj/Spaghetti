// Documents live inside the chat: attach button, drag-and-drop, removable chips above the composer.
import { api } from "./api.js";
import * as chats from "./chats.js";
import { icon } from "./icons.js";
import { $, escapeHtml, setHTML, toast } from "./util.js";

let docs = [];
export const count = () => docs.length;

export async function refresh() {
  try { docs = await api.pantry(); } catch { docs = []; }
  setHTML($("#docChips"), docs.map((d) => `<span class="dchip" data-id="${d.id}" title="${d.chunks} chunks">${icon("file")}${escapeHtml(d.name)}<button aria-label="Remove ${escapeHtml(d.name)}">${icon("x")}</button></span>`).join(""));
}

async function add(files) {
  for (const f of files) {
    try {
      const binary = /\.(pdf|docx)$/i.test(f.name);
      if (binary) {
        const bytes = new Uint8Array(await f.arrayBuffer());
        let base64 = "";
        const chunk = 0x8000;
        for (let i = 0; i < bytes.length; i += chunk) {
          base64 += String.fromCharCode(...bytes.subarray(i, i + chunk));
        }
        await api.addDoc(f.name, "", btoa(base64));
      } else {
        await api.addDoc(f.name, await f.text());
      }
      toast(`Added ${f.name}`);
    } catch (err) { toast(err.message); }
  }
  refresh();
}

export function init() {
  refresh();
  $("#attachBtn").addEventListener("click", () => $("#fileInput").click());
  $("#fileInput").addEventListener("change", (e) => { add([...e.target.files]); e.target.value = ""; });
  $("#docChips").addEventListener("click", async (e) => {
    const id = e.target.closest(".dchip")?.dataset.id;
    if (id && e.target.closest("button")) {
      const name = docs.find((doc) => doc.id === id)?.name || "";
      try {
        await api.removeDoc(id);
      } catch (err) {
        toast(err.message);
        refresh();
        return;
      }
      let warning = "";
      try {
        chats.redactDocument(id, name);
      } catch (err) {
        warning = err.message;
      }
      dispatchEvent(new CustomEvent("spaghetti:document-deleted", { detail: { id, name } }));
      toast(warning || `Removed ${name}`);
      refresh();
    }
  });
  const zone = $("#dropzone"); let depth = 0;
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  addEventListener("dragenter", (e) => { if (hasFiles(e)) { depth++; zone.classList.add("on"); } });
  addEventListener("dragleave", (e) => { if (hasFiles(e) && --depth <= 0) { depth = 0; zone.classList.remove("on"); } });
  addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  addEventListener("drop", (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth = 0; zone.classList.remove("on"); add([...e.dataTransfer.files]); });
}

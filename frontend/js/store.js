// Two settings only: which Ollama model is active, and whether "careful mode" is on.
const KEY = "spaghetti.settings";
const state = { model: "", careful: false };
export function load() { try { Object.assign(state, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch { /* corrupted: defaults */ } return state; }
export function save(patch) { Object.assign(state, patch); try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* storage blocked */ } }
export const get = () => state;

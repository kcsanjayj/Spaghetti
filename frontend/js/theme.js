// Dark/light switch. Circular reveal via the View Transitions API; a short colour fade as the fallback.
import { icon } from "./icons.js";
const KEY = "spaghetti.theme", root = document.documentElement;
const current = () => root.dataset.theme || "dark";
const paint = (btn) => { btn.innerHTML = icon(current() === "dark" ? "sun" : "moon"); btn.setAttribute("aria-label", `Switch to ${current() === "dark" ? "light" : "dark"} mode`); document.querySelector("#themeColor")?.setAttribute("content", current() === "dark" ? "#000000" : "#ffffff"); };

export function initTheme(btn) {
  paint(btn);
  btn.addEventListener("click", (e) => {
    const next = current() === "dark" ? "light" : "dark";
    const apply = () => { root.dataset.theme = next; try { localStorage.setItem(KEY, next); } catch { /* private mode */ } paint(btn); };
    const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!document.startViewTransition || calm) {
      root.classList.add("theming"); apply(); setTimeout(() => root.classList.remove("theming"), 400); return;
    }
    const r = btn.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    document.startViewTransition(apply).ready.then(() =>
      root.animate({ clipPath: [`circle(0 at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] }, { duration: 550, easing: "cubic-bezier(.22,1,.36,1)", pseudoElement: "::view-transition-new(root)" }));
  });
}

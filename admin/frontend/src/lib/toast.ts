/**
 * Shared toast notification utility for the Hermes Admin Panel frontend.
 * Cyberpunk dark theme with slide-in/out animations.
 */

export function showToast(message: string, type: "success" | "error" = "success") {
  let container = document.getElementById("admin-toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "admin-toast-container";
    container.style.cssText =
      "position:fixed;top:4rem;right:1rem;z-index:50;display:flex;flex-direction:column;gap:0.5rem;pointer-events:none;";
    document.body.appendChild(container);
  }

  const el = document.createElement("div");
  el.style.cssText =
    "padding:10px 16px;border-radius:8px;font-size:14px;max-width:400px;word-break:break-word;font-family:'Exo 2',sans-serif;pointer-events:auto;";

  if (type === "error") {
    el.style.background = "var(--color-surface)";
    el.style.color = "var(--color-accent-pink)";
    el.style.border = "1px solid var(--color-border)";
    el.style.borderLeft = "3px solid var(--color-accent-pink)";
  } else {
    el.style.background = "var(--color-surface)";
    el.style.color = "var(--color-success)";
    el.style.border = "1px solid var(--color-border)";
    el.style.borderLeft = "3px solid var(--color-success)";
  }

  el.className = "animate-toast-in";
  el.textContent = message;
  container.appendChild(el);

  setTimeout(() => {
    el.classList.remove("animate-toast-in");
    el.classList.add("animate-toast-out");
    el.addEventListener("animationend", () => el.remove(), { once: true });
  }, 3000);
}

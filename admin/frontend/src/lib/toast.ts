/**
 * Shared toast notification utility for the Hermes Admin Panel frontend.
 * Replaces duplicated local toast() definitions across components.
 */

export function showToast(message: string, type: "success" | "error" = "success") {
  const existing = document.getElementById("admin-toast-container");
  if (!existing) {
    const container = document.createElement("div");
    container.id = "admin-toast-container";
    container.style.cssText =
      "position:fixed;top:16px;right:16px;z-index:9999;display:flex;flex-direction:column;gap:8px;";
    document.body.appendChild(container);
  }
  const container = document.getElementById("admin-toast-container")!;
  const el = document.createElement("div");
  el.style.cssText = `padding:8px 16px;border-radius:4px;font-size:14px;max-width:400px;word-break:break-word;transition:opacity 0.3s;${
    type === "error"
      ? "background:#fef2f2;color:#dc2626;border:1px solid #fecaca;"
      : "background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0;"
  }`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 300);
  }, 3000);
}

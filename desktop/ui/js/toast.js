/**
 * 桌面端底部轻提示；容器在 layout.renderShell 的 #desktop-toast-host。
 */
export function showToast(message, opts) {
  opts = opts || {};
  var type = opts.type || "info";
  var duration = opts.duration != null ? opts.duration : 3600;
  var host = document.getElementById("desktop-toast-host");
  if (!host) {
    host = document.createElement("div");
    host.id = "desktop-toast-host";
    host.className = "desktop-toast-host";
    host.setAttribute("aria-live", "polite");
    document.body.appendChild(host);
  }
  var el = document.createElement("div");
  el.className = "desktop-toast desktop-toast-" + type;
  el.textContent = String(message || "");
  host.appendChild(el);
  requestAnimationFrame(function () {
    el.classList.add("desktop-toast-visible");
  });
  window.setTimeout(function () {
    el.classList.remove("desktop-toast-visible");
    window.setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 240);
  }, duration);
}

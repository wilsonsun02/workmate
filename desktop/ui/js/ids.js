export function genId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return "c" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);
}

/** 与 main.generate_session_id 一致：thread_YYYYMMDD_HHMMSS */
export function generateSessionId(prefix) {
  var p = prefix || "session";
  var d = new Date();
  var pad = function (n) {
    return (n < 10 ? "0" : "") + n;
  };
  var stamp =
    d.getFullYear() +
    pad(d.getMonth() + 1) +
    pad(d.getDate()) +
    "_" +
    pad(d.getHours()) +
    pad(d.getMinutes()) +
    pad(d.getSeconds());
  return p + "_" + stamp;
}

export function initial(username) {
  var s = (username || "?").trim();
  if (!s) return "?";
  return s.charAt(0).toUpperCase();
}

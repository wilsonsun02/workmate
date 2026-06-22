/**
 * 避免「立即执行」已在 tasks.js 里弹出完成提示后，侧栏同步又为同一条 feed 再弹一次。
 */
var _suppressUntil = Object.create(null);

export function suppressSchedulerFeedToastForExecution(executionId, ttlMs) {
  var id = String(executionId || "").trim();
  if (!id) return;
  ttlMs = ttlMs != null ? ttlMs : 15000;
  _suppressUntil[id] = Date.now() + ttlMs;
}

export function shouldSuppressSchedulerFeedToast(executionId) {
  var id = String(executionId || "").trim();
  if (!id) return false;
  var until = _suppressUntil[id];
  if (!until) return false;
  if (Date.now() > until) {
    delete _suppressUntil[id];
    return false;
  }
  return true;
}

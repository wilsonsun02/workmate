/**
 * 解析 /quotation 流式 SSE（与 main.run_stream_quotation 一致：data: {json}）
 * 最终以 event_type === 'done' 的 content 为助手回复正文。
 *
 * @param {ReadableStream} body
 * @param {{ onEvent?: (ev: Record<string, unknown>) => void }} [options]
 */
export function parseQuotationSSE(body, options) {
  if (!body || typeof body.getReader !== "function") {
    return Promise.reject(new Error("响应不支持流式读取"));
  }
  options = options || {};
  var onEvent = typeof options.onEvent === "function" ? options.onEvent : null;
  var onHITLWait = typeof options.onHITLWait === "function" ? options.onHITLWait : null;
  var reader = body.getReader();
  var decoder = new TextDecoder();
  var buf = "";
  var finalContent = "";
  var streamError = null;
  var hitlPending = false;

  function processLine(line) {
    if (line.indexOf("data: ") !== 0) return;
    var raw = line.slice(6).trim();
    if (!raw) return;
    try {
      var ev = JSON.parse(raw);
      if (onEvent) {
        try {
          onEvent(ev);
        } catch (_e) {
          /* ignore consumer errors */
        }
      }
      if (ev.event_type === "hitl_wait") {
        if (onHITLWait) {
          try { onHITLWait(ev); } catch (_e) { /* ignore */ }
        }
        hitlPending = true;
        return;
      }
      if (ev.event_type === "error") {
        streamError = ev.content || "执行错误";
      }
      if (ev.event_type === "done" && ev.content != null) {
        finalContent = ev.content;
      }
    } catch (e) {
      /* ignore malformed chunk */
    }
  }

  function pump() {
    return reader.read().then(function (result) {
      if (hitlPending) {
        try { reader.cancel(); } catch (_e) {}
        return null;
      }
      if (result.done) {
        if (buf.trim()) {
          processLine(buf.trim());
        }
        if (streamError) {
          throw new Error(streamError);
        }
        return finalContent;
      }
      buf += decoder.decode(result.value, { stream: true });
      var nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        var line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (line) processLine(line);
      }
      if (hitlPending) {
        try { reader.cancel(); } catch (_e) {}
        return null;
      }
      return pump();
    });
  }

  return pump();
}

export function escapeHtml(s) {
  var d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

/** 将助手 Markdown 转为安全 HTML；库未加载时退化为纯文本转义 */
function escapeAttr(s) {
  // 仅用于属性值上下文
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeMarkdownText(s) {
  return escapeHtml(s);
}

function splitTrailingPunct(token) {
  // 例如：路径后跟 `)` 或 `,` 时，尽量不要把标点包含进链接 href
  var m = String(token || "").match(/^(.*?)([)\],.;:]+)$/);
  if (!m) return { core: token, tail: "" };
  return { core: m[1], tail: m[2] };
}

/**
 * Windows 绝对路径：须匹配含空格的文件名（如 …/凤莲 2 月对账单.xlsx）。
 * 优先匹配以 .ext 结尾；否则退回到不含空格的老规则，避免过度吞噬正文。
 */
var WIN_ABS_PATH_RE = /\b[A-Za-z]:[\\/](?:[^<>"'\n]+?\.[A-Za-z0-9]{1,28}\b|[^\s<>"']+)/g;

/** /workspace/... 虚拟路径，同样允许空格 + 常见扩展名 */
var WS_ABS_PATH_RE = /\/workspace\/(?:[^<>"'\n]+?\.[A-Za-z0-9]{1,28}\b|[^\s<>"')\]]+)/g;

/** 避免匹配到 data-file-url="file:///C:/..." 里的第二个 C: */
function isWinPathInsideFileUrl(fullStr, matchOffset) {
  return /file:\/\//i.test(fullStr.slice(Math.max(0, matchOffset - 40), matchOffset));
}

function isWorkspacePathInsideHtmlAttr(fullStr, matchOffset) {
  var probe = fullStr.slice(Math.max(0, matchOffset - 180), matchOffset);
  return /<a\b[\s\S]*data-file-url\s*=\s*["'][^"']*$/i.test(probe);
}

function toFileUrlFromWindowsPath(p) {
  // C:\a\b -> file:///C:/a/b（对各路径段做 encodeURIComponent，避免空格等导致 URL 无效）
  var abs = String(p || "").replace(/\\/g, "/").trim();
  if (!abs) return "";
  if (abs.startsWith("file://")) return abs;
  if (/^[A-Za-z]:\//.test(abs)) {
    var parts = abs.split("/");
    var enc = parts.map(function (seg, i) {
      if (i === 0 && /^[A-Za-z]:$/.test(seg)) return seg;
      return encodeURIComponent(seg);
    });
    return "file:///" + enc.join("/");
  }
  return "file:///" + abs.replace(/^\.\/+/, "");
}

/**
 * DeepAgent 常在 ```json``` 里输出 { "generated_files": ["C:/..."] }；代码块内的路径不会走 linkify。
 * 将该结构展开为带 path-link 的片段，以便渲染可点击打开文件夹。
 */
function extractGeneratedFilesFromBlockBody(body) {
  var files = [];
  try {
    var parsed = JSON.parse(String(body).trim());
    if (parsed && Array.isArray(parsed.generated_files)) {
      parsed.generated_files.forEach(function (x) {
        if (x != null && String(x).trim()) files.push(String(x).trim());
      });
    }
  } catch (_e) {
    var innerMatch = String(body).match(/"generated_files"\s*:\s*\[([\s\S]*?)\]/i);
    if (innerMatch) {
      var re = /"([^"]+)"/g;
      var hit;
      while ((hit = re.exec(innerMatch[1])) !== null) {
        if (hit[1] && String(hit[1]).trim()) files.push(String(hit[1]).trim());
      }
    }
  }
  return files;
}

function expandGeneratedFilesJsonBlock(body, _opts) {
  var raw = String(body || "").trim();
  if (!/"generated_files"/i.test(raw)) return null;
  var files = extractGeneratedFilesFromBlockBody(body);
  // 仅有机具栏位、无实际路径：属于模型占位，不向用户展示空 JSON 代码块
  if (!files.length) return "";
  var lines = [];
  files.forEach(function (p) {
    var raw = String(p).trim();
    var sp = splitTrailingPunct(raw);
    var core = sp.core;
    var tailText = sp.tail ? escapeMarkdownText(sp.tail) : "";
    var pathForMd = core.replace(/`/g, "'");
    lines.push("- `" + pathForMd + "`" + tailText);
  });
  return lines.join("\n");
}

function mapWorkspacePathToFileUrl(p, workspaceRoot) {
  // /workspace/admin/x -> <workspaceRoot>/admin/x
  if (!workspaceRoot) return "";
  var rr = String(workspaceRoot || "").replace(/[\\/]+$/, "");
  var rest = String(p || "").replace(/^\/workspace\/?/, "");
  if (!rest) return "";
  var abs = rr + "/" + rest.replace(/^\/+/, "");
  return toFileUrlFromWindowsPath(abs);
}

/**
 * 模型有时把 path-link 整段 HTML 包在 ` 行内代码 ` 里，marked 会原样显示成原始标签。
 * 去掉外层的反引号并补全缺失的 </a>。
 */
function unwrapBacktickedPathLinkHtml(source) {
  var input = String(source || "");
  return input.replace(
    /`(<a\s[\s\S]*?)`/gi,
    function (_m, inner) {
      if (!/class\s*=\s*["']path-link["']/i.test(inner)) return _m;
      if (!/data-file-url\s*=\s*["']/i.test(inner)) return _m;
      var t = inner.trim();
      if (/<\/a>\s*$/i.test(t)) return t;
      var m = t.match(/^<a\s+([^>]+)>([\s\S]*)$/i);
      if (!m) return _m;
      return "<a " + m[1] + ">" + escapeMarkdownText(String(m[2] || "").trim()) + "</a>";
    }
  );
}

function linkifySource(raw, opts) {
  var source = raw == null ? "" : String(raw);
  var workspaceRoot = opts && opts.workspaceRoot ? String(opts.workspaceRoot) : "";

  source = unwrapBacktickedPathLinkHtml(source);

  // 0) 仅含 generated_files 的 JSON 围栏：展开为可点击链接（否则永远不会被下列逻辑处理）
  // 模型常在代码块前已写「生成的文件：**」，此处只插列表，避免重复标题。
  source = source.replace(/```(?:json)?\s*\r?\n([\s\S]*?)```/gi, function (m, inner, offset, fullStr) {
    var expanded = expandGeneratedFilesJsonBlock(inner, opts);
    if (expanded == null) return m;
    if (expanded === "") return "";
    var before = fullStr.slice(Math.max(0, offset - 320), offset).replace(/[\t \u00a0]+$/g, "");
    before = before.replace(/\n+$/g, "");
    var hasGenHeader = /(?:\*\*)?生成的文件(?:\*\*)?\s*[：:]?\s*$/.test(before);
    if (hasGenHeader) {
      return "\n\n" + expanded + "\n\n";
    }
    return "\n\n**生成的文件：**\n" + expanded + "\n\n";
  });

  // 防止在 Markdown 行内代码 / 代码块（反引号）中替换，
  // 否则 marked 会把我们的 <a ...> 当成代码文本转义，导致显示为“不可点击的 HTML 字符串”。
  // 处理顺序：
  // 1) 先保护 ```...``` 代码块（支持多行）
  var fenced = [];
  source = source.replace(/```[\s\S]*?```/g, function (m) {
    var key = "\u0000F" + fenced.length + "\u0000";
    fenced.push(m);
    return key;
  });

  // 2) 再保护 `...` 行内代码片段
  var parts = source.split(/(`[^`]*`)/g);
  source = parts
    .map(function (part) {
      if (!part) return part;
      if (part.startsWith("`") && part.endsWith("`")) {
        // 行内代码：如果里面看起来是路径/URL，把它替换成真正的 <a>，移除反引号；
        // 否则会出现“显示 HTML 字符串但不可点击”的问题。
        var inner = part.slice(1, -1);
        var looksLikePathOrUrl =
          inner.indexOf("/workspace/") >= 0 ||
          /^\s*[A-Za-z]:[\\/]/.test(inner) ||
          /^\s*https?:\/\//i.test(inner);
        if (!looksLikePathOrUrl) return part;

        // 1) URL
        var urlReInline = /\bhttps?:\/\/[^\s<>"')\]]+/gi;
        inner = inner.replace(urlReInline, function (u) {
          var sp = splitTrailingPunct(u);
          var href = escapeAttr(sp.core);
          var text = escapeMarkdownText(sp.core);
          return `<a href="#" class="path-link" data-file-url="${href}">${text}</a>${escapeMarkdownText(sp.tail)}`;
        });

        // 2) /workspace/... 路径（先处理，避免后续在已生成 <a> 的 data-file-url 中再次命中）
        inner = inner.replace(WS_ABS_PATH_RE, function (p) {
          var off = arguments.length > 1 ? Number(arguments[1]) : 0;
          var full = arguments.length > 2 ? String(arguments[2] || "") : "";
          if (isWorkspacePathInsideHtmlAttr(full, off)) return p;
          var sp = splitTrailingPunct(p);
          var fileUrl = mapWorkspacePathToFileUrl(sp.core, workspaceRoot);
          if (!fileUrl) return p;
          var href = escapeAttr(fileUrl);
          var text = escapeMarkdownText(sp.core);
          return `<a href="#" class="path-link" data-file-url="${href}">${text}</a>${escapeMarkdownText(sp.tail)}`;
        });

        // 3) Windows 绝对路径
        inner = inner.replace(WIN_ABS_PATH_RE, function (p, offset, full) {
          if (isWinPathInsideFileUrl(full, offset)) return p;
          var sp = splitTrailingPunct(p);
          var fileUrl = toFileUrlFromWindowsPath(sp.core);
          if (!fileUrl) return p;
          var href = escapeAttr(fileUrl);
          var text = escapeMarkdownText(sp.core);
          return `<a href="#" class="path-link" data-file-url="${href}">${text}</a>${escapeMarkdownText(sp.tail)}`;
        });

        return inner;
      }

      // 以下仅对“非代码片段”做 linkify

      // 先把 URL 链接化
      var urlRe = /\bhttps?:\/\/[^\s<>"')\]]+/gi;
      part = part.replace(urlRe, function (u) {
        var sp = splitTrailingPunct(u);
        var href = escapeAttr(sp.core);
        var text = escapeMarkdownText(sp.core);
        return `<a href="#" class="path-link" data-file-url="${href}">${text}</a>${escapeMarkdownText(sp.tail)}`;
      });

      // 再把 /workspace/... 映射为本地文件链接（先于 Windows 路径，防止二次替换）
      part = part.replace(WS_ABS_PATH_RE, function (p) {
        var off = arguments.length > 1 ? Number(arguments[1]) : 0;
        var full = arguments.length > 2 ? String(arguments[2] || "") : "";
        if (isWorkspacePathInsideHtmlAttr(full, off)) return p;
        var sp = splitTrailingPunct(p);
        var fileUrl = mapWorkspacePathToFileUrl(sp.core, workspaceRoot);
        if (!fileUrl) return p;
        var href = escapeAttr(fileUrl);
        var text = escapeMarkdownText(sp.core);
        return `<a href="#" class="path-link" data-file-url="${href}">${text}</a>${escapeMarkdownText(sp.tail)}`;
      });

      // 最后把 Windows 文件路径链接化
      part = part.replace(WIN_ABS_PATH_RE, function (p, offset, full) {
        if (isWinPathInsideFileUrl(full, offset)) return p;
        var sp = splitTrailingPunct(p);
        var fileUrl = toFileUrlFromWindowsPath(sp.core);
        if (!fileUrl) return p;
        var href = escapeAttr(fileUrl);
        var text = escapeMarkdownText(sp.core);
        return `<a href="#" class="path-link" data-file-url="${href}">${text}</a>${escapeMarkdownText(sp.tail)}`;
      });

      return part;
    })
    .join("");

  // 3) 恢复 ```...``` 代码块
  source = source.replace(/\u0000F(\d+)\u0000/g, function (_m, idx) {
    return fenced[Number(idx)] || "";
  });

  return source;
}

/** 将助手 Markdown 转为安全 HTML；库未加载时退化为纯文本转义 */
export function assistantMarkdownToHtml(source, opts) {
  var raw = source == null ? "" : String(source);
  if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
    return escapeHtml(raw);
  }
  try {
    marked.setOptions({ gfm: true, breaks: true });
    var linkified = linkifySource(raw, opts);
    var html = marked.parse(linkified);
    return DOMPurify.sanitize(html, { ADD_ATTR: ["data-file-url"] });
  } catch (e) {
    return escapeHtml(raw);
  }
}

import { assistantMarkdownToHtml } from "./markdown.js";
import { genId, generateSessionId } from "./ids.js";
import {
  getSession,
} from "./storage.js";
import { parseQuotationSSE } from "./sse.js";
import { showToast } from "./toast.js";
import { shouldSuppressSchedulerFeedToast } from "./scheduler_toast_dedupe.js";
import { createHITLManager } from "./hitl.js";
import {
  getConversationDisplayTitle,
  normalizeConversationTitle,
  normalizeDisplayMessageText,
  normalizeStoredUserMessage,
  parseSkillsInjectedPayload,
  parseMcpInjectedPayload,
  parseKnowledgePayload,
  parseAttachmentPayload,
  splitUserExtraContext,
  stripSourcePrefix,
} from "./message_normalizer.js";

function trimMsgText(t) {
  return String(t != null ? t : "").trim();
}

function deriveConversationTitleFromMessages(messages) {
  var list = Array.isArray(messages) ? messages : [];
  for (var i = 0; i < list.length; i++) {
    var m = list[i];
    if (!m || m.role !== "user") continue;
    var t = trimMsgText(normalizeDisplayMessageText(m.text));
    if (!t) continue;
    var max = 28;
    return t.length > max ? t.slice(0, max) + "…" : t;
  }
  return "";
}

function normalizeUpdatedAt(v) {
  var n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function formatTimestamp(ts) {
  if (ts == null || ts === "") return "";
  var n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return "";
  // 毫秒时间戳（13位）或秒时间戳（10位）
  var ms = n > 1000000000000 ? n : n * 1000;
  var d = new Date(ms);
  if (isNaN(d.getTime())) return "";
  // 拒绝明显无效的时间戳（年份不在 2024~2100 范围内），防止 rowid 等非时间戳值被误格式化
  var year = d.getFullYear();
  if (year < 2024 || year > 2100) return "";
  var pad = function (v) { return v < 10 ? "0" + v : "" + v; };
  return (
    year +
    "-" +
    pad(d.getMonth() + 1) +
    "-" +
    pad(d.getDate()) +
    " " +
    pad(d.getHours()) +
    ":" +
    pad(d.getMinutes()) +
    ":" +
    pad(d.getSeconds())
  );
}

/**
 * SSE / LangChain 的 content 可能是 string 或 block 数组。
 */
function normalizeThinkContent(raw) {
  if (raw == null) return "";
  if (typeof raw === "string") return raw;
  if (Array.isArray(raw)) {
    var parts = [];
    for (var i = 0; i < raw.length; i++) {
      var part = raw[i];
      if (typeof part === "string") parts.push(part);
      else if (part && typeof part === "object" && part.text != null) {
        parts.push(String(part.text));
      }
    }
    return parts.join("");
  }
  if (raw && typeof raw === "object" && raw.text != null) return String(raw.text);
  try {
    return String(raw);
  } catch (_e) {
    return "";
  }
}

function escapeMdBackticks(s) {
  return String(s || "").replace(/`/g, "'");
}

var SHELL_STEP_PREFIXES = [
  "uv run",
  "python ",
  "python3 ",
  "npm ",
  "npx ",
  "node ",
  "bash ",
  "sh ",
  "curl ",
  "pip ",
  "pytest ",
  "cmd ",
  "powershell",
];

function isCommandOnlyThinkLine(text) {
  var t = trimMsgText(text);
  if (!t) return true;
  var lower = t.toLowerCase();
  for (var i = 0; i < SHELL_STEP_PREFIXES.length; i++) {
    if (lower.indexOf(SHELL_STEP_PREFIXES[i]) === 0) return true;
  }
  return false;
}

function isPathLikeThinkHint(hint) {
  var h = trimMsgText(hint);
  if (!h) return false;
  if (/[/\\]/.test(h)) return true;
  return /\.(png|jpe?g|gif|webp|json|md|docx?|xlsx?|pdf|html?|py|txt)\b/i.test(h);
}

function stripGeneratedFilesPlaceholderJson(text) {
  var raw = String(text || "");
  if (!trimMsgText(raw)) return "";
  var cleaned = raw.replace(
    /```(?:json)?\s*\{[^{}]*"generated_files"\s*:\s*\[[^\]]*\][^{}]*\}\s*```/gis,
    ""
  );
  cleaned = cleaned.replace(
    /\{[^{}]*"generated_files"\s*:\s*\[[^\]]*\][^{}]*\}/gis,
    ""
  );
  return cleaned.trim();
}

/** 与后端 think-steps 一致：仅合并路径类工具参数。 */
function extractPathHintsFromToolArgs(args) {
  if (!args || typeof args !== "object") return [];
  var hints = [];
  ["path", "file_path", "filepath", "directory", "dir", "output", "out"].forEach(function (k) {
    var v = args[k];
    if (v == null) return;
    var candidate = trimMsgText(v);
    if (isPathLikeThinkHint(candidate) && hints.indexOf(candidate) < 0) {
      hints.push(candidate);
    }
  });
  return hints;
}

/** 将 SSE think 事件格式化为一步（与 /think-steps 同源规则）。 */
function formatThinkStepFromStreamEvent(ev) {
  if (!ev || ev.event_type !== "think") return null;
  var content = trimMsgText(normalizeThinkContent(ev.content));
  if (content.indexOf("[") === 0 && content.indexOf("tool_call") >= 0) content = "";
  if (isToolCallsOnlyContent(content)) content = "";
  content = stripGeneratedFilesPlaceholderJson(content);
  if (isCommandOnlyThinkLine(content)) content = "";
  var line = content;
  var hints = [];
  var toolsCalled = Array.isArray(ev.tools_called) ? ev.tools_called : [];
  toolsCalled.forEach(function (tc) {
    if (!tc || typeof tc !== "object") return;
    extractPathHintsFromToolArgs(tc.args).forEach(function (h) {
      if (hints.indexOf(h) < 0) hints.push(h);
    });
  });
  if (Array.isArray(ev.generated_files)) {
    ev.generated_files.forEach(function (p) {
      var s = trimMsgText(p);
      if (isPathLikeThinkHint(s) && hints.indexOf(s) < 0) hints.push(s);
    });
  }
  line = appendHintsToThinkLine(line, hints);
  if (!line || isCommandOnlyThinkLine(line)) return null;
  return line;
}

function appendHintsToThinkLine(line, hints) {
  var out = trimMsgText(line);
  (hints || []).forEach(function (h) {
    var hint = trimMsgText(h);
    if (!hint) return;
    if (out && out.indexOf(hint) >= 0) return;
    out = out ? out + " " + hint : hint;
  });
  return trimMsgText(out);
}

/** 是否为仅序列化 tool_calls 的正文（避免与「调用工具」重复）。 */
function isToolCallsOnlyContent(text) {
  var t = trimMsgText(text);
  if (!t || t.charAt(0) !== "[") return false;
  return (
    t.indexOf("tool_call") >= 0 ||
    (t.indexOf('"name"') >= 0 && t.indexOf('"args"') >= 0) ||
    (t.indexOf("'name'") >= 0 && t.indexOf("'args'") >= 0)
  );
}

/** 是否有可展示的思考/执行内容（忽略内部 middleware 节点名）。 */
function hasThinkDisplayContent(ev) {
  if (!ev) return false;
  var base = trimMsgText(normalizeThinkContent(ev.content));
  if (base && !isToolCallsOnlyContent(base)) return true;
  if (Array.isArray(ev.tools_called) && ev.tools_called.length) return true;
  if (Array.isArray(ev.generated_files) && ev.generated_files.length) return true;
  var results = Array.isArray(ev.tool_results) ? ev.tool_results : [];
  for (var i = 0; i < results.length; i++) {
    var r = results[i];
    if (!r || typeof r !== "object") continue;
    if (trimMsgText(r.result != null ? r.result : r.content)) return true;
  }
  return false;
}

/** 实时 SSE：按 think-steps 规则追加一步；结束后仍用 /think-steps 校准。 */
function ingestThinkStreamEvent(assistantMsg, ev) {
  if (!assistantMsg || !ev) return false;
  var stepText = formatThinkStepFromStreamEvent(ev);
  if (!stepText) return false;
  appendThinkStepToAssistant(assistantMsg, stepText);
  return true;
}

function clearThinkStreamState(assistantMsg) {
  if (!assistantMsg) return;
  delete assistantMsg._pendingThinkHints;
}

function isThinkStreamingPlaceholder(text) {
  var t = trimMsgText(text);
  return t === "" || t === "正在思考…" || t === "正在继续执行…";
}

/** 将一步思考/执行过程追加到 thinkSteps（去重）。 */
function appendThinkStepToAssistant(last, stepText) {
  if (!last || !stepText) return;
  last.thinkSteps = last.thinkSteps || [];
  var tail = last.thinkSteps.length
    ? trimMsgText(last.thinkSteps[last.thinkSteps.length - 1])
    : "";
  if (stepText !== tail) {
    last.thinkSteps.push(stepText);
  }
}

/** 将上一条流式预览归档到 thinkSteps（去重）。 */
function archiveThinkStreamingPreview(last, previewText) {
  appendThinkStepToAssistant(last, previewText);
}

/** 思考步骤不做 normalizeDisplayMessageText，避免误删工具/JSON 内容。 */
function cloneThinkStepsForDisplay(steps) {
  if (!Array.isArray(steps)) return [];
  return steps
    .map(function (s) {
      return trimMsgText(String(s != null ? s : ""));
    })
    .filter(Boolean);
}

/** 去除末尾与最终正文完全相同的步骤，避免折叠区与回复区重复。 */
function dedupeTrailingThinkSteps(thinkSteps, finalText) {
  var F = trimMsgText(finalText);
  var out = (thinkSteps || []).map(trimMsgText).filter(Boolean);
  while (out.length && F && out[out.length - 1] === F) {
    out.pop();
  }
  return out;
}

/**
 * 将 user 与紧随其后的多条 assistant 压成展示行：中间过程为 thinkSteps，末条为正文。
 */
function buildMessageDisplayRows(messages) {
  var rows = [];
  var i = 0;
  while (i < messages.length) {
    var m = messages[i];
    if (m.role === "user") {
      // 分层剥离：技能 → MCP工具 → 来源前缀 → 知识库 → 附件 → 【用户说明】分割
      var userParsed = parseSkillsInjectedPayload(m.text);
      var mcpParsed = parseMcpInjectedPayload(userParsed.text);
      var textAfterSource = stripSourcePrefix(mcpParsed.text);
      var knowledgeParsed = parseKnowledgePayload(textAfterSource);
      var attachmentParsed = parseAttachmentPayload(knowledgeParsed.text);
      var split = splitUserExtraContext(attachmentParsed.text);
      var skills =
        Array.isArray(m.skills) && m.skills.length ? m.skills : userParsed.skills;
      // 优先从消息对象读取元数据，兼容历史消息从文本解析
      var mcpTools =
        Array.isArray(m.mcpTools) && m.mcpTools.length ? m.mcpTools : mcpParsed.mcpTools;
      var attachmentNames =
        Array.isArray(m.attachmentNames) && m.attachmentNames.length ? m.attachmentNames : [];
      var knowledgeNames =
        Array.isArray(m.knowledgeNames) && m.knowledgeNames.length ? m.knowledgeNames : [];
      rows.push({
        kind: "user",
        text: split.main,
        extraContext: split.extra,
        mcpTools: mcpTools,
        skills: skills,
        knowledgeContent: knowledgeParsed.knowledgeContent,
        attachmentContent: attachmentParsed.attachmentContent,
        attachmentNames: attachmentNames,
        knowledgeNames: knowledgeNames,
        timestamp: m.timestamp,
      });
      i++;
      var assistants = [];
      while (i < messages.length && messages[i].role === "assistant") {
        assistants.push(messages[i]);
        i++;
      }
      if (!assistants.length) continue;
      if (assistants.length === 1) {
        var a0 = assistants[0];
        rows.push({
          kind: "assistant",
          text: normalizeDisplayMessageText(a0.text),
          thinkSteps: cloneThinkStepsForDisplay(a0.thinkSteps),
          streaming: a0.streaming,
          timestamp: a0.timestamp,
        });
      } else {
        var thinks = assistants.slice(0, -1).map(function (a) {
          return normalizeDisplayMessageText(a.text);
        });
        var last = assistants[assistants.length - 1];
        rows.push({
          kind: "assistant",
          text: normalizeDisplayMessageText(last.text),
          thinkSteps: thinks,
          streaming: last.streaming,
          timestamp: last.timestamp,
        });
      }
    } else if (m.role === "assistant") {
      rows.push({
        kind: "assistant",
        text: normalizeDisplayMessageText(m.text),
        thinkSteps: cloneThinkStepsForDisplay(m.thinkSteps),
        streaming: m.streaming,
        timestamp: m.timestamp,
      });
      i++;
    } else {
      i++;
    }
  }
  return rows;
}

export function createChatController(options) {
  var apiBase = options.apiBase;
  var conversationListEl = options.conversationListEl;
  var schedulerConversationListEl = options.schedulerConversationListEl || null;
  var messagesEl = options.messagesEl;
  var confirmOverlay = options.confirmOverlay;
  var confirmTitleEl = options.confirmTitleEl;
  var confirmDescEl = options.confirmDescEl;
  var confirmBtnOk = options.confirmBtnOk;
  var confirmBtnCancel = options.confirmBtnCancel;

  var scopedUsername = currentUsername();
  var chatState = { version: 1, activeId: null, conversations: [] };
  var openMenuConvId = null;
  var quotationInFlight = false;
  /** 进行中的 /quotation 属于哪个会话；切换回来时勿用空后端列表覆盖本地乐观更新。 */
  var quotationInFlightConvId = null;
  var quotationAbortController = null;
  var quotationStopRequested = false;

  var hitlManager = createHITLManager({
    apiBase: apiBase,
    getUsername: function () { return currentUsername(); },
    resumeFn: function (conv, command, attachmentPaths) {
      resumeWithHITL(conv, command, attachmentPaths);
    },
  });
  var confirmDialogResolve = null;
  var workspaceRoot = options.workspaceRoot || "";
  var desktopBridgeGetter = options.getDesktopBridge || null;
  var schedulerSectionToggleEl = document.getElementById("scheduler-section-toggle");
  var sidebarSearchInputEl = options.sidebarSearchInputEl || null;
  var sidebarSearchClearEl = null;
  /** 侧栏点击会话时（例如在「定时任务」页）先切回对话主视图 */
  var onSidebarConversationOpen = options.onSidebarConversationOpen;
  var buildUserInputBeforeSend =
    typeof options.buildUserInputBeforeSend === "function"
      ? options.buildUserInputBeforeSend
      : null;
  var onAssistantStreamDone =
    typeof options.onAssistantStreamDone === "function"
      ? options.onAssistantStreamDone
      : null;
  var augmentUserInputBeforeSend =
    typeof options.augmentUserInputBeforeSend === "function"
      ? options.augmentUserInputBeforeSend
      : null;

  function notifyAssistantStreamDone(conv, finalContent) {
    if (!onAssistantStreamDone) return Promise.resolve();
    try {
      return Promise.resolve(onAssistantStreamDone(conv, finalContent)).catch(
        function () {
          return undefined;
        }
      );
    } catch (_e) {
      return Promise.resolve();
    }
  }
  var pendingFiles = [];
  var schedulerSectionExpanded = true;
  /* 对话列表批量管理状态 */
  var convBatchMode = false;
  var convBatchSelectedIds = {};
  /* 定时任务记录列表批量管理状态 */
  var schedBatchMode = false;
  var schedBatchSelectedIds = {};
  var ATTACHMENT_ALLOWED_SUFFIXES = {
    ".xlsx": true,
    ".xls": true,
    ".xlsb": true,
    ".csv": true,
    ".jpg": true,
    ".jpeg": true,
    ".png": true,
    ".webp": true,
    ".gif": true,
    ".bmp": true,
    ".doc": true,
    ".docx": true,
    ".ppt": true,
    ".pptx": true,
    ".pdf": true,
    ".txt": true,
    ".md": true,
    ".mp4": true,
    ".mov": true,
    ".avi": true,
    ".mkv": true,
    ".webm": true,
    ".mp3": true,
    ".wav": true,
    ".m4a": true,
    ".aac": true,
    ".ogg": true,
    ".flac": true,
  };
  var ATTACHMENT_MAX_FILES = 10;

  function currentUsername() {
    var sess = getSession();
    if (sess && sess.user && sess.user.username) return sess.user.username;
    return "";
  }

  function isSchedulerConversation(conv) {
    if (!conv) return false;
    var tid = String(conv.threadId || "");
    return tid.indexOf("_sched_") >= 0;
  }

  /**
   * 与列表接口一致：checkpoint 中尚无有效用户消息时 title 为「新对话」。
   * 用于「＋」与自动开会话时复用，避免堆多个空白线程。
   */
  function isReusableBlankNormalConversation(conv) {
    if (!conv || isSchedulerConversation(conv)) return false;
    return String(conv.title || "").trim() === "新对话";
  }

  function findReusableBlankNormalConversation() {
    sortConversationsByRecency();
    for (var i = 0; i < chatState.conversations.length; i++) {
      var c = chatState.conversations[i];
      if (isReusableBlankNormalConversation(c)) return c;
    }
    return null;
  }

  function setSchedulerSectionExpanded(expanded) {
    schedulerSectionExpanded = !!expanded;
    if (schedulerSectionToggleEl) {
      schedulerSectionToggleEl.setAttribute("aria-expanded", schedulerSectionExpanded ? "true" : "false");
    }
    var chevron = document.getElementById("scheduler-section-chevron");
    if (chevron) chevron.classList.toggle("rotated", schedulerSectionExpanded);
    if (schedulerConversationListEl) {
      schedulerConversationListEl.classList.toggle("hidden", !schedulerSectionExpanded);
    }
  }

  function normalizeUsername(username) {
    return String(username || "").trim();
  }

  function normalizeChatStateShape(raw) {
    if (!raw || typeof raw !== "object" || !Array.isArray(raw.conversations)) return null;
    var normalized = {
      version: raw.version || 1,
      activeId: raw.activeId || null,
      conversations: raw.conversations.map(function (c) {
        return {
          id: c.id || genId(),
          title: normalizeConversationTitle(typeof c.title === "string" ? c.title : "对话"),
          messages: Array.isArray(c.messages) ? c.messages : [],
          threadId: c.threadId || "",
          sessionId: c.sessionId || "",
          updatedAt: normalizeUpdatedAt(c.updatedAt),
        };
      }),
    };
    if (!normalized.activeId && normalized.conversations.length) {
      normalized.activeId = normalized.conversations[0].id;
    }
    return normalized;
  }

  function persistChatState() {
    // 统一数据源后，前端不再持久化会话列表到本地。
  }

  function syncChatStateToBackend() {
    // no-op: deprecated
  }

  function touchConversation(conv, ts) {
    if (!conv) return;
    conv.updatedAt = normalizeUpdatedAt(ts || Date.now());
  }

  function sortConversationsByRecency() {
    chatState.conversations.sort(function (a, b) {
      var ua = normalizeUpdatedAt(a && a.updatedAt);
      var ub = normalizeUpdatedAt(b && b.updatedAt);
      if (ub !== ua) return ub - ua;
      // 稳定兜底：同时间戳按 id 逆序，避免抖动
      var ia = String((a && a.id) || "");
      var ib = String((b && b.id) || "");
      return ib.localeCompare(ia);
    });
  }

  function pickPreferredActiveConversationId() {
    if (!Array.isArray(chatState.conversations) || !chatState.conversations.length) return null;
    for (var i = 0; i < chatState.conversations.length; i++) {
      var c = chatState.conversations[i];
      if (!isSchedulerConversation(c)) return c.id;
    }
    return chatState.conversations[0].id;
  }

  /**
   * 从后端加载对话消息，支持分页
   * 后端基于原始消息总数分页（含工具调用等被过滤消息），
   * 因此 nextOffset = offset + limit，而非过滤后的显示数量。
   * @param {Object} conv - 对话对象
   * @param {number} [opts.offset] - 跳过最新 N 条原始消息（默认 0）
   * @param {number} [opts.limit] - 每次加载原始消息数量（默认 50）
   * @returns {Promise<{messages: Array, total: number, hasMore: boolean, nextOffset: number}>}
   */
  async function loadMessagesFromBackend(conv, opts) {
    if (!conv || !conv.threadId) return { messages: [], total: 0, hasMore: false, nextOffset: 0 };
    var username = scopedUsername || currentUsername();
    if (!username) return { messages: [], total: 0, hasMore: false, nextOffset: 0 };
    var offset = (opts && typeof opts.offset === "number" && opts.offset >= 0) ? opts.offset : 0;
    var limit = (opts && typeof opts.limit === "number") ? opts.limit : 50;
    try {
      var res = await fetch(
        apiBase +
          "/api/desktop/conversations/" +
          encodeURIComponent(conv.threadId) +
          "/messages?username=" +
          encodeURIComponent(username) +
          "&session_id=" +
          encodeURIComponent(conv.sessionId || "") +
          "&offset=" + offset +
          "&limit=" + limit,
        { method: "GET", cache: "no-store" }
      );
      if (!res.ok) return { messages: [], total: 0, hasMore: false, nextOffset: offset };
      var data = await res.json();
      var raw = Array.isArray(data && data.messages) ? data.messages : [];
      var messages = raw.map(function (m) {
        return m && m.role === "user" ? normalizeStoredUserMessage(m) : m;
      });
      return {
        messages: messages,
        total: (data && typeof data.total === "number") ? data.total : messages.length,
        hasMore: !!(data && data.has_more),
        // 后端按可显示消息总数分页，nextOffset 基于请求参数计算，
        // 避免因边界过滤差异导致分页错位
        nextOffset: offset + limit,
      };
    } catch (_e) {
      return { messages: [], total: 0, hasMore: false, nextOffset: offset };
    }
  }

  /**
   * 加载更早的历史消息，向前拼接
   * 使用 nextOffset（基于原始消息偏移）更新游标，避免因过滤导致分页错位；
   * 同时对新旧消息重叠部分去重，作为安全兜底。
   */
  async function loadMoreMessages(conv) {
    if (!conv || !conv._msgHasMore) return;
    var currentOffset = conv._msgOffset || 0;
    var result = await loadMessagesFromBackend(conv, { offset: currentOffset, limit: 50 });
    if (!result.messages.length) {
      conv._msgHasMore = false;
      return;
    }
    // 更早的消息插入到现有消息前面，去重兜底防止因 checkpoint 变化导致的边界重叠
    var olderMessages = dedupeOlderMessages(result.messages, conv.messages);
    conv.messages = olderMessages.concat(conv.messages);
    conv._msgOffset = result.nextOffset;
    conv._msgHasMore = result.hasMore;
    backfillConversationTitleFromMessages(conv);
  }

  // 对新加载的更早消息与已有消息做去重：按 role+text 组合键过滤重叠部分
  function dedupeOlderMessages(olderMsgs, existingMsgs) {
    if (!olderMsgs || !olderMsgs.length || !existingMsgs || !existingMsgs.length) return olderMsgs;
    // 构建已有消息的指纹集合，仅取末尾少量消息做比对（重叠范围有限）
    var fingerprintSet = Object.create(null);
    var checkLimit = Math.min(existingMsgs.length, olderMsgs.length + 5);
    for (var k = existingMsgs.length - checkLimit; k < existingMsgs.length; k++) {
      var ek = existingMsgs[k];
      fingerprintSet[(ek.role || "") + "\0" + trimMsgText(ek.text || "")] = true;
    }
    // 从 olderMsgs 末尾开始去除与已有消息重叠的部分
    var cutIdx = olderMsgs.length;
    while (cutIdx > 0) {
      var om = olderMsgs[cutIdx - 1];
      var fp = (om.role || "") + "\0" + trimMsgText(om.text || "");
      if (fingerprintSet[fp]) {
        cutIdx--;
      } else {
        break;
      }
    }
    return cutIdx < olderMsgs.length ? olderMsgs.slice(0, cutIdx) : olderMsgs;
  }

  function mergeThinkStepsOntoLastAssistant(conv, steps, finalText) {
    if (!conv || !steps || !steps.length) return;
    var last = conv.messages[conv.messages.length - 1];
    if (!last || last.role !== "assistant") return;
    var F = trimMsgText(finalText != null ? finalText : last.text);
    last.thinkSteps = dedupeTrailingThinkSteps(
      cloneThinkStepsForDisplay(steps),
      F
    );
  }

  function backfillConversationTitleFromMessages(conv) {
    if (!conv) return;
    var derived = deriveConversationTitleFromMessages(conv.messages);
    if (!derived) return;
    if (String(conv.title || "").trim() === "新对话") {
      conv.title = derived;
    }
  }

  async function hydrateStateFromBackend() {
    var username = scopedUsername || currentUsername();
    if (!username) return { status: "failed", reason: "no_username" };
    try {
      var res = await fetch(
        apiBase + "/api/desktop/conversations?username=" + encodeURIComponent(username),
        { method: "GET", cache: "no-store" }
      );
      if (!res.ok) return { status: "failed", reason: "http_" + res.status };
      var data = await res.json();
      var convs = Array.isArray(data && data.conversations) ? data.conversations : [];
      chatState = normalizeChatStateShape({
        version: 1,
        activeId: data && data.activeId ? data.activeId : convs[0] && convs[0].id,
        conversations: convs.map(function (c) {
          var stid = c.threadId || "";
          var conv = {
            id: c.id,
            title: normalizeConversationTitle(c.title || "新对话"),
            messages: [],
            threadId: c.threadId || "",
            sessionId: c.sessionId || "",
            updatedAt: normalizeUpdatedAt(c.updatedAt),
          };
          if (stid.indexOf("_sched_") >= 0) {
            conv._schedulerResultStatus = String(c.schedulerResultStatus || c.result_status || "").toLowerCase();
            conv._executionId = c.executionId || c.execution_id || "";
          }
          return conv;
        }),
      }) || { version: 1, activeId: null, conversations: [] };
      sortConversationsByRecency();
      // 登录进入时，默认优先打开「对话列表」中的最新会话；没有普通对话时再回退到定时任务。
      chatState.activeId = pickPreferredActiveConversationId();
      chatState._sidebarSyncSig = convs
        .map(function (c) {
          var stid = c.threadId || "";
          if (stid.indexOf("_sched_") >= 0) {
            return c.id + "|" + (c.updatedAt || 0) + "|" + (c.schedulerResultStatus || c.result_status || "");
          }
          return c.id;
        })
        .join("\0");

      var active = getActiveConversation();
      if (active) {
        var result = await loadMessagesFromBackend(active, { offset: 0, limit: 50 });
        active.messages = result.messages;
        active._msgOffset = result.nextOffset;
        active._msgTotal = result.total;
        active._msgHasMore = result.hasMore;
        backfillConversationTitleFromMessages(active);
      }
      renderConversationList();
      renderMessages();
      return { status: "loaded" };
    } catch (_e) {
      return { status: "failed", reason: "network_error" };
    }
  }

  /** 仅合并侧栏会话列表（如定时任务完成后插入的 feed），不打断当前会话中的消息缓存 */
  async function syncSidebarConversationsFromServer() {
    var username = scopedUsername || currentUsername();
    if (!username) return;
    if (document.visibilityState !== "visible") return;
    try {
      var res = await fetch(
        apiBase + "/api/desktop/conversations?username=" + encodeURIComponent(username),
        { method: "GET", cache: "no-store" }
      );
      if (!res.ok) return;
      var data = await res.json();
      var serverList = Array.isArray(data && data.conversations) ? data.conversations : [];
      var sig = serverList
        .map(function (s) {
          var stid = s.threadId || "";
          if (stid.indexOf("_sched_") >= 0) {
            return s.id + "|" + (s.updatedAt || 0) + "|" + (s.schedulerResultStatus || s.result_status || "");
          }
          return s.id;
        })
        .join("\0");
      if (sig === chatState._sidebarSyncSig) return;

      var seen = Object.create(null);
      var merged = [];
      var listChanged = false;
      var hasNewSchedulerConversation = false;

      for (var i = 0; i < serverList.length; i++) {
        var s = serverList[i];
        var id = s.id;
        seen[id] = true;
        var ex = null;
        for (var j = 0; j < chatState.conversations.length; j++) {
          if (chatState.conversations[j].id === id) {
            ex = chatState.conversations[j];
            break;
          }
        }
        var title = normalizeConversationTitle(s.title || "新对话");
        if (ex) {
          ex.updatedAt = Math.max(normalizeUpdatedAt(ex.updatedAt), normalizeUpdatedAt(s.updatedAt));
          var shouldKeepLocalTitle =
            title === "新对话" &&
            String(ex.title || "").trim() &&
            String(ex.title || "").trim() !== "新对话";
          if (!shouldKeepLocalTitle && ex.title !== title) {
            ex.title = title;
            listChanged = true;
          }

          var stid = s.threadId || "";
          if (stid.indexOf("_sched_") >= 0) {
            var newStatus = String(s.schedulerResultStatus || s.result_status || "").toLowerCase();
            var oldStatus = String(ex._schedulerResultStatus || "").toLowerCase();
            ex._schedulerResultStatus = newStatus;
            ex._executionId = s.executionId || s.execution_id || "";

            if (newStatus && newStatus !== oldStatus) {
              listChanged = true;
              var isActive = chatState.activeId === ex.id;
              loadMessagesFromBackend(ex).then(function (res) {
                ex.messages = res.messages;
                ex._msgOffset = res.nextOffset;
                ex._msgTotal = res.total;
                ex._msgHasMore = res.hasMore;
                renderConversationList();
                if (isActive) renderMessages();
              });
            }
          }

          merged.push(ex);
        } else {
          listChanged = true;
          var nc = {
            id: id,
            title: title,
            messages: [],
            threadId: s.threadId || "",
            sessionId: s.sessionId || "",
            updatedAt: normalizeUpdatedAt(s.updatedAt),
          };
          var stidNew = s.threadId || "";
          if (stidNew.indexOf("_sched_") >= 0) {
            nc._schedulerResultStatus = String(s.schedulerResultStatus || s.result_status || "").toLowerCase();
            nc._executionId = s.executionId || s.execution_id || "";
          }
          merged.push(nc);
          var stid = s.threadId || "";
          if (stid.indexOf("_sched_") >= 0) {
            hasNewSchedulerConversation = true;
            var exId = s.executionId || s.execution_id || "";
            if (!shouldSuppressSchedulerFeedToast(exId)) {
              var st = String(
                s.schedulerResultStatus || s.result_status || "success"
              ).toLowerCase();
              var tail = exId ? " 记录：" + exId : "";
              if (st === "success") {
                showToast("执行已完成。" + tail, {
                  type: "success",
                  duration: 5000,
                });
              } else if (st === "running") {
                /* 初次写入状态为 running，表明任务刚刚开始；不弹 toast，避免误报"执行失败" */
              } else {
                showToast(
                  "执行失败：" + (title && title !== "新对话" ? title : "定时任务") + tail,
                  { type: "error", duration: 6000 }
                );
              }
            }
          }
          loadMessagesFromBackend(nc).then(function (res) {
            nc.messages = res.messages;
            nc._msgOffset = res.nextOffset;
            nc._msgTotal = res.total;
            nc._msgHasMore = res.hasMore;
            backfillConversationTitleFromMessages(nc);
            renderConversationList();
            if (chatState.activeId === nc.id) renderMessages();
          });
        }
      }

      for (var k = 0; k < chatState.conversations.length; k++) {
        var c = chatState.conversations[k];
        if (!seen[c.id]) merged.push(c);
      }

      chatState.conversations = merged;
      sortConversationsByRecency();
      if (
        !chatState.activeId ||
        !chatState.conversations.some(function (x) {
          return x && x.id === chatState.activeId;
        })
      ) {
        chatState.activeId = pickPreferredActiveConversationId();
      }
      chatState._sidebarSyncSig = sig;
      if (hasNewSchedulerConversation) setSchedulerSectionExpanded(true);
      if (listChanged) renderConversationList();
    } catch (_e) {
      /* ignore */
    }
  }

  var sidebarPollTimer = null;
  var SIDEBAR_POLL_MS = 5000;

  function startSidebarAutoRefresh(intervalMs) {
    stopSidebarAutoRefresh();
    if (!intervalMs || intervalMs < 2000) intervalMs = SIDEBAR_POLL_MS;
    sidebarPollTimer = window.setInterval(function () {
      syncSidebarConversationsFromServer();
    }, intervalMs);
  }

  function stopSidebarAutoRefresh() {
    if (sidebarPollTimer != null) {
      window.clearInterval(sidebarPollTimer);
      sidebarPollTimer = null;
    }
  }


  function ensureThreadSession(conv) {
    if (!conv) return;
    if (!conv.threadId) conv.threadId = generateSessionId("thread");
    // sessionId 现在在每次发送新消息时生成，不需要强制为空
  }

  async function setScopedUser(username) {
    var nextUser = normalizeUsername(username);
    if (nextUser === scopedUsername) return { status: "unchanged" };
    stopSidebarAutoRefresh();
    scopedUsername = nextUser;
    chatState = { version: 1, activeId: null, conversations: [] };
    renderConversationList();
    renderMessages();

    if (!scopedUsername) return { status: "guest" };
    var ret = await hydrateStateFromBackend();
    startSidebarAutoRefresh(SIDEBAR_POLL_MS);
    return ret || { status: "failed", reason: "unknown" };
  }

  function getActiveConversation() {
    if (!chatState.activeId) return null;
    return chatState.conversations.find(function (c) {
      return c.id === chatState.activeId;
    });
  }

  function setComposerBusy(busy) {
    var ta = document.getElementById("composer-input");
    var send = document.getElementById("btn-send");
    var inner = document.querySelector(".composer-inner");
    if (ta) ta.disabled = !!busy;
    if (send) {
      send.disabled = false;
      send.textContent = busy ? "⏹" : "➤";
      send.title = busy ? "中断当前任务" : "发送";
      send.classList.toggle("send-btn-stop", !!busy);
    }
    if (inner) inner.classList.toggle("composer-busy", !!busy);
  }

  async function uploadDesktopFiles(files) {
    var username = scopedUsername || currentUsername();
    if (!username) {
      throw new Error("请先登录后再上传附件");
    }
    var fd = new FormData();
    fd.append("username", username);
    for (var i = 0; i < files.length; i++) {
      fd.append("files", files[i]);
    }
    var res = await fetch(apiBase + "/api/desktop/upload", {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      var t = await res.text();
      throw new Error(String(res.status) + (t ? ": " + t : ""));
    }
    var data = await res.json();
    if (!data || !data.ok) {
      throw new Error((data && data.message) || "上传失败");
    }
    return Array.isArray(data.paths) ? data.paths : [];
  }

  function renderAttachmentChips() {
    var wrap = document.getElementById("composer-attachments");
    if (!wrap) return;
    wrap.innerHTML = "";
    if (!pendingFiles.length) {
      wrap.classList.add("hidden");
      return;
    }
    wrap.classList.remove("hidden");
    pendingFiles.forEach(function (file) {
      var chip = document.createElement("span");
      chip.className = "attachment-chip";
      var nameEl = document.createElement("span");
      nameEl.className = "attachment-chip-name";
      nameEl.textContent = file.name || "file";
      var x = document.createElement("button");
      x.type = "button";
      x.className = "attachment-chip-remove";
      x.setAttribute("aria-label", "移除附件");
      x.textContent = "×";
      x.addEventListener("click", function (e) {
        e.preventDefault();
        pendingFiles = pendingFiles.filter(function (f) {
          return f !== file;
        });
        renderAttachmentChips();
      });
      chip.appendChild(nameEl);
      chip.appendChild(x);
      wrap.appendChild(chip);
    });
  }

  function filenameSuffix(name) {
    var n = String(name || "");
    var idx = n.lastIndexOf(".");
    if (idx < 0) return "";
    return n.slice(idx).toLowerCase();
  }

  function isAllowedAttachmentFile(file) {
    var suffix = filenameSuffix(file && file.name);
    return !!ATTACHMENT_ALLOWED_SUFFIXES[suffix];
  }

  function fileIdentity(file) {
    if (!file) return "";
    return [
      String(file.name || "").toLowerCase(),
      String(file.size || 0),
      String(file.lastModified || 0),
    ].join("__");
  }

  function addPendingFilesFromList(fileList) {
    if (!fileList || !fileList.length) return;
    var existing = Object.create(null);
    pendingFiles.forEach(function (f) {
      existing[fileIdentity(f)] = true;
    });
    var blocked = [];
    for (var i = 0; i < fileList.length; i++) {
      var f = fileList[i];
      if (!isAllowedAttachmentFile(f)) {
        blocked.push(f && f.name ? f.name : "unknown");
        continue;
      }
      var key = fileIdentity(f);
      if (existing[key]) continue;
      if (pendingFiles.length >= ATTACHMENT_MAX_FILES) {
        showToast("附件最多支持 " + ATTACHMENT_MAX_FILES + " 个", {
          type: "error",
          duration: 3500,
        });
        break;
      }
      existing[key] = true;
      pendingFiles.push(f);
    }
    if (blocked.length) {
      var preview = blocked.slice(0, 3).join("、");
      var suffix = blocked.length > 3 ? " 等" + blocked.length + " 个" : "";
      showToast("文件格式暂不支持：" + preview + suffix, {
        type: "error",
        duration: 5200,
      });
    }
    renderAttachmentChips();
  }

  function bindAttachmentUi() {
    var btn = document.getElementById("btn-attach");
    var fi = document.getElementById("composer-file-input");
    var composerInner = document.querySelector(".composer-inner");
    if (!btn || !fi) return;
    btn.addEventListener("click", function () {
      fi.click();
    });
    fi.addEventListener("change", function () {
      addPendingFilesFromList(fi.files);
      fi.value = "";
    });
    if (!composerInner) return;
    function preventDefaults(e) {
      e.preventDefault();
      e.stopPropagation();
    }
    function setDragActive(active) {
      composerInner.classList.toggle("composer-dragover", !!active);
    }
    ["dragenter", "dragover"].forEach(function (eventName) {
      composerInner.addEventListener(eventName, function (e) {
        preventDefaults(e);
        setDragActive(true);
      });
    });
    ["dragleave", "dragend", "drop"].forEach(function (eventName) {
      composerInner.addEventListener(eventName, function (e) {
        preventDefaults(e);
        if (eventName === "drop") {
          var dt = e.dataTransfer;
          var files = dt && dt.files ? dt.files : null;
          if (files && files.length) addPendingFilesFromList(files);
        }
        setDragActive(false);
      });
    });
  }

  /* ========== 知识库选择面板 ========== */
  var pendingKnowledgeFiles = [];
  var pendingKnowledgeCategories = [];
  var knowledgePanelVisible = false;
  var knowledgePanelEl = null;

  function bindKnowledgeUi() {
    var btn = document.getElementById("btn-knowledge");
    if (!btn) return;
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleKnowledgePanel();
    });
  }

  function toggleKnowledgePanel() {
    if (knowledgePanelVisible) {
      closeKnowledgePanel();
    } else {
      openKnowledgePanel();
    }
  }

  function openKnowledgePanel() {
    if (knowledgePanelEl) {
      knowledgePanelEl.remove();
      knowledgePanelEl = null;
    }

    var panel = document.createElement("div");
    panel.className = "knowledge-picker-panel";
    panel.innerHTML = '<div class="knowledge-picker-loading">加载中...</div>';
    document.body.appendChild(panel);
    knowledgePanelEl = panel;
    knowledgePanelVisible = true;

    loadKnowledgeData().then(function (data) {
      renderKnowledgePanel(data);
    }).catch(function () {
      renderKnowledgePanel({ categories: [], files: [] });
    });

    setTimeout(function () {
      document.addEventListener("click", closeKnowledgePanelOnOutsideClick);
    }, 0);
  }

  function closeKnowledgePanel() {
    if (knowledgePanelEl) {
      knowledgePanelEl.remove();
      knowledgePanelEl = null;
    }
    knowledgePanelVisible = false;
    document.removeEventListener("click", closeKnowledgePanelOnOutsideClick);
  }

  function closeKnowledgePanelOnOutsideClick(e) {
    if (knowledgePanelEl && !knowledgePanelEl.contains(e.target)) {
      var btn = document.getElementById("btn-knowledge");
      if (btn && btn.contains(e.target)) return;
      closeKnowledgePanel();
    }
  }

  async function loadKnowledgeData() {
    var username = scopedUsername || currentUsername();
    var uParam = username ? "&username=" + encodeURIComponent(username) : "";
    var categories = [];
    var files = [];

    // 加载个人知识库
    try {
      var catRes = await fetch(apiBase + "/knowledge/categories?type=personal" + uParam, { cache: "no-store" });
      var catData = await catRes.json();
      if (catData && catData.success) {
        var personalCats = (catData.categories || []).map(function (c) { c._kbType = "personal"; return c; });
        categories = categories.concat(personalCats);
      }
    } catch (_e) {}

    try {
      var fileRes = await fetch(apiBase + "/knowledge/files?type=personal" + uParam, { cache: "no-store" });
      var fileData = await fileRes.json();
      if (fileData && fileData.success) {
        var personalFiles = (fileData.files || []).map(function (f) { f._kbType = "personal"; return f; });
        files = files.concat(personalFiles);
      }
    } catch (_e) {}

    // 加载公司知识库
    try {
      var compCatRes = await fetch(apiBase + "/knowledge/categories?type=company" + uParam, { cache: "no-store" });
      var compCatData = await compCatRes.json();
      if (compCatData && compCatData.success) {
        var companyCats = (compCatData.categories || []).map(function (c) { c._kbType = "company"; c.display_name = "🏢 " + (c.display_name || c.name); return c; });
        categories = categories.concat(companyCats);
      }
    } catch (_e) {}

    try {
      var compFileRes = await fetch(apiBase + "/knowledge/files?type=company" + uParam, { cache: "no-store" });
      var compFileData = await compFileRes.json();
      if (compFileData && compFileData.success) {
        var companyFiles = (compFileData.files || []).map(function (f) { f._kbType = "company"; return f; });
        files = files.concat(companyFiles);
      }
    } catch (_e) {}

    return { categories: categories, files: files };
  }

  function renderKnowledgePanel(data) {
    if (!knowledgePanelEl) return;
    var categories = data.categories || [];
    var files = data.files || [];

    var html = '<div class="knowledge-picker-header">';
    html += '<span class="knowledge-picker-title">选择知识库</span>';
    html += '<button type="button" class="knowledge-picker-close" title="关闭">&times;</button>';
    html += '</div>';

    if (!categories.length && !files.length) {
      html += '<div class="knowledge-picker-empty">暂无知识库文件</div>';
    } else {
      html += '<div class="knowledge-picker-body">';
      categories.forEach(function (cat) {
        var catKbType = cat._kbType || "personal";
        var catFiles = files.filter(function (f) { return f.category === cat.name && (f._kbType || "personal") === catKbType; });
        if (!catFiles.length) return;
        var isCatSelected = pendingKnowledgeCategories.some(function (kc) { return kc.name === cat.name && (kc.kbType || "personal") === catKbType; });
        var allCatFileIds = catFiles.map(function (f) { return f.id; });
        var allCatFilesSelected = allCatFileIds.length > 0 && allCatFileIds.every(function (fid) {
          return pendingKnowledgeFiles.some(function (kf) { return kf.id === fid; });
        });
        html += '<div class="knowledge-picker-group">';
        html += '<label class="knowledge-picker-cat-row' + (isCatSelected || allCatFilesSelected ? " selected" : "") + '">';
        html += '<input type="checkbox" class="knowledge-picker-cat-checkbox" data-cat-name="' + escapeHtml(cat.name) + '" data-cat-display="' + escapeHtml(cat.display_name || cat.name) + '" data-kb-type="' + catKbType + '"' + (isCatSelected || allCatFilesSelected ? " checked" : "") + ' />';
        html += '<span class="knowledge-picker-cat-name">' + escapeHtml(cat.display_name || cat.name) + '</span>';
        html += '<span class="knowledge-picker-cat-count">' + catFiles.length + ' 个文件</span>';
        html += '</label>';
        html += '<div class="knowledge-picker-cat-files">';
        catFiles.forEach(function (f) {
          var displayName = f.md_filename ? f.md_filename.replace(/\.md$/i, "") : f.original_filename;
          var isSelected = pendingKnowledgeFiles.some(function (kf) { return kf.id === f.id; }) || isCatSelected;
          html += '<label class="knowledge-picker-item' + (isSelected ? " selected" : "") + '">';
          html += '<input type="checkbox" class="knowledge-picker-checkbox" data-file-id="' + f.id + '" data-file-name="' + escapeHtml(displayName) + '" data-cat-name="' + escapeHtml(cat.name) + '" data-kb-type="' + catKbType + '"' + (isSelected ? " checked" : "") + ' />';
          html += '<span class="knowledge-picker-item-name">' + escapeHtml(displayName) + '</span>';
          html += '</label>';
        });
        html += '</div>';
        html += '</div>';
      });

      var uncategorized = files.filter(function (f) {
        return !categories.some(function (c) { return c.name === f.category && (c._kbType || "personal") === (f._kbType || "personal"); });
      });
      if (uncategorized.length) {
        html += '<div class="knowledge-picker-group">';
        html += '<div class="knowledge-picker-group-title">未分类 (' + uncategorized.length + ')</div>';
        uncategorized.forEach(function (f) {
          var displayName = f.md_filename ? f.md_filename.replace(/\.md$/i, "") : f.original_filename;
          var isSelected = pendingKnowledgeFiles.some(function (kf) { return kf.id === f.id; });
          var fKbType = f._kbType || "personal";
          html += '<label class="knowledge-picker-item' + (isSelected ? " selected" : "") + '">';
          html += '<input type="checkbox" class="knowledge-picker-checkbox" data-file-id="' + f.id + '" data-file-name="' + escapeHtml(displayName) + '" data-kb-type="' + fKbType + '"' + (isSelected ? " checked" : "") + ' />';
          html += '<span class="knowledge-picker-item-name">' + escapeHtml(displayName) + '</span>';
          html += '</label>';
        });
        html += '</div>';
      }

      html += '</div>';
    }

    knowledgePanelEl.innerHTML = html;

    var closeBtn = knowledgePanelEl.querySelector(".knowledge-picker-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        closeKnowledgePanel();
      });
    }

    var catCheckboxes = knowledgePanelEl.querySelectorAll(".knowledge-picker-cat-checkbox");
    for (var ci = 0; ci < catCheckboxes.length; ci++) {
      catCheckboxes[ci].addEventListener("change", function () {
        var catName = this.getAttribute("data-cat-name");
        var catDisplay = this.getAttribute("data-cat-display");
        var catKbType = this.getAttribute("data-kb-type") || "personal";
        if (this.checked) {
          if (!pendingKnowledgeCategories.some(function (kc) { return kc.name === catName && (kc.kbType || "personal") === catKbType; })) {
            pendingKnowledgeCategories.push({ name: catName, display_name: catDisplay, kbType: catKbType });
          }
          var group = this.closest(".knowledge-picker-group");
          if (group) {
            var fileCbs = group.querySelectorAll(".knowledge-picker-checkbox");
            for (var fi = 0; fi < fileCbs.length; fi++) {
              var fid = fileCbs[fi].getAttribute("data-file-id");
              var fname = fileCbs[fi].getAttribute("data-file-name");
              if (!pendingKnowledgeFiles.some(function (kf) { return kf.id === fid; })) {
                pendingKnowledgeFiles.push({ id: fid, name: fname });
              }
              fileCbs[fi].checked = true;
              var lbl = fileCbs[fi].closest(".knowledge-picker-item");
              if (lbl) lbl.classList.add("selected");
            }
          }
        } else {
          pendingKnowledgeCategories = pendingKnowledgeCategories.filter(function (kc) { return !(kc.name === catName && (kc.kbType || "personal") === catKbType); });
          var group2 = this.closest(".knowledge-picker-group");
          if (group2) {
            var fileCbs2 = group2.querySelectorAll(".knowledge-picker-checkbox");
            for (var fj = 0; fj < fileCbs2.length; fj++) {
              var fid2 = fileCbs2[fj].getAttribute("data-file-id");
              pendingKnowledgeFiles = pendingKnowledgeFiles.filter(function (kf) { return kf.id !== fid2; });
              fileCbs2[fj].checked = false;
              var lbl2 = fileCbs2[fj].closest(".knowledge-picker-item");
              if (lbl2) lbl2.classList.remove("selected");
            }
          }
        }
        renderKnowledgeChips();
        var catRow = this.closest(".knowledge-picker-cat-row");
        if (catRow) catRow.classList.toggle("selected", this.checked);
      });
    }

    var checkboxes = knowledgePanelEl.querySelectorAll(".knowledge-picker-checkbox");
    for (var i = 0; i < checkboxes.length; i++) {
      checkboxes[i].addEventListener("change", function () {
        var fileId = this.getAttribute("data-file-id");
        var fileName = this.getAttribute("data-file-name");
        var fileCatName = this.getAttribute("data-cat-name");
        if (this.checked) {
          if (!pendingKnowledgeFiles.some(function (kf) { return kf.id === fileId; })) {
            pendingKnowledgeFiles.push({ id: fileId, name: fileName });
          }
        } else {
          pendingKnowledgeFiles = pendingKnowledgeFiles.filter(function (kf) { return kf.id !== fileId; });
          if (fileCatName) {
            var fileKbType = this.getAttribute("data-kb-type") || "personal";
            pendingKnowledgeCategories = pendingKnowledgeCategories.filter(function (kc) { return !(kc.name === fileCatName && (kc.kbType || "personal") === fileKbType); });
            var group3 = this.closest(".knowledge-picker-group");
            if (group3) {
              var catCb = group3.querySelector(".knowledge-picker-cat-checkbox");
              if (catCb) {
                catCb.checked = false;
                var catRow2 = catCb.closest(".knowledge-picker-cat-row");
                if (catRow2) catRow2.classList.remove("selected");
              }
            }
          }
        }
        renderKnowledgeChips();
        var label = this.closest(".knowledge-picker-item");
        if (label) label.classList.toggle("selected", this.checked);
      });
    }
  }

  function renderKnowledgeChips() {
    var wrap = document.getElementById("composer-knowledge-chips");
    if (!wrap) return;
    wrap.innerHTML = "";
    if (!pendingKnowledgeFiles.length && !pendingKnowledgeCategories.length) {
      wrap.classList.add("hidden");
      return;
    }
    wrap.classList.remove("hidden");
    pendingKnowledgeCategories.forEach(function (kc) {
      var chip = document.createElement("span");
      chip.className = "knowledge-chip knowledge-chip-cat";
      var nameEl = document.createElement("span");
      nameEl.className = "knowledge-chip-name";
      nameEl.textContent = kc.display_name || kc.name;
      var x = document.createElement("button");
      x.type = "button";
      x.className = "knowledge-chip-remove";
      x.setAttribute("aria-label", "移除知识库分类");
      x.textContent = "×";
      x.addEventListener("click", function (e) {
        e.preventDefault();
        pendingKnowledgeCategories = pendingKnowledgeCategories.filter(function (k) { return k.name !== kc.name; });
        renderKnowledgeChips();
      });
      chip.appendChild(nameEl);
      chip.appendChild(x);
      wrap.appendChild(chip);
    });
    pendingKnowledgeFiles.forEach(function (kf) {
      var isFromCat = pendingKnowledgeCategories.some(function (kc) {
        return kf.category === kc.name;
      });
      if (isFromCat) return;
      var chip = document.createElement("span");
      chip.className = "knowledge-chip";
      var nameEl = document.createElement("span");
      nameEl.className = "knowledge-chip-name";
      nameEl.textContent = kf.name || kf.id;
      var x = document.createElement("button");
      x.type = "button";
      x.className = "knowledge-chip-remove";
      x.setAttribute("aria-label", "移除知识库文件");
      x.textContent = "×";
      x.addEventListener("click", function (e) {
        e.preventDefault();
        pendingKnowledgeFiles = pendingKnowledgeFiles.filter(function (k) { return k.id !== kf.id; });
        renderKnowledgeChips();
      });
      chip.appendChild(nameEl);
      chip.appendChild(x);
      wrap.appendChild(chip);
    });
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  /* ========== 知识库选择面板 END ========== */

  function pad2(n) {
    return n < 10 ? "0" + n : "" + n;
  }

  function bindPasteAttachmentHandler() {
    var ta = document.getElementById("composer-input");
    if (!ta) return;

    ta.addEventListener("paste", function (e) {
      var cd = e.clipboardData;
      if (!cd) return;

      var files = [];
      var hasFileOrImage = false;

      // 方式1：从 clipboardData.files 获取文件（适用于从文件管理器复制的文件）
      if (cd.files && cd.files.length) {
        for (var i = 0; i < cd.files.length; i++) {
          files.push(cd.files[i]);
        }
        hasFileOrImage = true;
      }

      // 方式2：从 clipboardData.items 获取图片数据（适用于截图等场景，
      // 部分浏览器/环境下 clipboardData.files 可能不包含截图图片）
      if (!hasFileOrImage && cd.items) {
        for (var j = 0; j < cd.items.length; j++) {
          var item = cd.items[j];
          if (item.kind === "file" && item.type.indexOf("image/") === 0) {
            var blob = item.getAsFile();
            if (blob) {
              // 为截图生成带时间戳的文件名
              var now = new Date();
              var ts = now.getFullYear()
                + pad2(now.getMonth() + 1)
                + pad2(now.getDate())
                + "_"
                + pad2(now.getHours())
                + pad2(now.getMinutes())
                + pad2(now.getSeconds());
              var ext = item.type === "image/png" ? ".png" : ".jpg";
              var screenshotFile = new File([blob], "screenshot_" + ts + ext, {
                type: item.type,
              });
              files.push(screenshotFile);
              hasFileOrImage = true;
            }
          }
        }
      }

      // 如果剪贴板中有文件或图片，阻止默认文本粘贴行为，改为添加附件
      if (files.length > 0) {
        e.preventDefault();
        e.stopPropagation();
        addPendingFilesFromList(files);
      }
      // 纯文本粘贴不做任何拦截，保持原有行为
    });
  }

  function extractXmlInjectedFields(userInput) {
    var text = String(userInput || "");
    var skillsNames = [];
    var mcpToolNames = [];
    var skillsRe = /<skills>([\s\S]*?)<\/skills>/g;
    var mcpRe = /<mcp-tools>([\s\S]*?)<\/mcp-tools>/g;
    var m;
    while ((m = skillsRe.exec(text)) !== null) {
      var names = m[1].split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      skillsNames = skillsNames.concat(names);
    }
    while ((m = mcpRe.exec(text)) !== null) {
      var names2 = m[1].split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      mcpToolNames = mcpToolNames.concat(names2);
    }
    var cleaned = text.replace(/<skills>[\s\S]*?<\/skills>\s*/g, "").replace(/<mcp-tools>[\s\S]*?<\/mcp-tools>\s*/g, "");
    return { text: cleaned.trim(), skillsNames: skillsNames, mcpToolNames: mcpToolNames };
  }

  function streamQuotation(conv, userInput, attachmentPaths, sseOptions, abortSignal, resumeCommand, knowledgeFileIds, knowledgeCategoryNames) {
    ensureThreadSession(conv);
    var username = "Workmate";
    var sess = getSession();
    if (sess && sess.user && sess.user.username) {
      username = sess.user.username;
    }
    // 从文本中提取skills/mcp-tools，作为payload字段传递，不再混入user_input
    var extracted = extractXmlInjectedFields(userInput);
    var taggedInput = "【workmate桌面端】" + (extracted.text || "(无)");
    var payload = {
      user_input: taggedInput,
      chat_history: [],
      thread_id: conv.threadId,
      sessionId: conv.sessionId,
      mode: 0,
      username: username,
      wechat_context: "",
      contact_name: "",
    };
    if (attachmentPaths && attachmentPaths.length) {
      payload.attachment_paths = attachmentPaths;
    }
    if (resumeCommand != null) {
      payload.resume_command = resumeCommand;
    }
    if (knowledgeFileIds && knowledgeFileIds.length) {
      payload.knowledge_file_ids = knowledgeFileIds;
    }
    if (knowledgeCategoryNames && knowledgeCategoryNames.length) {
      payload.knowledge_category_names = knowledgeCategoryNames;
    }
    if (extracted.skillsNames.length) {
      payload.skills_names = extracted.skillsNames;
    }
    if (extracted.mcpToolNames.length) {
      payload.mcp_tool_names = extracted.mcpToolNames;
    }
    return fetch(apiBase + "/quotation", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(payload),
      signal: abortSignal,
    }).then(function (res) {
      if (!res.ok) {
        return res.text().then(function (t) {
          throw new Error(res.status + (t ? ": " + t : ""));
        });
      }
      return parseQuotationSSE(res.body, sseOptions || {});
    });
  }

  async function requestServerStop(conv) {
    if (!conv) return;
    try {
      await fetch(apiBase + "/api/desktop/conversations/" + encodeURIComponent(conv.threadId || "") + "/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: scopedUsername || currentUsername(),
          session_id: conv.sessionId || "",
        }),
      });
    } catch (_e) {
      // 忽略网络错误，仍会执行本地 abort
    }
  }

  async function stopComposerRequest() {
    if (!quotationInFlight) return;
    quotationStopRequested = true;
    var conv = getActiveConversation();
    if (conv && quotationInFlightConvId && conv.id !== quotationInFlightConvId) {
      conv = chatState.conversations.find(function (c) {
        return c.id === quotationInFlightConvId;
      }) || conv;
    }
    await requestServerStop(conv);
    if (quotationAbortController) {
      try {
        quotationAbortController.abort();
      } catch (_e) {}
    }
  }

  function resumeWithHITL(conv, command, attachmentPaths) {
    if (!conv) return;
    var resumeCommand = Object.assign({}, command);
    if (attachmentPaths && attachmentPaths.length) {
      resumeCommand.attachments = attachmentPaths;
    }

    quotationInFlight = true;
    quotationStopRequested = false;
    quotationInFlightConvId = conv.id;
    quotationAbortController = new AbortController();
    setComposerBusy(true);

    conv.messages.push({
      role: "assistant",
      text: "正在继续执行…",
      streaming: true,
      thinkSteps: [],
      _pendingThinkHints: [],
      timestamp: Date.now(),
    });
    conv._msgHasMore = false;
    touchConversation(conv);
    renderMessages();

    function applyThinkStep(ev) {
      var last = conv.messages[conv.messages.length - 1];
      if (!last || last.role !== "assistant" || !last.streaming) return;
      ingestThinkStreamEvent(last, ev);
      last.text = "正在继续执行…";
      renderMessages();
    }

    streamQuotation(conv, "", [], {
      onEvent: function (ev) { applyThinkStep(ev); },
      onHITLWait: function (ev) {
        quotationInFlight = false;
        quotationInFlightConvId = null;
        setComposerBusy(false);
        var last = conv.messages[conv.messages.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          last.text = last.text === "正在继续执行…" ? "等待您的确认…" : last.text;
          delete last.streaming;
        }
        renderMessages();
        hitlManager.show(ev, conv);
      },
    }, quotationAbortController.signal, resumeCommand)
      .then(function (finalContent) {
        var last = conv.messages[conv.messages.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          var F = finalContent != null ? String(finalContent).trim() : "";
          var prev = trimMsgText(last.text);
          last.text = F ? finalContent : prev || "（本次未返回文本内容）";
          last.timestamp = Date.now();
          delete last.streaming;
        }
        clearThinkStreamState(last);
        touchConversation(conv);
        return fetchThinkStepsFromBackend(conv).then(function (steps) {
          mergeThinkStepsOntoLastAssistant(conv, steps, finalContent);
          renderMessages();
          return notifyAssistantStreamDone(conv, finalContent);
        });
      })
      .catch(function (err) {
        var last = conv.messages[conv.messages.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          clearThinkStreamState(last);
          last.text = "恢复执行失败：" + (err && err.message ? err.message : String(err));
          last.timestamp = Date.now();
          delete last.streaming;
        }
        touchConversation(conv);
      })
      .finally(function () {
        quotationInFlight = false;
        quotationInFlightConvId = null;
        persistChatState();
        renderMessages();
        setComposerBusy(false);
      });
  }

  function maybeRenameFromFirstMessage(conv, text) {
    if (conv.title !== "新对话") return;
    var t = trimMsgText(normalizeDisplayMessageText(text));
    if (!t) return;
    var max = 28;
    conv.title = t.length > max ? t.slice(0, max) + "…" : t;
  }

  function closeConversationMenu() {
    openMenuConvId = null;
    document.querySelectorAll(".history-dropdown").forEach(function (el) {
      el.classList.add("hidden");
    });
    document.querySelectorAll(".history-row.menu-open").forEach(function (el) {
      el.classList.remove("menu-open");
    });
  }

  function closeConfirmDialog(result) {
    if (confirmOverlay.classList.contains("hidden")) return;
    confirmOverlay.classList.add("hidden");
    confirmOverlay.setAttribute("aria-hidden", "true");
    var fn = confirmDialogResolve;
    confirmDialogResolve = null;
    if (fn) fn(!!result);
  }

  function showConfirmDialog(opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      confirmDialogResolve = resolve;
      confirmTitleEl.textContent = opts.title != null ? opts.title : "确认";
      confirmDescEl.textContent = opts.message != null ? opts.message : "";
      confirmBtnOk.textContent = opts.confirmText != null ? opts.confirmText : "确定";
      confirmBtnCancel.textContent = opts.cancelText != null ? opts.cancelText : "取消";
      confirmOverlay.classList.remove("hidden");
      confirmOverlay.setAttribute("aria-hidden", "false");
      confirmBtnOk.focus();
    });
  }

  function bindConfirmDialog() {
    confirmBtnOk.addEventListener("click", function () {
      closeConfirmDialog(true);
    });
    confirmBtnCancel.addEventListener("click", function () {
      closeConfirmDialog(false);
    });
    confirmOverlay.addEventListener("click", function (e) {
      if (e.target === confirmOverlay) closeConfirmDialog(false);
    });
  }

  function detectAssistantMessageState(text) {
    var t = trimMsgText(text);
    if (!t) return "";
    if (t.indexOf("请求失败：") === 0) return "error";
    if (t === "已中断当前任务") return "stopped";
    if (t === "（本次未返回文本内容）") return "empty";
    return "";
  }

  function assistantStateMetaLabel(stateType) {
    if (stateType === "error") return "⚠ 请求失败";
    if (stateType === "stopped") return "⏹ 已中断";
    if (stateType === "empty") return "ℹ 无文本返回";
    return "";
  }

  function renderAssistantThinkAndReply(displayRow) {
    var stack = document.createElement("div");
    stack.className = "assistant-stack";

    var thinkStepsRaw = displayRow.thinkSteps;
    var deduped = dedupeTrailingThinkSteps(thinkStepsRaw, displayRow.text);
    var showThinkPanel = deduped.length > 0 || !!displayRow.streaming;

    if (showThinkPanel) {
      var details = document.createElement("details");
      details.className = "agent-think-panel";
      // 仅思考进行中展开；完成后默认收起
      details.open = !!displayRow.streaming;

      var summary = document.createElement("summary");
      summary.className = "agent-think-summary";
      var titleSpan = document.createElement("span");
      titleSpan.className = "agent-think-title";
      titleSpan.textContent = displayRow.streaming ? "思考中…" : "已完成思考";
      var metaSpan = document.createElement("span");
      metaSpan.className = "agent-think-meta";
      metaSpan.textContent = deduped.length
        ? "（" + deduped.length + " 步）"
        : displayRow.streaming
          ? ""
          : "";
      var chev = document.createElement("span");
      chev.className = "agent-think-chevron";
      chev.setAttribute("aria-hidden", "true");
      summary.appendChild(titleSpan);
      summary.appendChild(metaSpan);
      summary.appendChild(chev);

      var body = document.createElement("div");
      body.className = "agent-think-body";
      if (deduped.length) {
        var ul = document.createElement("ul");
        ul.className = "agent-think-list";
        deduped.forEach(function (stepText, idx) {
          var li = document.createElement("li");
          var stepNum = document.createElement("span");
          stepNum.className = "agent-think-step-num";
          stepNum.textContent = String(idx + 1);
          var stepBody = document.createElement("div");
          stepBody.className = "agent-think-step-text";
          stepBody.textContent = stepText;
          li.appendChild(stepNum);
          li.appendChild(stepBody);
          ul.appendChild(li);
        });
        body.appendChild(ul);
      } else if (displayRow.streaming) {
        var pending = document.createElement("div");
        pending.className = "agent-think-pending";
        pending.textContent = "正在整理执行过程…";
        body.appendChild(pending);
      }
      details.appendChild(summary);
      details.appendChild(body);
      stack.appendChild(details);
    }

    var bubble = document.createElement("div");
    bubble.className = "bubble assistant-bubble";
    var md = document.createElement("div");
    md.className = "md-body";
    bubble.appendChild(md);

    var bodyText = trimMsgText(displayRow.text);
    if (displayRow.streaming && !bodyText) {
      bubble.classList.add("assistant-bubble-streaming");
      md.textContent = "…";
    } else if (displayRow.streaming) {
      bubble.classList.add("assistant-bubble-streaming");
      md.textContent = displayRow.text != null ? displayRow.text : "";
    } else if (bodyText) {
      var stateType = detectAssistantMessageState(bodyText);
      if (stateType) {
        bubble.classList.add("assistant-bubble-state");
        bubble.classList.add("assistant-bubble-state-" + stateType);
        var meta = document.createElement("div");
        meta.className = "assistant-state-meta";
        meta.textContent = assistantStateMetaLabel(stateType);
        bubble.insertBefore(meta, md);
      }
      md.innerHTML = assistantMarkdownToHtml(displayRow.text, {
        workspaceRoot: workspaceRoot,
      });
    } else {
      md.textContent = "";
    }

    stack.appendChild(bubble);
    return stack;
  }

  function renderMessages() {
    if (!messagesEl) return;
    var conv = getActiveConversation();
    messagesEl.innerHTML = "";
    if (!conv || !conv.messages.length) {
      var empty = document.createElement("div");
      empty.className = "chat-empty-hint";
      empty.textContent = "暂无消息，在下方输入开始对话。";
      messagesEl.appendChild(empty);
      return;
    }

    // 如果有更多历史消息可加载，在顶部渲染「加载更多」提示
    // 默认隐藏，通过滚动事件监听器控制显隐：拖动到最上方时显示
    if (conv._msgHasMore) {
      var loadMoreRow = document.createElement("div");
      loadMoreRow.className = "load-more-row hidden";
      loadMoreRow.id = "load-more-hint";
      var loadMoreText = document.createElement("span");
      loadMoreText.className = "load-more-text";
      loadMoreText.textContent = "加载更多…";
      var remainingHint = "";
      if (typeof conv._msgTotal === "number" && conv._msgTotal > 0 && typeof conv._msgOffset === "number") {
        var remaining = conv._msgTotal - (conv._msgOffset || 0);
        if (remaining > 0) {
          remainingHint = "（约 " + remaining + " 条）";
        }
      }
      loadMoreText.title = remainingHint;
      loadMoreText.setAttribute("aria-label", "加载更早的历史消息" + remainingHint);
      // 点击加载更多
      loadMoreText.addEventListener("click", function (e) {
        e.preventDefault();
        if (loadMoreText.classList.contains("loading")) return;
        loadMoreText.textContent = "加载中…";
        loadMoreText.classList.add("loading");
        // 记录加载前的滚动容器高度，用于加载后定位到新增内容顶部
        var area = messagesEl.parentElement;
        var beforeHeight = area ? area.scrollHeight : 0;
        loadMoreMessages(conv).then(function () {
          renderMessages();
          // 将滚动位置停留在新增内容的最上方
          if (area) {
            var newContentHeight = area.scrollHeight - beforeHeight;
            area.scrollTop = Math.max(0, newContentHeight);
          }
        }).catch(function () {
          loadMoreText.textContent = "加载更多…";
          loadMoreText.classList.remove("loading");
        });
      });
      loadMoreRow.appendChild(loadMoreText);
      messagesEl.appendChild(loadMoreRow);
    }

    var displayRows = buildMessageDisplayRows(conv.messages);
    displayRows.forEach(function (dr) {
      var row = document.createElement("div");
      if (dr.kind === "user") {
        row.className = "msg-row user";
        var userStack = document.createElement("div");
        userStack.className = "user-stack";

        var hasKnowledgeContent = !!dr.knowledgeContent;
        var hasAttachmentContent = !!dr.attachmentContent;
        var hasAttachmentNames = Array.isArray(dr.attachmentNames) && dr.attachmentNames.length > 0;
        var hasKnowledgeNames = Array.isArray(dr.knowledgeNames) && dr.knowledgeNames.length > 0;
        var hasMcpTools = Array.isArray(dr.mcpTools) && dr.mcpTools.length > 0;
        var hasSkills = Array.isArray(dr.skills) && dr.skills.length > 0;
        var hasExtraContext = !!dr.extraContext;

        // 附件区域
        if (hasAttachmentContent) {
          // 历史消息：折叠面板显示附件内容
          var attPanel = document.createElement("details");
          attPanel.className = "user-extra-panel user-attachment-panel";
          var attSummary = document.createElement("summary");
          attSummary.className = "user-extra-summary";
          var attTitle = document.createElement("span");
          attTitle.className = "user-extra-title";
          attTitle.textContent = "📎 附件";
          var attChev = document.createElement("span");
          attChev.className = "user-extra-chevron";
          attChev.setAttribute("aria-hidden", "true");
          attSummary.appendChild(attTitle);
          attSummary.appendChild(attChev);
          var attBody = document.createElement("div");
          attBody.className = "user-extra-body";
          var attBlock = document.createElement("pre");
          attBlock.className = "user-extra-context";
          attBlock.textContent = dr.attachmentContent;
          attBody.appendChild(attBlock);
          attPanel.appendChild(attSummary);
          attPanel.appendChild(attBody);
          userStack.appendChild(attPanel);
        } else if (hasAttachmentNames) {
          // 思考过程：纯文本标签显示附件名
          var attMeta = document.createElement("div");
          attMeta.className = "user-meta-tag user-attachment-meta";
          attMeta.textContent = "附件：" + dr.attachmentNames.join("、");
          userStack.appendChild(attMeta);
        }

        // 知识库区域
        if (hasKnowledgeContent) {
          // 历史消息：折叠面板显示知识库摘要
          var kbPanel = document.createElement("details");
          kbPanel.className = "user-extra-panel user-knowledge-panel";
          var kbSummary = document.createElement("summary");
          kbSummary.className = "user-extra-summary";
          var kbTitle = document.createElement("span");
          kbTitle.className = "user-extra-title";
          kbTitle.textContent = "📚 知识库";
          var kbChev = document.createElement("span");
          kbChev.className = "user-extra-chevron";
          kbChev.setAttribute("aria-hidden", "true");
          kbSummary.appendChild(kbTitle);
          kbSummary.appendChild(kbChev);
          var kbBody = document.createElement("div");
          kbBody.className = "user-extra-body";
          var kbBlock = document.createElement("pre");
          kbBlock.className = "user-extra-context";
          kbBlock.textContent = dr.knowledgeContent;
          kbBody.appendChild(kbBlock);
          kbPanel.appendChild(kbSummary);
          kbPanel.appendChild(kbBody);
          userStack.appendChild(kbPanel);
        } else if (hasKnowledgeNames) {
          // 思考过程：纯文本标签显示知识库名
          var kbMeta = document.createElement("div");
          kbMeta.className = "user-meta-tag user-knowledge-meta";
          kbMeta.textContent = "知识库：" + dr.knowledgeNames.join("、");
          userStack.appendChild(kbMeta);
        }

        // 技能标签
        if (hasSkills) {
          var skillMeta = document.createElement("div");
          skillMeta.className = "user-meta-tag user-skill-meta";
          skillMeta.textContent = "技能：" + dr.skills.join("、");
          userStack.appendChild(skillMeta);
        }

        // MCP工具标签
        if (hasMcpTools) {
          var mcpMeta = document.createElement("div");
          mcpMeta.className = "user-meta-tag user-mcp-meta";
          mcpMeta.textContent = "mcp：" + dr.mcpTools.join("、");
          userStack.appendChild(mcpMeta);
        }

        // 额外上下文折叠面板（协同规则等）
        if (hasExtraContext) {
          var extraPanel = document.createElement("details");
          extraPanel.className = "user-extra-panel";
          var extraSummary = document.createElement("summary");
          extraSummary.className = "user-extra-summary";
          var extraTitle = document.createElement("span");
          extraTitle.className = "user-extra-title";
          extraTitle.textContent = "📎 附加信息";
          var extraChev = document.createElement("span");
          extraChev.className = "user-extra-chevron";
          extraChev.setAttribute("aria-hidden", "true");
          extraSummary.appendChild(extraTitle);
          extraSummary.appendChild(extraChev);
          var extraBody = document.createElement("div");
          extraBody.className = "user-extra-body";
          var ctxBlock = document.createElement("pre");
          ctxBlock.className = "user-extra-context";
          ctxBlock.textContent = dr.extraContext;
          extraBody.appendChild(ctxBlock);
          extraPanel.appendChild(extraSummary);
          extraPanel.appendChild(extraBody);
          userStack.appendChild(extraPanel);
        }

        // 用户消息气泡
        var bubble = document.createElement("div");
        bubble.className = "bubble user-bubble";
        bubble.textContent = dr.text || "";
        userStack.appendChild(bubble);

        var userTime = formatTimestamp(dr.timestamp);
        if (userTime) {
          var timeEl = document.createElement("div");
          timeEl.className = "msg-time user-time";
          timeEl.textContent = userTime;
          userStack.appendChild(timeEl);
        }
        row.appendChild(userStack);
      } else {
        row.className = "msg-row assistant";
        var avatar = document.createElement("span");
        avatar.className = "msg-avatar";
        avatar.setAttribute("aria-hidden", "true");
        avatar.textContent = "✦";
        row.appendChild(avatar);
        var assistantWrap = document.createElement("div");
        assistantWrap.className = "assistant-stack";
        assistantWrap.appendChild(renderAssistantThinkAndReply(dr));
        var assistantTime = formatTimestamp(dr.timestamp);
        if (assistantTime) {
          var aTimeEl = document.createElement("div");
          aTimeEl.className = "msg-time assistant-time";
          aTimeEl.textContent = assistantTime;
          assistantWrap.appendChild(aTimeEl);
        }
        row.appendChild(assistantWrap);
      }
      messagesEl.appendChild(row);
    });
    var area = messagesEl.parentElement;
    if (area) area.scrollTop = area.scrollHeight;
  }

  // 统一绑定：消息内的路径与 http(s) 外链一律外开，禁止在桌面 WebView 内导航
  function bindAssistantPathLinks() {
    if (!messagesEl || messagesEl.__pathLinkBound) return;
    messagesEl.__pathLinkBound = true;
    messagesEl.addEventListener("click", function (e) {
      var target = e.target;
      if (!target || !target.closest) return;

      function openExternally(url) {
        var u = String(url || "").trim();
        if (!u) return;
        try {
          var bridge = desktopBridgeGetter ? desktopBridgeGetter() : null;
          if (bridge && typeof bridge.open_external_url === "function") {
            // 仅传一个参数：槽签名为 open_external_url(str)，多传回调会导致 WebChannel 调用失败
            bridge.open_external_url(u);
            return;
          }
        } catch (_e) {
          /* ignore and fallback */
        }
        var lower = u.toLowerCase();
        if (lower.indexOf("http://") === 0 || lower.indexOf("https://") === 0) {
          try {
            window.open(u, "_blank", "noopener,noreferrer");
          } catch (_e2) {
            /* ignore */
          }
          return;
        }
        try {
          window.open(u, "_blank");
        } catch (_e3) {
          /* ignore */
        }
      }

      var pathA = target.closest("a.path-link");
      if (pathA) {
        var href = pathA.getAttribute("data-file-url");
        if (!href) return;
        e.preventDefault();
        e.stopPropagation();
        openExternally(href);
        return;
      }

      var rawA = target.closest("a[href]");
      if (!rawA) return;
      var rawHref = rawA.getAttribute("href") || "";
      if (!/^https?:\/\//i.test(rawHref)) return;
      e.preventDefault();
      e.stopPropagation();
      openExternally(rawHref);
    });
  }

  function deleteConversation(id) {
    var conv = chatState.conversations.find(function (c) {
      return c.id === id;
    });
    var username = scopedUsername || currentUsername();
    if (conv && conv.threadId && username) {
      fetch(
        apiBase +
          "/api/desktop/conversations/" +
          encodeURIComponent(conv.threadId) +
          "?username=" +
          encodeURIComponent(username) +
          "&session_id=" +
          encodeURIComponent(conv.sessionId || ""),
        { method: "DELETE" }
      ).catch(function () {
        /* ignore */
      });
    }

    chatState.conversations = chatState.conversations.filter(function (c) {
      return c.id !== id;
    });
    closeConversationMenu();
    if (chatState.conversations.length === 0) {
      var nc = {
        id: genId(),
        title: "新对话",
        messages: [],
      };
      chatState.conversations.push(nc);
      chatState.activeId = nc.id;
    } else if (chatState.activeId === id) {
      chatState.activeId = chatState.conversations[0].id;
    }
    persistChatState();
    renderConversationList();
    renderMessages();
  }

  /* ---- 批量删除 ---- */

  function toggleConvBatchMode() {
    convBatchMode = !convBatchMode;
    convBatchSelectedIds = {};
    renderConversationList();
  }

  function toggleSchedBatchMode() {
    schedBatchMode = !schedBatchMode;
    schedBatchSelectedIds = {};
    renderConversationList();
  }

  function batchSelectAll(convList, batchSelectedIds) {
    var allSelected = convList.every(function (c) { return batchSelectedIds[c.id]; });
    if (allSelected) {
      convList.forEach(function (c) { delete batchSelectedIds[c.id]; });
    } else {
      convList.forEach(function (c) { batchSelectedIds[c.id] = true; });
    }
    renderConversationList();
  }

  function batchDeleteSelected(isConvScope) {
    var selectedIdsObj = isConvScope ? convBatchSelectedIds : schedBatchSelectedIds;
    var selectedIds = Object.keys(selectedIdsObj).filter(function (id) { return selectedIdsObj[id]; });
    if (!selectedIds.length) return;
    var count = selectedIds.length;
    showConfirmDialog({
      title: "批量删除对话",
      message: "确定删除选中的 " + count + " 条对话？删除后将无法恢复。",
      confirmText: "删除",
      cancelText: "取消",
    }).then(function (ok) {
      if (!ok) return;
      selectedIds.forEach(function (id) {
        var conv = chatState.conversations.find(function (c) { return c.id === id; });
        if (conv) deleteConversation(conv.id);
      });
      if (isConvScope) {
        convBatchMode = false;
        convBatchSelectedIds = {};
      } else {
        schedBatchMode = false;
        schedBatchSelectedIds = {};
      }
      renderConversationList();
    });
  }

  function cancelBatchMode(isConvScope) {
    if (isConvScope) {
      convBatchMode = false;
      convBatchSelectedIds = {};
    } else {
      schedBatchMode = false;
      schedBatchSelectedIds = {};
    }
    renderConversationList();
  }

  function renderBatchActionBar(slotId, labelId, convList, batchSelectedIds) {
    var slot = document.getElementById(slotId);
    var label = document.getElementById(labelId);
    if (!slot || !label || !convList.length) return;
    var isConvScope = (batchSelectedIds === convBatchSelectedIds);
    var selectedCount = convList.filter(function (c) { return batchSelectedIds[c.id]; }).length;
    slot.innerHTML =
      '<span class="batch-info-inline">' +
      (selectedCount > 0 ? "已选" + selectedCount : "") +
      "</span>" +
      '<button type="button" class="batch-sm-btn" id="' + slotId + '-select-all">全选</button>' +
      '<button type="button" class="batch-sm-btn" id="' + slotId + '-cancel">取消</button>' +
      '<button type="button" class="batch-sm-btn batch-sm-del" id="' + slotId + '-delete"' +
      (selectedCount === 0 ? " disabled" : "") +
      ">删除</button>";
    label.classList.add("batch-mode");
    var selectAllBtn = slot.querySelector("#" + slotId + "-select-all");
    if (selectAllBtn) {
      selectAllBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        batchSelectAll(convList, batchSelectedIds);
      });
    }
    var cancelBtn = slot.querySelector("#" + slotId + "-cancel");
    if (cancelBtn) {
      cancelBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        cancelBatchMode(isConvScope);
      });
    }
    var delBtn = slot.querySelector("#" + slotId + "-delete");
    if (delBtn) {
      delBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        batchDeleteSelected(isConvScope);
      });
    }
  }

  function clearBatchActionBar(slotId, labelId) {
    var slot = document.getElementById(slotId);
    var label = document.getElementById(labelId);
    if (slot) slot.innerHTML = "";
    if (label) label.classList.remove("batch-mode");
  }

  /* 绑定侧栏批量管理图标按钮 */
  function bindBatchIconButtons() {
    var convBtn = document.getElementById("sidebar-batch-conv-btn");
    var schedBtn = document.getElementById("sidebar-batch-sched-btn");
    if (convBtn) {
      convBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        toggleConvBatchMode();
      });
    }
    if (schedBtn) {
      schedBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        toggleSchedBatchMode();
      });
    }
  }

  function updateBatchIconStates() {
    var convBtn = document.getElementById("sidebar-batch-conv-btn");
    var schedBtn = document.getElementById("sidebar-batch-sched-btn");
    if (convBtn) convBtn.classList.toggle("is-active", convBatchMode);
    if (schedBtn) schedBtn.classList.toggle("is-active", schedBatchMode);
  }

  function syncSidebarSearchElements() {
    if (!sidebarSearchInputEl) {
      sidebarSearchInputEl = document.getElementById("sidebar-conversation-search");
    }
    if (!sidebarSearchClearEl) {
      sidebarSearchClearEl = document.getElementById("sidebar-search-clear");
    }
  }

  function sidebarSearchQueryNorm() {
    syncSidebarSearchElements();
    return trimMsgText(sidebarSearchInputEl ? sidebarSearchInputEl.value : "").toLowerCase();
  }

  function filterConversationsBySearch(convs) {
    var q = sidebarSearchQueryNorm();
    if (!q) return convs;
    return convs.filter(function (c) {
      return String(getConversationDisplayTitle(c) || "").toLowerCase().indexOf(q) >= 0;
    });
  }

  function updateSidebarSearchClearUi() {
    syncSidebarSearchElements();
    if (!sidebarSearchClearEl || !sidebarSearchInputEl) return;
    var has = !!trimMsgText(sidebarSearchInputEl.value);
    sidebarSearchClearEl.classList.toggle("hidden", !has);
  }

  function renderConversationList() {
    if (!conversationListEl) return;
    closeConversationMenu();
    conversationListEl.innerHTML = "";
    if (schedulerConversationListEl) schedulerConversationListEl.innerHTML = "";
    var normalConvs = [];
    var schedulerConvs = [];
    chatState.conversations.forEach(function (conv) {
      if (isSchedulerConversation(conv)) schedulerConvs.push(conv);
      else normalConvs.push(conv);
    });
    var filteredNormal = filterConversationsBySearch(normalConvs);
    var filteredScheduler = filterConversationsBySearch(schedulerConvs);

    function renderIntoList(targetEl, convList, emptyText, title, isBatchMode, batchSelectedIds) {
      if (!targetEl) return;
      if (!convList.length && !isBatchMode) {
        var empty = document.createElement("div");
        empty.className = "history-empty";
        empty.textContent = emptyText;
        targetEl.appendChild(empty);
        return;
      }
      convList.forEach(function (conv) {
      var displayTitle = getConversationDisplayTitle(conv);
      var row = document.createElement("div");
      var rowClass = "history-row";
      if (conv.id === chatState.activeId) rowClass += " active";
      if (isBatchMode) rowClass += " batch-mode";
      row.className = rowClass;
      row.dataset.id = conv.id;

      /* 批量模式下的复选框 */
      var checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "history-checkbox";
      checkbox.checked = !!batchSelectedIds[conv.id];
      checkbox.addEventListener("click", function (e) {
        e.stopPropagation();
        if (batchSelectedIds[conv.id]) {
          delete batchSelectedIds[conv.id];
        } else {
          batchSelectedIds[conv.id] = true;
        }
        renderConversationList();
      });
      if (isBatchMode) {
        row.appendChild(checkbox);
      }

      var mainBtn = document.createElement("button");
      mainBtn.type = "button";
      mainBtn.className = "history-item-main";
      mainBtn.setAttribute("aria-label", "打开对话：" + displayTitle);
      var titleSpan = document.createElement("span");
      titleSpan.className = "history-item-title";
      titleSpan.textContent = displayTitle;
      mainBtn.appendChild(titleSpan);
      var convDate = formatTimestamp(conv.updatedAt);
      if (convDate) {
        var dateSpan = document.createElement("span");
        dateSpan.className = "history-item-date";
        dateSpan.textContent = convDate;
        mainBtn.appendChild(dateSpan);
      }

      row.appendChild(mainBtn);

      /* 批量模式不显示更多按钮和下拉菜单 */
      if (!isBatchMode) {
        var moreBtn = document.createElement("button");
        moreBtn.type = "button";
        moreBtn.className = "history-more";
        moreBtn.setAttribute("aria-label", "更多操作");
        moreBtn.setAttribute("aria-expanded", "false");
        moreBtn.textContent = "⋯";

        var dropdown = document.createElement("div");
        dropdown.className = "history-dropdown hidden";
        var delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.textContent = "删除";
        delBtn.dataset.action = "delete";
        dropdown.appendChild(delBtn);

        row.appendChild(moreBtn);
        row.appendChild(dropdown);

        delBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          closeConversationMenu();
          showConfirmDialog({
            title: "删除对话",
            message: "确定删除该对话？删除后将无法恢复。",
            confirmText: "删除",
            cancelText: "取消",
          }).then(function (ok) {
            if (ok) deleteConversation(conv.id);
          });
        });

        moreBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          var isOpen = openMenuConvId === conv.id;
          closeConversationMenu();
          if (!isOpen) {
            openMenuConvId = conv.id;
            dropdown.classList.remove("hidden");
            row.classList.add("menu-open");
            moreBtn.setAttribute("aria-expanded", "true");
          }
        });
      }

      mainBtn.addEventListener("click", async function () {
        closeConversationMenu();
        if (isBatchMode) {
          if (batchSelectedIds[conv.id]) {
            delete batchSelectedIds[conv.id];
          } else {
            batchSelectedIds[conv.id] = true;
          }
          renderConversationList();
          return;
        }
        if (typeof onSidebarConversationOpen === "function") {
          onSidebarConversationOpen();
        }
        if (chatState.activeId === conv.id) {
          renderConversationList();
          renderMessages();
          return;
        }
        chatState.activeId = conv.id;
        var preserveLocalPending =
          quotationInFlight &&
          quotationInFlightConvId === conv.id &&
          Array.isArray(conv.messages) &&
          conv.messages.length > 0;
        if (!preserveLocalPending) {
          var res = await loadMessagesFromBackend(conv, { offset: 0, limit: 50 });
          conv.messages = res.messages;
          conv._msgOffset = res.nextOffset;
          conv._msgTotal = res.total;
          conv._msgHasMore = res.hasMore;
          backfillConversationTitleFromMessages(conv);
        }
        renderConversationList();
        renderMessages();
      });

      targetEl.appendChild(row);
      });
    }

    var emptyNormal = normalConvs.length === 0 ? "暂无对话" : "无匹配对话";
    var emptyScheduler =
      schedulerConvs.length === 0 ? "暂无定时任务记录" : "无匹配记录";
    renderIntoList(conversationListEl, filteredNormal, emptyNormal, "对话列表", convBatchMode, convBatchSelectedIds);
    if (schedulerConversationListEl) {
      renderIntoList(schedulerConversationListEl, filteredScheduler, emptyScheduler, "定时任务", schedBatchMode, schedBatchSelectedIds);
      var active = getActiveConversation();
      if (active && isSchedulerConversation(active)) {
        setSchedulerSectionExpanded(true);
      } else {
        setSchedulerSectionExpanded(!!schedulerSectionExpanded);
      }
    }

    /* 填充侧栏标题行的批量操作内联控件 */
    if (convBatchMode && filteredNormal.length > 0) {
      renderBatchActionBar("conv-batch-slot", "conv-history-label", filteredNormal, convBatchSelectedIds);
    } else {
      clearBatchActionBar("conv-batch-slot", "conv-history-label");
    }
    if (schedBatchMode && filteredScheduler.length > 0) {
      renderBatchActionBar("sched-batch-slot", "sched-history-label", filteredScheduler, schedBatchSelectedIds);
    } else {
      clearBatchActionBar("sched-batch-slot", "sched-history-label");
    }
    updateBatchIconStates();
  }

  async function createConversation(options) {
    options = options || {};
    closeConversationMenu();
    var username = scopedUsername || currentUsername();
    if (!username) return null;

    if (options.reuseBlank !== false) {
      var reuse = findReusableBlankNormalConversation();
      if (reuse) {
        chatState.activeId = reuse.id;
        var reuseRes = await loadMessagesFromBackend(reuse, { offset: 0, limit: 50 });
        reuse.messages = reuseRes.messages;
        reuse._msgOffset = reuseRes.nextOffset;
        reuse._msgTotal = reuseRes.total;
        reuse._msgHasMore = reuseRes.hasMore;
        renderConversationList();
        renderMessages();
        var ta0 = document.getElementById("composer-input");
        if (ta0) ta0.focus();
        return reuse;
      }
    }

    try {
      var res = await fetch(apiBase + "/api/desktop/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username }),
      });
      if (!res.ok) throw new Error("create conversation failed");
      var data = await res.json();
      var c = data && data.conversation ? data.conversation : null;
      if (!c) return null;
      var conv = {
        id: c.id || genId(),
        title: normalizeConversationTitle(c.title || "新对话"),
        messages: [],
        threadId: c.threadId || generateSessionId("thread"),
        sessionId: typeof c.sessionId === "string" ? c.sessionId : "",
        updatedAt: normalizeUpdatedAt(c.updatedAt || Date.now()),
      };
      chatState.conversations.push(conv);
      sortConversationsByRecency();
      chatState.activeId = conv.id;
      renderConversationList();
      renderMessages();
      var ta = document.getElementById("composer-input");
      if (ta) ta.focus();
      return conv;
    } catch (_e) {
      return null;
    }
  }

  // 滚动事件：拖动到消息区最上方时显示「加载更多」提示
  function bindScrollLoadMore() {
    if (!messagesEl || messagesEl.__scrollLoadMoreBound) return;
    messagesEl.__scrollLoadMoreBound = true;
    var area = messagesEl.parentElement;
    if (!area) return;
    var SCROLL_TOP_THRESHOLD = 5;
    var scrollTimer = null;
    area.addEventListener("scroll", function () {
      // 使用 requestAnimationFrame 节流，避免高频触发
      if (scrollTimer) return;
      scrollTimer = requestAnimationFrame(function () {
        scrollTimer = null;
        var hint = document.getElementById("load-more-hint");
        if (!hint) return;
        if (area.scrollTop <= SCROLL_TOP_THRESHOLD) {
          hint.classList.remove("hidden");
        } else {
          hint.classList.add("hidden");
        }
      });
    });
  }

  bindScrollLoadMore();
  bindAssistantPathLinks();
  bindAttachmentUi();
  bindKnowledgeUi();
  bindPasteAttachmentHandler();

  async function startConversationWithMessage(text, options) {
    options = options || {};
    var autoSend = options.autoSend !== false;
    var username = scopedUsername || currentUsername();
    if (!username) {
      if (typeof options.onNeedLogin === "function") options.onNeedLogin();
      return null;
    }
    var t = trimMsgText(text);
    if (!t) return null;
    closeConversationMenu();
    var conv = await createConversation();
    if (!conv) return null;
    var ta = document.getElementById("composer-input");
    if (ta) ta.value = t;
    if (autoSend) {
      await sendComposerMessage();
    } else if (ta) {
      ta.focus();
    }
    return conv;
  }

  async function sendComposerMessage() {
    if (quotationInFlight) {
      await stopComposerRequest();
      return;
    }
    var ta = document.getElementById("composer-input");
    var text = (ta && ta.value.trim()) || "";
    var filesToSend = pendingFiles.slice(0);
    var kbFilesToSend = pendingKnowledgeFiles.slice(0);
    if (!text && !filesToSend.length && !kbFilesToSend.length) return;

    var conv = getActiveConversation();
    if (!conv) {
      conv = await createConversation();
      if (!conv) return;
    }

    var attachmentPathsForApi = [];
    try {
      if (filesToSend.length) {
        attachmentPathsForApi = await uploadDesktopFiles(filesToSend);
      }
    } catch (uploadErr) {
      var umsg = uploadErr && uploadErr.message ? uploadErr.message : String(uploadErr);
      window.alert("附件上传失败：" + umsg);
      return;
    }

    ta.value = "";
    // 手动触发 input 事件，让 autoGrowComposer 将输入框高度重置为默认值
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    // 在清空之前提取附件名和知识库名（用于消息显示）
    var attachmentNamesForMsg = filesToSend.map(function (f) { return f.name; });
    var knowledgeNamesForMsg = pendingKnowledgeCategories
      .map(function (kc) { return kc.display_name || kc.name; })
      .concat(
        pendingKnowledgeFiles
          .filter(function (kf) {
            return !pendingKnowledgeCategories.some(function (kc) { return kc.name === kf.category; });
          })
          .map(function (kf) { return kf.name; })
      );
    pendingFiles = [];
    renderAttachmentChips();
    var knowledgeFileIdsForApi = pendingKnowledgeFiles.map(function (kf) { return kf.id; });
    var knowledgeCategoryNamesForApi = pendingKnowledgeCategories.map(function (kc) { return kc.name; });
    pendingKnowledgeFiles = [];
    pendingKnowledgeCategories = [];
    renderKnowledgeChips();
    closeKnowledgePanel();

    var displayText = text;

    var textForApi = buildUserInputBeforeSend ? buildUserInputBeforeSend(displayText) : displayText;
    if (augmentUserInputBeforeSend) {
      try {
        textForApi = await augmentUserInputBeforeSend(textForApi, conv.messages);
      } catch (_augErr) {
        /* keep original input */
      }
    }
    var parsedForSend = parseSkillsInjectedPayload(textForApi);
    var mcpParsedForSend = parseMcpInjectedPayload(parsedForSend.text);
    var userMsg = { role: "user", text: displayText, timestamp: Date.now() };
    if (parsedForSend.skills && parsedForSend.skills.length) {
      userMsg.skills = parsedForSend.skills;
    }
    if (mcpParsedForSend.mcpTools && mcpParsedForSend.mcpTools.length) {
      userMsg.mcpTools = mcpParsedForSend.mcpTools;
    }
    if (attachmentNamesForMsg.length) {
      userMsg.attachmentNames = attachmentNamesForMsg;
    }
    if (knowledgeNamesForMsg.length) {
      userMsg.knowledgeNames = knowledgeNamesForMsg;
    }
    conv.messages.push(userMsg);
    conv._msgHasMore = false;
    touchConversation(conv);
    maybeRenameFromFirstMessage(conv, text || displayText);
    
    // 每次发送新消息时，生成新的 sessionId（对应 checkpoint_ns）
    // 这样同一个 thread_id（会话窗口）下的每轮对话都有独立的 checkpoint
    var username = scopedUsername || currentUsername();
    var prefix = "desktop_" + (username || "user") + "_";
    conv.sessionId = generateSessionId(prefix + "session");
    
    ensureThreadSession(conv);

    quotationInFlight = true;
    quotationStopRequested = false;
    quotationInFlightConvId = conv.id;
    quotationAbortController = new AbortController();
    setComposerBusy(true);
    conv.messages.push({
      role: "assistant",
      text: "正在思考…",
      streaming: true,
      thinkSteps: [],
      _pendingThinkHints: [],
      timestamp: Date.now(),
    });
    conv._msgHasMore = false;
    touchConversation(conv);
    persistChatState();
    sortConversationsByRecency();
    renderConversationList();
    renderMessages();

    function applyThinkEventToAssistant(ev) {
      var last = conv.messages[conv.messages.length - 1];
      if (!last || last.role !== "assistant" || !last.streaming) return;
      ingestThinkStreamEvent(last, ev);
      last.text = "正在思考…";
      renderMessages();
    }

    streamQuotation(conv, textForApi, attachmentPathsForApi, {
      onEvent: function (ev) {
        applyThinkEventToAssistant(ev);
      },
      onHITLWait: function (ev) {
        quotationInFlight = false;
        quotationInFlightConvId = null;
        setComposerBusy(false);
        var last = conv.messages[conv.messages.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          last.text = last.text === "正在思考…" ? "等待您的确认…" : last.text;
          delete last.streaming;
        }
        renderMessages();
        hitlManager.show(ev, conv);
      },
    }, quotationAbortController.signal, null, knowledgeFileIdsForApi, knowledgeCategoryNamesForApi)
      .then(function (finalContent) {
        var last = conv.messages[conv.messages.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          var F = finalContent != null ? String(finalContent).trim() : "";
          var prev = trimMsgText(last.text);
          last.text = F ? finalContent : prev || "（本次未返回文本内容）";
          last.timestamp = Date.now();
          delete last.streaming;
        }
        clearThinkStreamState(last);
        touchConversation(conv);
        return fetchThinkStepsFromBackend(conv).then(function (steps) {
          mergeThinkStepsOntoLastAssistant(conv, steps, finalContent);
          renderMessages();
          return notifyAssistantStreamDone(conv, finalContent);
        });
      })
      .catch(function (err) {
        var last = conv.messages[conv.messages.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          clearThinkStreamState(last);
          if (quotationStopRequested) {
            last.text = "已中断当前任务";
          } else {
            last.text = "请求失败：" + (err && err.message ? err.message : String(err));
          }
          last.timestamp = Date.now();
          delete last.streaming;
        }
        touchConversation(conv);
      })
      .finally(function () {
        quotationInFlight = false;
        quotationInFlightConvId = null;
        quotationAbortController = null;
        quotationStopRequested = false;
        setComposerBusy(false);
        persistChatState();
        sortConversationsByRecency();
        renderMessages();
        renderConversationList();
      });
  }

  function bindGlobalEvents() {
    document.addEventListener("click", function () {
      closeConversationMenu();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (confirmOverlay && !confirmOverlay.classList.contains("hidden")) {
        e.preventDefault();
        closeConfirmDialog(false);
        return;
      }
      syncSidebarSearchElements();
      if (
        sidebarSearchInputEl &&
        document.activeElement === sidebarSearchInputEl &&
        trimMsgText(sidebarSearchInputEl.value)
      ) {
        e.preventDefault();
        sidebarSearchInputEl.value = "";
        updateSidebarSearchClearUi();
        renderConversationList();
        return;
      }
      closeConversationMenu();
    });

    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") {
        syncSidebarConversationsFromServer();
      }
    });

    conversationListEl.addEventListener("click", function (e) {
      e.stopPropagation();
    });
    if (schedulerSectionToggleEl) {
      schedulerSectionToggleEl.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        setSchedulerSectionExpanded(!schedulerSectionExpanded);
      });
    }

    syncSidebarSearchElements();
    if (sidebarSearchInputEl) {
      sidebarSearchInputEl.addEventListener("input", function () {
        updateSidebarSearchClearUi();
        renderConversationList();
      });
    }
    if (sidebarSearchClearEl) {
      sidebarSearchClearEl.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (sidebarSearchInputEl) {
          sidebarSearchInputEl.value = "";
          updateSidebarSearchClearUi();
          renderConversationList();
          sidebarSearchInputEl.focus();
        }
      });
    }
    updateSidebarSearchClearUi();
  }

  return {
    setComposerBusy: setComposerBusy,
    renderMessages: renderMessages,
    renderConversationList: renderConversationList,
    createConversation: createConversation,
    sendComposerMessage: sendComposerMessage,
    startConversationWithMessage: startConversationWithMessage,
    setScopedUser: setScopedUser,
    hydrateStateFromBackend: hydrateStateFromBackend,
    syncChatStateToBackend: syncChatStateToBackend,
    syncSidebarConversationsFromServer: syncSidebarConversationsFromServer,
    startSidebarAutoRefresh: startSidebarAutoRefresh,
    stopSidebarAutoRefresh: stopSidebarAutoRefresh,
    bindConfirmDialog: bindConfirmDialog,
    bindGlobalEvents: bindGlobalEvents,
    bindBatchIconButtons: bindBatchIconButtons,
  };
}

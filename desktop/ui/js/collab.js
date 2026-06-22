import { getSession } from "./storage.js";

const COLLAB_POLL_MS = 30000;

const STEP_STATUS_LABELS = {
  pending: "待开始",
  running: "进行中",
  completed: "已完成",
  rejected: "已退回",
};

const CHAIN_STATUS_LABELS = {
  defining: "定义中",
  running: "进行中",
  completed: "已完成",
  cancelled: "已取消",
};

function decodeCollabFilename(name) {
  var s = String(name || "").trim();
  if (!s) return "附件";
  if (/%[0-9A-Fa-f]{2}/.test(s)) {
    try {
      var decoded = decodeURIComponent(s.replace(/\+/g, " "));
      if (decoded && decoded.trim()) return decoded.trim();
    } catch (e) {
      /* ignore */
    }
  }
  return s;
}

function formatCollabTimestamp(value) {
  if (value == null || value === "") return "";
  var d = new Date(value);
  if (isNaN(d.getTime())) {
    var s = String(value).trim();
    return s.length >= 16 ? s.slice(0, 16) : s;
  }
  var pad = function (n) {
    return n < 10 ? "0" + n : String(n);
  };
  return (
    d.getFullYear() +
    "-" +
    pad(d.getMonth() + 1) +
    "-" +
    pad(d.getDate()) +
    " " +
    pad(d.getHours()) +
    ":" +
    pad(d.getMinutes())
  );
}

function formatChainTimeSummary(chain) {
  var parts = [];
  var created = formatCollabTimestamp(chain.created_at);
  if (created) parts.push("创建 " + created);
  var updated = formatCollabTimestamp(chain.updated_at);
  if (updated && updated !== created) parts.push("更新 " + updated);
  if (String(chain.status) === "completed") {
    var done = formatCollabTimestamp(chain.completed_at);
    if (done) parts.push("完成 " + done);
  }
  return parts.join(" · ");
}

function formatStepTimeSummary(step) {
  var parts = [];
  var started = formatCollabTimestamp(step.started_at);
  if (started) parts.push("开始 " + started);
  var completed = formatCollabTimestamp(step.completed_at);
  if (completed) parts.push("完成 " + completed);
  return parts.join(" · ");
}

function formatFileSize(bytes) {
  var n = Number(bytes);
  if (!n || n < 0) return "";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + " MB";
  return (n / (1024 * 1024 * 1024)).toFixed(1) + " GB";
}

function indexAttachmentsByStepId(attachments) {
  var map = Object.create(null);
  (attachments || []).forEach(function (att) {
    var sid = String(att.step_id || "").trim();
    if (!sid) return;
    if (!map[sid]) map[sid] = [];
    map[sid].push(att);
  });
  return map;
}

export function createCollabController(options) {
  var adminApiBase = String(options.adminApiBase || "").replace(/\/$/, "");
  var getDesktopBridge = options.getDesktopBridge || function () {
    return null;
  };
  var getWorkspaceRoot = options.getWorkspaceRoot || function () {
    return "";
  };
  var listEl = options.listEl;
  var detailRootEl = options.detailRootEl;
  var sectionToggleEl = options.sectionToggleEl;
  var sectionUnreadBadgeEl = options.sectionUnreadBadgeEl;
  var setMainView = options.setMainView || function () {};
  var setTopBarTitle = options.setTopBarTitle || function () {};
  var startConversationWithMessage =
    options.startConversationWithMessage || function () {
      return Promise.resolve();
    };

  var chains = [];
  var selectedChainId = "";
  var sectionExpanded = true;
  var pollTimer = null;
  /** 每次打开/切换详情递增，用于丢弃过期响应 */
  var detailLoadSeq = 0;
  var detailAbortController = null;
  /** 同一 chain+附件集合的同步请求去重（避免轮询/详情刷新重复下载） */
  var inboundSyncInflight = Object.create(null);

  function getCurrentUserId() {
    var sess = getSession();
    var u = sess && sess.user;
    return String((u && (u.id || u.user_id)) || "").trim();
  }

  function getCurrentUsername() {
    var sess = getSession();
    var u = sess && sess.user;
    return String((u && u.username) || "").trim();
  }

  function isChainCollaborator(chain, steps, userId) {
    if (!userId || !chain) return false;
    if (String(chain.initiator_user_id) === userId) return true;
    return (steps || []).some(function (step) {
      return String(step.assignee_user_id) === userId;
    });
  }

  function canManageStepUpload(step, chain, steps, userId) {
    if (!isChainCollaborator(chain, steps, userId)) return false;
    if (String(step.status) !== "running") return false;
    return String(step.assignee_user_id) === userId;
  }

  function isLastCollabStep(step, chain) {
    if (!step || !chain) return false;
    var idx = Number(step.step_index);
    var total = Number(chain.total_steps);
    if (!total || !idx) return false;
    return idx >= total;
  }

  function canCompleteStep(step, chain, userId) {
    if (!userId || !step || !chain) return false;
    if (String(chain.status) !== "running") return false;
    if (String(step.status) !== "running") return false;
    if (isLastCollabStep(step, chain)) return false;
    return String(step.assignee_user_id) === userId;
  }

  function canDeleteAttachment(att, step, chain, steps, userId) {
    if (!isChainCollaborator(chain, steps, userId)) return false;
    if (!userId || !att) return false;
    if (String(chain.status) === "completed") return false;
    if (!step || String(step.status) !== "running") return false;
    if (String(att.uploader_user_id) === userId) return true;
    if (String(step.assignee_user_id) === userId) return true;
    return false;
  }

  function formatPromptForDisplay(text) {
    var t = String(text || "").trim();
    if (!t) return "";
    var markerIdx = t.indexOf("【上游协同附件");
    if (markerIdx < 0) return t;
    var before = t.slice(0, markerIdx).replace(/\s+$/, "");
    var after = t.slice(markerIdx);
    if (/### 步骤|## 附件：/.test(after)) {
      var names = [];
      var re = /## 附件：([^\n]+)/g;
      var m;
      while ((m = re.exec(after)) !== null) names.push(m[1]);
      var summary = "【上游协同附件】";
      if (names.length) {
        var shown = names.slice(0, 8).join("、");
        if (names.length > 8) shown += " 等共 " + names.length + " 个";
        summary += " " + shown;
      }
      summary += "（正文已解析，执行时由 Agent 自动加载，界面省略显示）";
      return before ? before + "\n\n" + summary : summary;
    }
    return t;
  }

  /* 批量删除状态 */
  var batchDeleteMode = false;
  var batchSelectedChainIds = {};

  function authHeaders() {
    var sess = getSession();
    var token = sess && sess.token ? sess.token : "";
    if (!token) return null;
    return {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    };
  }

  function isDetailLoadCurrent(chainId, loadSeq) {
    return loadSeq === detailLoadSeq && chainId === selectedChainId;
  }

  function abortDetailLoad() {
    if (detailAbortController) {
      try {
        detailAbortController.abort();
      } catch (e) {
        /* ignore */
      }
      detailAbortController = null;
    }
  }

  async function adminFetch(path, opts) {
    var headers = authHeaders();
    if (!headers) throw new Error("not_logged_in");
    var url = adminApiBase + path;
    var fetchOpts = Object.assign({ headers: headers }, opts || {});
    var res = await fetch(url, fetchOpts);
    var data = {};
    try {
      data = await res.json();
    } catch (e) {
      data = {};
    }
    if (!res.ok) {
      var msg = data.detail || data.message || res.statusText || "request failed";
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  }

  function downloadViaBridge(bridge, attachmentId, filename) {
    return new Promise(function (resolve, reject) {
      var sess = getSession();
      var token = sess && sess.token ? sess.token : "";
      if (!token) {
        reject(new Error("请先登录"));
        return;
      }
      if (typeof bridge.download_collab_attachment !== "function") {
        reject(new Error("桌面桥接不可用"));
        return;
      }
      bridge.download_collab_attachment(
        JSON.stringify({
          admin_api_base: adminApiBase,
          bearer_token: token,
          attachment_id: attachmentId,
          filename: decodeCollabFilename(filename),
        }),
        function (raw) {
          var parsed = {};
          try {
            parsed = JSON.parse(raw || "{}");
          } catch (e) {
            reject(new Error("解析下载结果失败"));
            return;
          }
          if (parsed.ok) {
            resolve(parsed);
            return;
          }
          if (parsed.cancelled) {
            resolve(parsed);
            return;
          }
          reject(new Error(parsed.message || "下载失败"));
        }
      );
    });
  }

  async function downloadCollabAttachmentFallback(attachmentId, filename) {
    var headers = authHeaders();
    if (!headers) throw new Error("请先登录");
    var url =
      adminApiBase +
      "/api/admin/collab/attachments/" +
      encodeURIComponent(attachmentId) +
      "/download";
    var res = await fetch(url, { headers: { Authorization: headers.Authorization } });
    if (!res.ok) {
      var errText = res.statusText || "下载失败";
      try {
        var errJson = await res.json();
        errText = errJson.detail || errJson.message || errText;
      } catch (e) {
        /* ignore */
      }
      throw new Error(typeof errText === "string" ? errText : JSON.stringify(errText));
    }
    var blob = await res.blob();
    var saveName = decodeCollabFilename(filename);
    if (!saveName || saveName === "附件") {
      var disp = res.headers.get("Content-Disposition") || "";
      var m = /filename\*=UTF-8''([^;\s]+)/i.exec(disp);
      if (m) {
        try {
          saveName = decodeURIComponent(m[1]);
        } catch (e) {
          saveName = m[1];
        }
      } else {
        m = /filename="([^"]+)"/i.exec(disp);
        saveName = m ? m[1] : "attachment";
      }
    }
    var objectUrl = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = objectUrl;
    a.download = saveName;
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(objectUrl);
    return { ok: true, path: saveName };
  }

  async function downloadCollabAttachment(attachmentId, filename, btnEl) {
    if (btnEl) {
      btnEl.disabled = true;
      btnEl.textContent = "下载中…";
    }
    try {
      var bridge = getDesktopBridge();
      var result;
      if (bridge && typeof bridge.download_collab_attachment === "function") {
        result = await downloadViaBridge(bridge, attachmentId, filename);
      } else {
        result = await downloadCollabAttachmentFallback(attachmentId, filename);
      }
      if (result && result.cancelled) return;
      if (result && result.path) {
        window.alert("已保存至:\n" + result.path);
      }
    } finally {
      if (btnEl) {
        btnEl.disabled = false;
        btnEl.textContent = "下载";
      }
    }
  }

  function extractGeneratedFilesFromText(text) {
    var raw = String(text || "");
    if (!raw.trim()) return [];
    var paths = [];
    var seen = Object.create(null);
    function addPath(p) {
      var s = String(p || "").trim().replace(/^["']|["']$/g, "");
      if (!s || seen[s]) return;
      seen[s] = true;
      paths.push(s);
    }
    var reBlock =
      /```(?:json)?\s*(\{[\s\S]*?"generated_files"\s*:\s*\[[\s\S]*?\][\s\S]*?\})\s*```/gi;
    var m;
    while ((m = reBlock.exec(raw)) !== null) {
      try {
        var parsed = JSON.parse(m[1]);
        if (parsed && Array.isArray(parsed.generated_files)) {
          parsed.generated_files.forEach(addPath);
        }
      } catch (e) {
        /* ignore */
      }
    }
    var reInline = /\{[^{}]*"generated_files"\s*:\s*\[([\s\S]*?)\][^{}]*\}/gi;
    while ((m = reInline.exec(raw)) !== null) {
      try {
        var block = m[0];
        var parsedInline = JSON.parse(block);
        if (parsedInline && Array.isArray(parsedInline.generated_files)) {
          parsedInline.generated_files.forEach(addPath);
        }
      } catch (e2) {
        var inner = m[1];
        var itemRe = /"([^"\\]*(?:\\.[^"\\]*)*)"/g;
        var im;
        while ((im = itemRe.exec(inner)) !== null) {
          addPath(im[1].replace(/\\"/g, '"'));
        }
      }
    }
    return paths;
  }

  function extractCollabContextFromText(text) {
    var t = String(text || "");
    if (!t.trim()) return null;
    var chainMatch = t.match(
      /协同链\s*ID\s*[：:]\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i
    );
    if (!chainMatch) {
      var uuidMatch = t.match(
        /\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b/i
      );
      if (!uuidMatch || (t.indexOf("协同") < 0 && t.toLowerCase().indexOf("collab") < 0)) {
        return null;
      }
      chainMatch = uuidMatch;
    }
    var stepMatch = t.match(/步骤\s*[：:]\s*(\d+)/);
    return {
      chain_id: chainMatch[1],
      step_index: stepMatch ? Number(stepMatch[1]) : 0,
    };
  }

  function extractCollabContextFromMessages(messages) {
    var list = Array.isArray(messages) ? messages : [];
    for (var i = 0; i < list.length; i++) {
      var msg = list[i];
      if (!msg || msg.role !== "user") continue;
      var ctx = extractCollabContextFromText(msg.text || "");
      if (ctx && ctx.chain_id) return ctx;
    }
    return null;
  }

  function resolveRunningStepForUser(steps, username) {
    var user = String(username || "").trim();
    if (!user) return null;
    var found = null;
    (steps || []).forEach(function (s) {
      if (String(s.status) !== "running") return;
      if (String(s.assignee_username || "").trim() !== user) return;
      found = s;
    });
    return found;
  }

  function buildCollabExecutionUserText(chain, step, taskPromptRendered) {
    var title = chain && chain.title ? String(chain.title) : "协同任务";
    var chainId = chain && chain.id ? String(chain.id) : "";
    var stepIndex = step && step.step_index ? Number(step.step_index) : 0;
    var lines = [
      "【协同任务】" + title,
      "协同链ID: " + chainId,
      "步骤: " + stepIndex,
    ];
    var prompt = String(taskPromptRendered || step.task_prompt_rendered || step.task_prompt || "").trim();
    if (prompt) {
      lines.push("");
      lines.push("任务要求:");
      lines.push(prompt);
    }
    return lines.join("\n");
  }

  async function buildCollabAttachmentRule(chainId, stepIndex, attachments, steps) {
    var workspace = String(getWorkspaceRoot() || "").trim();
    var user = getCurrentUsername();
    if (!workspace || !user || !chainId || !stepIndex || stepIndex <= 1) {
      return "";
    }
    var stepIdToIndex = Object.create(null);
    (steps || []).forEach(function (s) {
      if (s.id) stepIdToIndex[String(s.id)] = Number(s.step_index);
    });
    var pathLines = [];
    (attachments || []).forEach(function (att) {
      var idx = stepIdToIndex[String(att.step_id || "")];
      if (!idx || idx >= stepIndex) return;
      var fname = decodeCollabFilename(att.original_filename || "");
      if (!fname) return;
      pathLines.push(
        "- `" +
          buildCollabLocalPath(workspace, user, chainId, idx, fname) +
          "`"
      );
    });
    if (!pathLines.length) return "";
    return (
      "【协同附件读取规则】协同链 " +
      chainId +
      " 步骤 " +
      stepIndex +
      "：\n" +
      "- 仅允许用 read_file 读取下列 collab/step_N/ 路径（与界面「本地协同目录」一致）；\n" +
      "- 禁止使用其他同事 workspace 下的 YYYYMMDD 日期目录路径；禁止 HTTP 下载协同附件。\n" +
      "合法路径：\n" +
      pathLines.join("\n")
    );
  }

  async function resolveCollabContextForSend(text, messages) {
    var body = String(text || "");
    var ctx = extractCollabContextFromText(body) || extractCollabContextFromMessages(messages);
    if (!ctx || !ctx.chain_id) return null;

    var data;
    try {
      data = await adminFetch(
        "/api/admin/collab/chains/" + encodeURIComponent(ctx.chain_id)
      );
    } catch (e) {
      return ctx;
    }
    var steps = data.steps || [];
    var user = getCurrentUsername();
    if (!ctx.step_index || ctx.step_index <= 1) {
      var myStep = resolveRunningStepForUser(steps, user);
      if (myStep) {
        ctx.step_index = Number(myStep.step_index);
        ctx.step_id = myStep.id;
        ctx.task_prompt_rendered =
          myStep.task_prompt_rendered || myStep.task_prompt || "";
      } else if (data.chain && data.chain.current_step) {
        ctx.step_index = Number(data.chain.current_step);
      }
    }
    ctx.steps = steps;
    ctx.attachments = data.attachments || [];
    ctx.chain = data.chain || null;
    return ctx;
  }

  function buildCollabLocalPath(workspace, username, chainId, stepIndex, filename) {
    var sep = "\\";
    return (
      String(workspace || "").replace(/[/\\]+$/, "") +
      sep +
      String(username || "user") +
      sep +
      "collab" +
      sep +
      String(chainId || "") +
      sep +
      "step_" +
      String(stepIndex) +
      sep +
      String(filename || "")
    );
  }

  /**
   * Before each /quotation send in a collab conversation, inject canonical collab paths
   * so the agent does not guess .../YYYYMMDD/... from upstream summaries.
   */
  async function augmentCollabUserInputForSend(text, messages) {
    var body = String(text || "");
    if (body.indexOf("【上游协同附件（已自动解析）】") >= 0) return body;
    if (body.indexOf("【协同附件读取规则】") >= 0) return body;

    var ctx = await resolveCollabContextForSend(body, messages);
    if (!ctx || !ctx.chain_id || !ctx.step_index || ctx.step_index <= 1) {
      return body;
    }

    var rule = await buildCollabAttachmentRule(
      ctx.chain_id,
      ctx.step_index,
      ctx.attachments,
      ctx.steps
    );
    if (!rule) return body;
    return rule + "\n\n" + body;
  }

  async function uploadCollabPathsViaBridge(paths, chainId, stepId) {
    var bridge = getDesktopBridge();
    if (!bridge || typeof bridge.upload_collab_attachment_paths !== "function") {
      throw new Error("桌面桥接不可用，无法上传本地交付物");
    }
    var sess = getSession();
    var token = sess && sess.token ? sess.token : "";
    if (!token) throw new Error("请先登录");
    return new Promise(function (resolve, reject) {
      bridge.upload_collab_attachment_paths(
        JSON.stringify({
          admin_api_base: adminApiBase,
          bearer_token: token,
          chain_id: String(chainId || ""),
          step_id: String(stepId || ""),
          paths: paths,
        }),
        function (raw) {
          var parsed = {};
          try {
            parsed = JSON.parse(raw || "{}");
          } catch (e) {
            parsed = {};
          }
          if (!parsed.ok) {
            reject(new Error(parsed.message || "上传交付物失败"));
            return;
          }
          resolve(parsed.attachment_ids || []);
        }
      );
    });
  }

  async function uploadCollabAttachmentFile(file, chainId, stepId) {
    var headers = authHeaders();
    if (!headers) throw new Error("请先登录");
    var url =
      adminApiBase +
      "/api/admin/collab/attachments/upload?chain_id=" +
      encodeURIComponent(chainId) +
      "&step_id=" +
      encodeURIComponent(stepId);
    var fd = new FormData();
    fd.append("file", file);
    var res = await fetch(url, {
      method: "POST",
      headers: { Authorization: headers.Authorization },
      body: fd,
    });
    var data = {};
    try {
      data = await res.json();
    } catch (e) {
      data = {};
    }
    if (!res.ok) {
      var msg = data.detail || data.message || res.statusText || "上传失败";
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  }

  async function deleteCollabAttachment(attachmentId) {
    return adminFetch(
      "/api/admin/collab/attachments/" + encodeURIComponent(attachmentId),
      { method: "DELETE" }
    );
  }

  function canDeleteCollabChain(chain, userId) {
    if (!chain || !userId) return false;
    if (String(chain.status) === "completed") return false;
    return String(chain.initiator_user_id) === String(userId);
  }

  async function deleteCollabChain(chainId) {
    return adminFetch("/api/admin/collab/chains/" + encodeURIComponent(chainId), {
      method: "DELETE",
    });
  }

  async function completeCollabStep(chainId, stepId, payload) {
    var qs = "?chain_id=" + encodeURIComponent(chainId);
    return adminFetch(
      "/api/admin/collab/steps/" + encodeURIComponent(stepId) + "/complete" + qs,
      {
        method: "POST",
        body: JSON.stringify({
          result_summary: payload.result_summary,
          result_detail: payload.result_detail || null,
          relay_note: payload.relay_note || null,
          attachment_ids: payload.attachment_ids || [],
        }),
      }
    );
  }

  function priorAttachmentsSyncKey(chainId, prior) {
    var ids = prior
      .map(function (a) {
        return String(a.id || "");
      })
      .filter(Boolean)
      .sort();
    return String(chainId || "") + ":" + ids.join(",");
  }

  function syncInboundViaBridge(msg) {
    var prior = Array.isArray(msg.prior_attachments) ? msg.prior_attachments : [];
    if (!prior.length) return Promise.resolve(null);
    var bridge = getDesktopBridge();
    if (!bridge || typeof bridge.sync_collab_inbound_attachments !== "function") {
      return Promise.resolve(null);
    }
    var sess = getSession();
    var token = sess && sess.token ? sess.token : "";
    if (!token) return Promise.resolve(null);
    var workspace = String(getWorkspaceRoot() || "").trim();
    if (!workspace) return Promise.resolve(null);
    var chainId = String(msg.chain_id || "");
    var syncKey = priorAttachmentsSyncKey(chainId, prior);
    if (inboundSyncInflight[syncKey]) {
      return inboundSyncInflight[syncKey];
    }
    var pending = new Promise(function (resolve) {
      bridge.sync_collab_inbound_attachments(
        JSON.stringify({
          admin_api_base: adminApiBase,
          bearer_token: token,
          chain_id: chainId,
          step_index: msg.step_index,
          username: getCurrentUsername(),
          workspace_root: workspace,
          prior_attachments: prior,
        }),
        function (raw) {
          var parsed = {};
          try {
            parsed = JSON.parse(raw || "{}");
          } catch (e) {
            parsed = {};
          }
          resolve(parsed);
        }
      );
    }).then(function (result) {
      if (!result || !result.ok) {
        delete inboundSyncInflight[syncKey];
      }
      return result;
    });
    inboundSyncInflight[syncKey] = pending;
    return pending;
  }

  function buildPriorAttachments(attachments, steps, beforeStepIndex) {
    var stepIdToIndex = Object.create(null);
    (steps || []).forEach(function (s) {
      if (s.id) stepIdToIndex[String(s.id)] = Number(s.step_index);
    });
    var out = [];
    (attachments || []).forEach(function (att) {
      var idx = stepIdToIndex[String(att.step_id || "")];
      if (!idx || idx >= beforeStepIndex) return;
      out.push({
        id: att.id,
        original_filename: att.original_filename,
        file_size: att.file_size,
        mime_type: att.mime_type,
        step_id: att.step_id,
        step_index: idx,
        uploader_user_id: att.uploader_user_id,
      });
    });
    return out;
  }

  function appendAttachmentList(parentEl, items, ctx) {
    var list = document.createElement("ul");
    list.className = "collab-attachment-list";
    if (!items || !items.length) {
      var empty = document.createElement("li");
      empty.className = "collab-attachment-empty";
      empty.textContent = "暂无附件";
      list.appendChild(empty);
      parentEl.appendChild(list);
      return;
    }
    items.forEach(function (att) {
      var li = document.createElement("li");
      li.className = "collab-attachment-item";

      var info = document.createElement("div");
      info.className = "collab-attachment-info";

      var nameEl = document.createElement("span");
      nameEl.className = "collab-attachment-name";
      var displayName = decodeCollabFilename(att.original_filename || att.id || "附件");
      nameEl.textContent = displayName;
      nameEl.title = displayName;
      info.appendChild(nameEl);

      var metaParts = [];
      var sizeText = formatFileSize(att.file_size);
      if (sizeText) metaParts.push(sizeText);
      var attTime = formatCollabTimestamp(att.created_at);
      if (attTime) metaParts.push(attTime);
      if (att.mime_type) metaParts.push(att.mime_type);
      if (metaParts.length) {
        var metaEl = document.createElement("span");
        metaEl.className = "collab-attachment-meta";
        metaEl.textContent = metaParts.join(" · ");
        info.appendChild(metaEl);
      }

      var actions = document.createElement("div");
      actions.className = "collab-attachment-actions";

      var btnDl = document.createElement("button");
      btnDl.type = "button";
      btnDl.className = "collab-attachment-download";
      btnDl.textContent = "下载";
      btnDl.addEventListener("click", function () {
        ctx.onDownload(att, btnDl).catch(function (err) {
          window.alert(err && err.message ? err.message : String(err));
        });
      });
      actions.appendChild(btnDl);

      if (ctx.canDelete(att)) {
        var btnDel = document.createElement("button");
        btnDel.type = "button";
        btnDel.className = "collab-attachment-delete";
        btnDel.textContent = "删除";
        btnDel.addEventListener("click", function () {
          if (!window.confirm("确定删除附件「" + displayName + "」？")) return;
          btnDel.disabled = true;
          ctx
            .onDelete(att)
            .then(function () {
              return ctx.onRefresh();
            })
            .catch(function (err) {
              window.alert(err && err.message ? err.message : String(err));
              btnDel.disabled = false;
            });
        });
        actions.appendChild(btnDel);
      }

      li.appendChild(info);
      li.appendChild(actions);
      list.appendChild(li);
    });
    parentEl.appendChild(list);
  }

  function appendStepUploadControl(parentEl, chain, step, onRefresh) {
    var row = document.createElement("div");
    row.className = "collab-attachment-upload-row";
    var input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.className = "collab-attachment-upload-input hidden";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "collab-attachment-upload-btn";
    btn.textContent = "上传附件";
    btn.addEventListener("click", function () {
      input.click();
    });
    input.addEventListener("change", function () {
      var files = input.files;
      if (!files || !files.length) return;
      btn.disabled = true;
      btn.textContent = "上传中…";
      var chainId = chain.id;
      var stepId = step.id;
      var tasks = [];
      for (var i = 0; i < files.length; i++) {
        tasks.push(uploadCollabAttachmentFile(files[i], chainId, stepId));
      }
      Promise.all(tasks)
        .then(function () {
          return onRefresh();
        })
        .catch(function (err) {
          window.alert(err && err.message ? err.message : String(err));
        })
        .finally(function () {
          btn.disabled = false;
          btn.textContent = "上传附件";
          input.value = "";
        });
    });
    row.appendChild(input);
    row.appendChild(btn);
    parentEl.appendChild(row);
  }

  function appendStepLastStepHint(parentEl) {
    var row = document.createElement("div");
    row.className = "collab-step-complete-row collab-step-last-hint";
    var hint = document.createElement("p");
    hint.className = "collab-step-complete-hint";
    hint.textContent =
      "最后一步：Agent 在对话中完成报告后，将自动上传交付物并完成协同链，无需手动流转。";
    row.appendChild(hint);
    parentEl.appendChild(row);
  }

  function appendStepCompleteControl(parentEl, chain, step, stepAtts, onRefresh) {
    var row = document.createElement("div");
    row.className = "collab-step-complete-row";
    var attCount = (stepAtts || []).length;
    var hint = document.createElement("p");
    hint.className = "collab-step-complete-hint";
    hint.textContent =
      attCount > 0
        ? "确认本步附件无误后，可手动流转到下一步（无需 Agent 自动完成）。"
        : "须先上传至少 1 个本步附件，方可流转到下一步。";
    row.appendChild(hint);

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "collab-step-complete-btn";
    btn.textContent = "流转到下一步";
    if (attCount < 1) {
      btn.disabled = true;
      btn.title = "请先上传本步附件";
    }
    btn.addEventListener("click", function () {
      var attIds = (stepAtts || [])
        .map(function (att) {
          return String(att.id || "").trim();
        })
        .filter(Boolean);
      if (attIds.length < 1) {
        window.alert("本步骤尚未上传任何附件，请先上传附件后再流转。");
        return;
      }
      var confirmMsg =
        "确认将步骤 " +
        step.step_index +
        " 流转到下一步？\n" +
        "当前附件 " +
        attIds.length +
        " 个。";
      if (!window.confirm(confirmMsg)) return;

      var defaultSummary = "手动流转：本步骤已完成，交付物见下方附件。";
      var summary = window.prompt("流转说明（写入本步结果摘要）", defaultSummary);
      if (summary === null) return;
      summary = String(summary || "").trim();
      if (!summary) {
        window.alert("请填写流转说明");
        return;
      }

      var relayRaw = window.prompt("传递给下一步的说明（可选，取消则跳过）", "");
      var relayNote =
        relayRaw === null ? "" : String(relayRaw || "").trim();

      btn.disabled = true;
      btn.classList.add("is-busy");
      btn.textContent = "流转中…";
      completeCollabStep(chain.id, step.id, {
        result_summary: summary,
        relay_note: relayNote || null,
        attachment_ids: attIds,
      })
        .then(function () {
          return onRefresh();
        })
        .then(function () {
          return refresh();
        })
        .catch(function (err) {
          window.alert(err && err.message ? err.message : String(err));
        })
        .finally(function () {
          btn.classList.remove("is-busy");
          btn.disabled = attIds.length < 1;
          btn.textContent = "流转到下一步";
        });
    });
    row.appendChild(btn);
    parentEl.appendChild(row);
  }

  function setSectionExpanded(expanded) {
    sectionExpanded = !!expanded;
    if (sectionToggleEl) {
      sectionToggleEl.setAttribute("aria-expanded", sectionExpanded ? "true" : "false");
    }
    var chevron = document.getElementById("collab-section-chevron");
    if (chevron) chevron.classList.toggle("rotated", sectionExpanded);
    if (listEl) {
      listEl.classList.toggle("hidden", !sectionExpanded);
    }
  }

  function updateSectionUnreadBadge() {
    if (!sectionUnreadBadgeEl) return;
    var count = chains.filter(function (c) {
      return !!c.is_unread;
    }).length;
    if (count > 0) {
      sectionUnreadBadgeEl.textContent = count > 99 ? "99+" : String(count);
      sectionUnreadBadgeEl.classList.remove("hidden");
    } else {
      sectionUnreadBadgeEl.classList.add("hidden");
    }
  }

  function chainTitle(chain) {
    return String(chain.title || chain.id || "协同任务");
  }

  function renderList() {
    if (!listEl) return;
    listEl.innerHTML = "";
    if (!chains.length && !batchDeleteMode) {
      var empty = document.createElement("div");
      empty.className = "history-empty";
      empty.textContent = "暂无协同任务";
      listEl.appendChild(empty);
      updateSectionUnreadBadge();
      updateCollabBatchIcon();
      return;
    }

    chains.forEach(function (chain) {
      var row = document.createElement("div");
      var rowClass = "history-row collab-history-row";
      if (chain.id === selectedChainId) rowClass += " active";
      if (batchDeleteMode) rowClass += " batch-mode";
      row.className = rowClass;

      /* 批量模式复选框 */
      if (batchDeleteMode) {
        var checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "history-checkbox";
        checkbox.checked = !!batchSelectedChainIds[chain.id];
        checkbox.addEventListener("click", function (e) {
          e.stopPropagation();
          if (batchSelectedChainIds[chain.id]) {
            delete batchSelectedChainIds[chain.id];
          } else {
            batchSelectedChainIds[chain.id] = true;
          }
          renderList();
        });
        row.appendChild(checkbox);
      }

      var main = document.createElement("button");
      main.type = "button";
      main.className = "history-item-main collab-history-main";

      var titleRow = document.createElement("div");
      titleRow.className = "collab-row-title-line";

      var titleEl = document.createElement("span");
      titleEl.className = "history-item-title";
      titleEl.textContent = chainTitle(chain);
      titleRow.appendChild(titleEl);

      if (chain.is_unread) {
        var badge = document.createElement("span");
        badge.className = "collab-new-badge";
        badge.textContent = "NEW";
        titleRow.appendChild(badge);
      }

      var meta = document.createElement("div");
      meta.className = "collab-row-meta";
      var metaParts = [];
      if (chain.progress_text) metaParts.push(chain.progress_text);
      var listTime = formatCollabTimestamp(chain.updated_at || chain.created_at);
      if (listTime) metaParts.push(listTime);
      meta.textContent = metaParts.join(" · ");

      main.appendChild(titleRow);
      main.appendChild(meta);

      main.addEventListener("click", function () {
        if (batchDeleteMode) {
          if (batchSelectedChainIds[chain.id]) {
            delete batchSelectedChainIds[chain.id];
          } else {
            batchSelectedChainIds[chain.id] = true;
          }
          renderList();
          return;
        }
        openChain(chain.id);
      });

      row.appendChild(main);
      listEl.appendChild(row);
    });

    /* 填充协同空间标题行的批量操作内联控件 */
    var collabSlot = document.getElementById("collab-batch-slot");
    var collabLabel = document.getElementById("collab-history-label");
    if (batchDeleteMode && collabSlot && collabLabel && chains.length > 0) {
      var selectedCount = chains.filter(function (c) { return batchSelectedChainIds[c.id]; }).length;
      collabSlot.innerHTML =
        '<span class="batch-info-inline">' +
        (selectedCount > 0 ? "已选" + selectedCount : "") +
        "</span>" +
        '<button type="button" class="batch-sm-btn" id="collab-batch-select-all">全选</button>' +
        '<button type="button" class="batch-sm-btn" id="collab-batch-cancel">取消</button>' +
        '<button type="button" class="batch-sm-btn batch-sm-del" id="collab-batch-delete"' +
        (selectedCount === 0 ? " disabled" : "") +
        ">删除</button>";
      collabLabel.classList.add("batch-mode");
      var selectAllBtn = collabSlot.querySelector("#collab-batch-select-all");
      if (selectAllBtn) {
        selectAllBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          var allSelected = chains.every(function (c) { return batchSelectedChainIds[c.id]; });
          if (allSelected) {
            chains.forEach(function (c) { delete batchSelectedChainIds[c.id]; });
          } else {
            chains.forEach(function (c) { batchSelectedChainIds[c.id] = true; });
          }
          renderList();
        });
      }
      var cancelBtnEl = collabSlot.querySelector("#collab-batch-cancel");
      if (cancelBtnEl) {
        cancelBtnEl.addEventListener("click", function () {
          batchDeleteMode = false;
          batchSelectedChainIds = {};
          renderList();
        });
      }
      var delBtnEl = collabSlot.querySelector("#collab-batch-delete");
      if (delBtnEl) {
        delBtnEl.addEventListener("click", function () {
          batchDeleteChains();
        });
      }
    } else {
      if (collabSlot) collabSlot.innerHTML = "";
      if (collabLabel) collabLabel.classList.remove("batch-mode");
    }

    updateSectionUnreadBadge();
    updateCollabBatchIcon();
  }

  /* ---- 批量删除协同链 ---- */

  function batchDeleteChains() {
    var selectedIds = Object.keys(batchSelectedChainIds).filter(function (id) { return batchSelectedChainIds[id]; });
    if (!selectedIds.length) return;
    if (!window.confirm("确定删除选中的 " + selectedIds.length + " 条协同任务？")) return;
    var headers = authHeaders();
    if (!headers) return;
    fetch(adminApiBase + "/api/admin/collab/chains/batch", {
      method: "DELETE",
      headers: headers,
      body: JSON.stringify({ chain_ids: selectedIds }),
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data && data.success) {
          batchDeleteMode = false;
          batchSelectedChainIds = {};
          refresh();
        } else {
          window.alert("删除失败: " + (data && data.detail ? data.detail : "未知错误"));
        }
      })
      .catch(function (err) {
        window.alert("删除失败: " + (err.message || err));
      });
  }

  function renderDetail(chain, steps, attachments, reloadDetail) {
    if (!detailRootEl) return;
    detailRootEl.innerHTML = "";

    var userId = getCurrentUserId();
    var attList = Array.isArray(attachments) ? attachments : [];
    var attByStep = indexAttachmentsByStepId(attList);
    var attCtx = {
      onDownload: function (att, btn) {
        return downloadCollabAttachment(att.id, att.original_filename, btn);
      },
      onDelete: function (att) {
        return deleteCollabAttachment(att.id);
      },
      onRefresh: reloadDetail || function () {
        return Promise.resolve();
      },
      canDelete: function (att) {
        var step = (steps || []).find(function (s) {
          return String(s.id) === String(att.step_id);
        });
        return canDeleteAttachment(att, step, chain, steps, userId);
      },
    };

    var header = document.createElement("div");
    header.className = "collab-detail-header";

    var hTitle = document.createElement("h2");
    hTitle.className = "collab-detail-title";
    hTitle.textContent = chainTitle(chain);
    header.appendChild(hTitle);

    var hMeta = document.createElement("p");
    hMeta.className = "collab-detail-meta";
    var chainStatus = CHAIN_STATUS_LABELS[chain.status] || chain.status || "";
    hMeta.textContent =
      (chain.progress_text || "") +
      (chainStatus ? " · " + chainStatus : "") +
      (chain.initiator_name || chain.initiator_username
        ? " · 发起人 " + (chain.initiator_name || chain.initiator_username)
        : "");
    header.appendChild(hMeta);

    if (chain.description) {
      var desc = document.createElement("p");
      desc.className = "collab-detail-desc";
      desc.textContent = chain.description;
      header.appendChild(desc);
    }

    var chainTimes = formatChainTimeSummary(chain);
    if (chainTimes) {
      var timesEl = document.createElement("p");
      timesEl.className = "collab-detail-times";
      timesEl.textContent = chainTimes;
      header.appendChild(timesEl);
    }

    if (canDeleteCollabChain(chain, userId)) {
      var actionsRow = document.createElement("div");
      actionsRow.className = "collab-detail-actions";
      var delChainBtn = document.createElement("button");
      delChainBtn.type = "button";
      delChainBtn.className = "collab-chain-delete-btn";
      delChainBtn.textContent = "删除协同流程";
      delChainBtn.addEventListener("click", function () {
        if (
          !window.confirm(
            "确定删除协同流程「" +
              chainTitle(chain) +
              "」？\n将永久删除步骤记录与附件，且不可恢复。"
          )
        ) {
          return;
        }
        delChainBtn.disabled = true;
        deleteCollabChain(chain.id)
          .then(function () {
            selectedChainId = "";
            detailLoadSeq += 1;
            renderDetailPlaceholder();
            setTopBarTitle("协同空间");
            return refresh();
          })
          .catch(function (err) {
            window.alert(err && err.message ? err.message : String(err));
            delChainBtn.disabled = false;
          });
      });
      actionsRow.appendChild(delChainBtn);
      header.appendChild(actionsRow);
    } else if (String(chain.status) === "running") {
      var myRunningStep = (steps || []).find(function (s) {
        return (
          String(s.status) === "running" &&
          String(s.assignee_user_id) === userId
        );
      });
      if (myRunningStep) {
        var execRow = document.createElement("div");
        execRow.className = "collab-detail-actions";
        var execBtn = document.createElement("button");
        execBtn.type = "button";
        execBtn.className = "collab-step-execute-btn";
        execBtn.textContent = "开始执行本步";
        execBtn.addEventListener("click", function () {
          execBtn.disabled = true;
          startCollabStepExecution(chain, myRunningStep, attList, steps)
            .catch(function (err) {
              window.alert(err && err.message ? err.message : String(err));
            })
            .finally(function () {
              execBtn.disabled = false;
            });
        });
        execRow.appendChild(execBtn);
        header.appendChild(execRow);
      }
    } else if (String(chain.status) === "completed" && String(chain.initiator_user_id) === String(userId)) {
      var completedHint = document.createElement("p");
      completedHint.className = "collab-detail-hint";
      completedHint.textContent = "协同流程已完成，不可删除。";
      header.appendChild(completedHint);
    }

    detailRootEl.appendChild(header);

    var timeline = document.createElement("ol");
    timeline.className = "collab-timeline";

    (steps || []).forEach(function (step) {
      var li = document.createElement("li");
      var st = String(step.status || "pending");
      li.className = "collab-timeline-step collab-step-" + st;
      if (Number(chain.current_step) === Number(step.step_index) && chain.status === "running") {
        li.classList.add("collab-timeline-current");
      }

      var head = document.createElement("div");
      head.className = "collab-step-head";
      head.innerHTML =
        "<span class=\"collab-step-index\">步骤 " +
        step.step_index +
        "</span>" +
        "<span class=\"collab-step-status\">" +
        (STEP_STATUS_LABELS[st] || st) +
        "</span>";

      var who = document.createElement("div");
      who.className = "collab-step-who";
      who.textContent =
        "执行人: " +
        (step.assignee_name || step.assignee_username || step.assignee_user_id || "—");

      li.appendChild(head);
      li.appendChild(who);

      var stepTimesText = formatStepTimeSummary(step);
      if (stepTimesText) {
        var stepTimes = document.createElement("div");
        stepTimes.className = "collab-step-times";
        stepTimes.textContent = stepTimesText;
        li.appendChild(stepTimes);
      }

      if (step.task_prompt_rendered || step.task_prompt) {
        var prompt = document.createElement("div");
        prompt.className = "collab-step-prompt";
        prompt.textContent = formatPromptForDisplay(
          step.task_prompt_rendered || step.task_prompt
        );
        li.appendChild(prompt);
      }

      if (step.result_summary) {
        var summary = document.createElement("div");
        summary.className = "collab-step-result";
        summary.textContent = "结果: " + step.result_summary;
        li.appendChild(summary);
      }

      if (step.reject_reason) {
        var rej = document.createElement("div");
        rej.className = "collab-step-reject";
        rej.textContent = "退回原因: " + step.reject_reason;
        li.appendChild(rej);
      }

      if (step.relay_note) {
        var relay = document.createElement("div");
        relay.className = "collab-step-relay";
        relay.textContent = "传递说明: " + step.relay_note;
        li.appendChild(relay);
      }

      var stepId = String(step.id || "").trim();
      var stepAtts = stepId ? attByStep[stepId] || [] : [];
      var attWrap = document.createElement("div");
      attWrap.className = "collab-step-attachments";
      var attLabel = document.createElement("div");
      attLabel.className = "collab-step-attachments-label";
      attLabel.textContent = "附件 (" + stepAtts.length + ")";
      attWrap.appendChild(attLabel);
      if (canManageStepUpload(step, chain, steps, userId)) {
        appendStepUploadControl(attWrap, chain, step, attCtx.onRefresh);
      }
      appendAttachmentList(attWrap, stepAtts, attCtx);
      if (
        isLastCollabStep(step, chain) &&
        String(step.status) === "running" &&
        String(step.assignee_user_id) === userId
      ) {
        appendStepLastStepHint(attWrap);
      } else if (canCompleteStep(step, chain, userId)) {
        appendStepCompleteControl(attWrap, chain, step, stepAtts, attCtx.onRefresh);
      }
      li.appendChild(attWrap);
      if (stepId) delete attByStep[stepId];

      timeline.appendChild(li);
    });

    detailRootEl.appendChild(timeline);

    var orphanAtts = [];
    Object.keys(attByStep).forEach(function (sid) {
      orphanAtts = orphanAtts.concat(attByStep[sid]);
    });
    if (orphanAtts.length) {
      var orphanSection = document.createElement("section");
      orphanSection.className = "collab-attachments-section";
      var orphanTitle = document.createElement("h3");
      orphanTitle.className = "collab-attachments-title";
      orphanTitle.textContent = "其他附件";
      orphanSection.appendChild(orphanTitle);
      appendAttachmentList(orphanSection, orphanAtts, attCtx);
      detailRootEl.appendChild(orphanSection);
    } else if (attList.length && !(steps || []).length) {
      var onlySection = document.createElement("section");
      onlySection.className = "collab-attachments-section";
      var onlyTitle = document.createElement("h3");
      onlyTitle.className = "collab-attachments-title";
      onlyTitle.textContent = "附件 (" + attList.length + ")";
      onlySection.appendChild(onlyTitle);
      appendAttachmentList(onlySection, attList, attCtx);
      detailRootEl.appendChild(onlySection);
    }
  }

  function renderDetailLoading() {
    if (!detailRootEl) return;
    detailRootEl.innerHTML =
      '<div class="collab-detail-loading" role="status" aria-live="polite">' +
      '<div class="collab-detail-spinner" aria-hidden="true"></div>' +
      "<span>加载中…</span></div>";
  }

  function renderDetailError(message) {
    if (!detailRootEl) return;
    detailRootEl.innerHTML =
      '<div class="collab-detail-empty">加载失败: ' +
      String(message || "未知错误") +
      "</div>";
  }

  function renderDetailPlaceholder() {
    if (!detailRootEl) return;
    detailRootEl.innerHTML =
      '<div class="collab-detail-empty">从左侧「协同空间」选择一条协同任务查看进度</div>';
  }

  function markChainRead(chainId) {
    adminFetch("/api/admin/collab/chains/" + encodeURIComponent(chainId) + "/read", {
      method: "POST",
    })
      .catch(function () {
        /* ignore */
      })
      .then(function () {
        if (selectedChainId !== chainId) return;
        chains = chains.map(function (c) {
          if (c.id === chainId) {
            return Object.assign({}, c, { is_unread: false });
          }
          return c;
        });
        renderList();
      });
  }

  /**
   * 加载协同链详情。仅当 loadSeq 仍为当前选中任务时才渲染。
   * @param {boolean} showLoading 用户切换任务时为 true；后台轮询刷新为 false
   */
  async function loadChainDetail(chainId, loadSeq, showLoading) {
    abortDetailLoad();
    detailAbortController = new AbortController();
    var signal = detailAbortController.signal;

    if (showLoading) {
      renderDetailLoading();
    }

    try {
      var data = await adminFetch(
        "/api/admin/collab/chains/" + encodeURIComponent(chainId),
        { signal: signal }
      );
      if (!isDetailLoadCurrent(chainId, loadSeq)) return;
      if (data.chain) {
        var chainOut = data.chain;
        if (!chainOut.progress_text) {
          var cached = chains.find(function (c) {
            return c.id === chainId;
          });
          if (cached && cached.progress_text) {
            chainOut = Object.assign({}, chainOut, {
              progress_text: cached.progress_text,
            });
          }
        }
        var stepsOut = data.steps || [];
        var attachmentsOut = data.attachments || [];
        var reloadDetail = function () {
          return loadChainDetail(chainId, loadSeq, false);
        };
        renderDetail(chainOut, stepsOut, attachmentsOut, reloadDetail);
        setTopBarTitle(chainTitle(chainOut));
        maybeSyncPriorAttachments(chainOut, stepsOut, attachmentsOut);
      }
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!isDetailLoadCurrent(chainId, loadSeq)) return;
      renderDetailError(e.message || e);
    } finally {
      if (detailAbortController && detailAbortController.signal === signal) {
        detailAbortController = null;
      }
    }
  }

  function maybeSyncPriorAttachments(chain, steps, attachments) {
    var userId = getCurrentUserId();
    if (!userId || !chain || chain.status !== "running") return;
    var myStep = (steps || []).find(function (s) {
      return (
        String(s.status) === "running" && String(s.assignee_user_id) === userId
      );
    });
    if (!myStep) return;
    var stepIndex = Number(myStep.step_index);
    if (stepIndex <= 1) return;
    var prior = buildPriorAttachments(attachments, steps, stepIndex);
    if (!prior.length) return;
    syncInboundViaBridge({
      chain_id: chain.id,
      step_index: stepIndex,
      prior_attachments: prior,
    }).then(function (result) {
      if (!result || !result.ok) return;
      var savedN =
        result.saved && result.saved.length ? result.saved.length : 0;
      var skippedN =
        result.skipped && result.skipped.length ? result.skipped.length : 0;
      if (!savedN && !skippedN) return;
      var inboundNote = document.querySelector(".collab-inbound-sync-note");
      if (!inboundNote && detailRootEl) {
        inboundNote = document.createElement("p");
        inboundNote.className = "collab-inbound-sync-note";
        detailRootEl.insertBefore(inboundNote, detailRootEl.firstChild);
      }
      if (inboundNote) {
        var parts = [];
        if (savedN) parts.push("新同步 " + savedN + " 个");
        if (skippedN) parts.push("已存在 " + skippedN + " 个");
        inboundNote.textContent =
          "上游附件 " +
          parts.join("，") +
          "（本地协同目录：" +
          (result.base_dir || "") +
          "）";
      }
    });
  }

  function syncInboundAttachments(msg) {
    return syncInboundViaBridge(msg).then(function (result) {
      if (!result || !result.ok) return result;
      var savedN =
        result.saved && result.saved.length ? result.saved.length : 0;
      if (savedN) {
        window.alert(
          "已自动同步 " +
            savedN +
            " 个上游附件到本地协同目录。\n" +
            (result.base_dir || "")
        );
      }
      return result;
    });
  }

  function openChain(chainId) {
    if (!chainId) return;

    detailLoadSeq += 1;
    var loadSeq = detailLoadSeq;

    selectedChainId = chainId;
    renderList();
    setMainView("collab");

    var chain = chains.find(function (c) {
      return c.id === chainId;
    });
    setTopBarTitle(chain ? chainTitle(chain) : "协同任务");

    markChainRead(chainId);
    loadChainDetail(chainId, loadSeq, true);
  }

  async function refresh() {
    if (!authHeaders()) {
      abortDetailLoad();
      chains = [];
      selectedChainId = "";
      detailLoadSeq += 1;
      renderList();
      renderDetailPlaceholder();
      updateSectionUnreadBadge();
      return;
    }
    try {
      var data = await adminFetch("/api/admin/collab/chains");
      chains = Array.isArray(data.chains) ? data.chains : [];
      renderList();
      if (selectedChainId) {
        var still = chains.some(function (c) {
          return c.id === selectedChainId;
        });
        if (still) {
          var loadSeq = detailLoadSeq;
          var hasContent =
            detailRootEl &&
            !detailRootEl.querySelector(".collab-detail-loading") &&
            !detailRootEl.querySelector(".collab-detail-empty");
          await loadChainDetail(selectedChainId, loadSeq, !hasContent);
        } else {
          abortDetailLoad();
          detailLoadSeq += 1;
          selectedChainId = "";
          renderDetailPlaceholder();
          setTopBarTitle("协同空间");
        }
      }
    } catch (e) {
      if (listEl) {
        listEl.innerHTML = "";
        var err = document.createElement("div");
        err.className = "history-empty";
        err.textContent = "加载协同任务失败";
        listEl.appendChild(err);
      }
    }
  }

  function clear() {
    abortDetailLoad();
    detailLoadSeq += 1;
    chains = [];
    selectedChainId = "";
    renderList();
    renderDetailPlaceholder();
    updateSectionUnreadBadge();
  }

  /** WebSocket 协同通知：立即标未读，避免仅刷新列表时 is_unread 尚未落库 */
  function handleNotification(msg) {
    var chainId = String((msg && msg.chain_id) || "").trim();
    if (!chainId) return;
    var title = String((msg && msg.chain_title) || "").trim();
    var found = false;
    chains = chains.map(function (c) {
      if (c.id === chainId) {
        found = true;
        return Object.assign({}, c, { is_unread: true });
      }
      return c;
    });
    if (!found) {
      chains.unshift({
        id: chainId,
        title: title || chainId,
        is_unread: true,
        progress_text: "",
      });
    }
    renderList();
  }

  function startPoll() {
    stopPoll();
    pollTimer = setInterval(function () {
      if (document.hidden) return;
      refresh();
    }, COLLAB_POLL_MS);
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  /* 侧栏批量管理图标 */
  function updateCollabBatchIcon() {
    var btn = document.getElementById("sidebar-batch-collab-btn");
    if (btn) btn.classList.toggle("is-active", batchDeleteMode);
  }

  function bindCollabBatchIcon() {
    var btn = document.getElementById("sidebar-batch-collab-btn");
    if (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        batchDeleteMode = !batchDeleteMode;
        batchSelectedChainIds = {};
        renderList();
      });
    }
  }

  if (sectionToggleEl) {
    sectionToggleEl.addEventListener("click", function (e) {
      e.preventDefault();
      setSectionExpanded(!sectionExpanded);
    });
  }

  setSectionExpanded(true);
  renderDetailPlaceholder();

  /**
   * After collab-task agent stream ends: on last step, upload generated_files and complete chain.
   */
  async function tryFinalizeLastStepFromAgent(conv, assistantText) {
    try {
      await tryFinalizeLastStepFromAgentImpl(conv, assistantText);
    } catch (e) {
      if (typeof console !== "undefined" && console.error) {
        console.error("collab last-step finalize failed:", e);
      }
    }
  }

  async function tryFinalizeLastStepFromAgentImpl(conv, assistantText) {
    if (!conv || !Array.isArray(conv.messages)) return;
    var ctx = extractCollabContextFromMessages(conv.messages);
    if (!ctx || !ctx.chain_id || !ctx.step_index) return;
    var paths = extractGeneratedFilesFromText(assistantText);
    if (!paths.length) return;

    var userId = getCurrentUserId();
    if (!userId) return;

    var data = await adminFetch(
      "/api/admin/collab/chains/" + encodeURIComponent(ctx.chain_id)
    );
    var chain = data.chain;
    var steps = data.steps || [];
    if (!chain || String(chain.status) !== "running") return;

    var step = steps.find(function (s) {
      return Number(s.step_index) === Number(ctx.step_index);
    });
    if (!step || String(step.status) !== "running") return;
    if (String(step.assignee_user_id) !== userId) return;
    if (!isLastCollabStep(step, chain)) return;

    var existingAtts = (data.attachments || []).filter(function (att) {
      return String(att.step_id || "") === String(step.id || "");
    });
    var existingByName = Object.create(null);
    var attIds = [];
    existingAtts.forEach(function (att) {
      var n = decodeCollabFilename(att.original_filename || "");
      var aid = String(att.id || "").trim();
      if (n && aid) {
        existingByName[n] = aid;
        if (attIds.indexOf(aid) < 0) attIds.push(aid);
      }
    });
    var pathsToUpload = paths.filter(function (p) {
      var base = String(p || "").replace(/^.*[/\\]/, "");
      return base && !existingByName[base];
    });
    if (pathsToUpload.length) {
      var newIds = await uploadCollabPathsViaBridge(
        pathsToUpload,
        ctx.chain_id,
        step.id
      );
      (newIds || []).forEach(function (id) {
        if (id && attIds.indexOf(id) < 0) attIds.push(id);
      });
    }
    if (!attIds.length) return;

    var fresh = await adminFetch(
      "/api/admin/collab/chains/" + encodeURIComponent(ctx.chain_id)
    );
    var freshStep = (fresh.steps || []).find(function (s) {
      return Number(s.step_index) === Number(ctx.step_index);
    });
    if (!freshStep || String(freshStep.status) !== "running") return;

    var summary =
      "协同最后一步已完成，已自动上传 " +
      attIds.length +
      " 个交付物。";
    await completeCollabStep(ctx.chain_id, step.id, {
      result_summary: summary,
      result_detail: JSON.stringify({ generated_files: paths }),
      attachment_ids: attIds,
    });
    await refresh();
    if (selectedChainId === ctx.chain_id) {
      await loadChainDetail(ctx.chain_id, detailLoadSeq, false);
    }
  }

  async function startCollabStepExecution(chain, step, attachments, steps) {
    if (!chain || !step) return;
    var stepIndex = Number(step.step_index);
    if (stepIndex <= 1) return;
    var prior = buildPriorAttachments(attachments, steps, stepIndex);
    if (prior.length) {
      await syncInboundViaBridge({
        chain_id: chain.id,
        step_index: stepIndex,
        prior_attachments: prior,
      });
    }
    var userText = buildCollabExecutionUserText(
      chain,
      step,
      step.task_prompt_rendered || step.task_prompt || ""
    );
    setMainView("chat");
    await startConversationWithMessage(userText, { autoSend: true });
  }

  return {
    refresh: refresh,
    clear: clear,
    startPoll: startPoll,
    stopPoll: stopPoll,
    setSectionExpanded: setSectionExpanded,
    openChain: openChain,
    handleNotification: handleNotification,
    bindCollabBatchIcon: bindCollabBatchIcon,
    tryFinalizeLastStepFromAgent: tryFinalizeLastStepFromAgent,
    augmentCollabUserInputForSend: augmentCollabUserInputForSend,
  };
}

import {
  getSession,
} from "./js/storage.js?v=2026052814";
import { createChatController } from "./js/chat.js?v=2026052814";
import { createSettingsController } from "./js/settings.js?v=2026060412";
import { createAuthController } from "./js/auth.js?v=2026060410";
import { renderAppLayout } from "./js/layout.js?v=2026052814";
import { createTasksController } from "./js/tasks.js?v=2026052814";
import { createCollabController } from "./js/collab.js?v=2026052915";
import { createKnowledgeController } from "./js/knowledge.js?v=2026053002";
import { createContactsController } from "./js/contacts.js?v=2026060101";
import { initAutoHideScrollbars } from "./js/scrollbars.js?v=2026060420";

(function () {
  "use strict";

  initAutoHideScrollbars();

  function getParams() {
    var q = new URLSearchParams(window.location.search);
    var api = q.get("api_base") || "http://127.0.0.1:8009";
    var adminApi = q.get("admin_api_base");
    var rawConfig = q.get("desktop_config");
    var osUsername = q.get("os_username") || "default";
    var desktopConfig = {};
    if (rawConfig) {
      try {
        desktopConfig = JSON.parse(rawConfig);
      } catch (e) {
        desktopConfig = {};
      }
    }
    adminApi =
      adminApi ||
      desktopConfig.admin_api_base ||
      "";
    if (!adminApi) {
      console.error(
        "admin_api_base missing: set WORKMATE_ADMIN_API_BASE in .env and restart desktop"
      );
      adminApi = "http://127.0.0.1:8010";
    }
    return {
      apiBase: api.replace(/\/$/, ""),
      adminApiBase: adminApi.replace(/\/$/, ""),
      desktopConfig: desktopConfig,
      osUsername: osUsername,
    };
  }

  function normalizeJoin(base, child) {
    var root = String(base || "").replace(/[\\/]+$/, "");
    var leaf = String(child || "").replace(/^[\\/]+/, "");
    if (!root) return leaf;
    if (!leaf) return root;
    return root + "/" + leaf;
  }

  function normalizePathSlashes(path) {
    return String(path || "").replace(/\\/g, "/");
  }

  function resolveDefaultOutputPath(params, appSession) {
    var cfg = params.desktopConfig || {};
    var workspaceRoot = cfg.workspace_root || "";
    var outputBase = cfg.output_base_dir || "";
    var template = cfg.output_dir_template || "{output_base_dir}/{username}";
    var username =
      (appSession && appSession.user && appSession.user.username) || params.osUsername || "default";

    if (template.indexOf("{output_base_dir}") >= 0 && !outputBase) return "-";
    if (!workspaceRoot && template.indexOf("{workspace_root}") >= 0) return "-";
    if (
      template.indexOf("{workspace_root}") >= 0 ||
      template.indexOf("{output_base_dir}") >= 0 ||
      template.indexOf("{username}") >= 0
    ) {
      return normalizePathSlashes(
        template
        .replace(/\{workspace_root\}/g, workspaceRoot)
        .replace(/\{output_base_dir\}/g, outputBase)
        .replace(/\{username\}/g, username)
      );
    }
    return normalizePathSlashes(normalizeJoin(workspaceRoot || outputBase, username));
  }

  function renderDefaultOutputPath(params, appSession) {
    var el = document.getElementById("pref-output-path");
    if (!el) return;
    el.textContent = resolveDefaultOutputPath(params, appSession);
  }

  var OPTIONAL_DESKTOP_STRING_KEYS = [
    "admin_api_base",
    "logs_dir",
    "output_base_dir",
    "webengine_storage_root",
    "wechat_attachment_save_dir",
    "wechat_attachment_cache_file",
    "wechat_audio_cache_file",
    "wechat_window_title",
    "wechat_process_name",
    "wechat_ai_reply_prefix",
    "mate_name",
    "company_name",
    "department_name",
    "mate_title",
    "image_provider",
    "llm_provider",
    "template_dir",
    "image_template_dir",
  ];

  function pickConfigFields(input) {
    var o = {
      workspace_root: (input && input.workspace_root) || "",
      output_dir_template: (input && input.output_dir_template) || "{output_base_dir}/{username}",
      auto_create_workspace_root:
        input && typeof input.auto_create_workspace_root === "boolean"
          ? input.auto_create_workspace_root
          : true,
    };
    if (!input || typeof input !== "object") return o;
    OPTIONAL_DESKTOP_STRING_KEYS.forEach(function (k) {
      if (Object.prototype.hasOwnProperty.call(input, k)) {
        o[k] = input[k] == null ? "" : String(input[k]);
      }
    });
    return o;
  }

  function parseJsonSafely(text, fallback) {
    try {
      return JSON.parse(text);
    } catch (e) {
      return fallback;
    }
  }

  function initDesktopBridge() {
    return new Promise(function (resolve) {
      if (!window.qt || !window.qt.webChannelTransport || typeof QWebChannel !== "function") {
        resolve(null);
        return;
      }
      new QWebChannel(window.qt.webChannelTransport, function (channel) {
        resolve((channel.objects && channel.objects.desktopBridge) || null);
      });
    });
  }

  function getBridgeConfig(bridge) {
    return new Promise(function (resolve) {
      if (!bridge || typeof bridge.get_desktop_config !== "function") {
        resolve(null);
        return;
      }
      bridge.get_desktop_config(function (raw) {
        var parsed = parseJsonSafely(raw, null);
        resolve(parsed && typeof parsed === "object" ? parsed : null);
      });
    });
  }

  function saveBridgeConfig(bridge, data) {
    return new Promise(function (resolve) {
      if (!bridge || typeof bridge.save_desktop_config !== "function") {
        resolve({ ok: false, message: "bridge unavailable" });
        return;
      }
      bridge.save_desktop_config(JSON.stringify(data || {}), function (raw) {
        resolve(parseJsonSafely(raw, { ok: false, message: "save failed" }));
      });
    });
  }

  function resetBridgeConfig(bridge) {
    return new Promise(function (resolve) {
      if (!bridge || typeof bridge.reset_desktop_config !== "function") {
        resolve({ ok: false, message: "bridge unavailable" });
        return;
      }
      bridge.reset_desktop_config(function (raw) {
        resolve(parseJsonSafely(raw, { ok: false, message: "reset failed" }));
      });
    });
  }

  function getBridgeSkillsConfig(bridge) {
    return new Promise(function (resolve) {
      if (!bridge || typeof bridge.get_skills_config !== "function") {
        resolve({ ok: false, message: "bridge unavailable" });
        return;
      }
      bridge.get_skills_config(function (raw) {
        resolve(parseJsonSafely(raw, { ok: false, message: "load failed" }));
      });
    });
  }

  function saveBridgeSkillsConfig(bridge, data) {
    return new Promise(function (resolve) {
      if (!bridge || typeof bridge.save_skills_config !== "function") {
        resolve({ ok: false, message: "bridge unavailable" });
        return;
      }
      bridge.save_skills_config(JSON.stringify(data || {}), function (raw) {
        resolve(parseJsonSafely(raw, { ok: false, message: "save failed" }));
      });
    });
  }

  function installSkillPackageViaBridge(bridge, task) {
    return new Promise(function (resolve) {
      if (!bridge || typeof bridge.install_skill_package !== "function") {
        resolve({ ok: false, message: "bridge unavailable" });
        return;
      }
      var session = getSession();
      var payload = {
        task_id: task.task_id != null && task.task_id !== "" ? String(task.task_id) : "",
        skill_name: String(task.skill_name || ""),
        version: String(task.version || ""),
        download_url: String(task.download_url || ""),
        sha256: String(task.sha256 || ""),
        admin_api_base: params.adminApiBase || "",
        bearer_token: session && session.token ? String(session.token) : "",
      };
      bridge.install_skill_package(JSON.stringify(payload), function (raw) {
        resolve(parseJsonSafely(raw, { ok: false, message: "invalid response" }));
      });
    });
  }

  function getBridgeSkillInventory(bridge) {
    return new Promise(function (resolve) {
      if (!bridge || typeof bridge.get_skill_inventory !== "function") {
        resolve(null);
        return;
      }
      bridge.get_skill_inventory(function (raw) {
        resolve(parseJsonSafely(raw, null));
      });
    });
  }

  async function fetchMcpRuntimeCheck() {
    try {
      var res = await fetch(params.apiBase + "/api/desktop/mcp_runtime_check", {
        method: "GET",
        cache: "no-store",
      });
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  function normalizeSkillsConfig(raw) {
    var source = raw && typeof raw === "object" ? raw : {};
    var skillsNode = source.skills && typeof source.skills === "object" ? source.skills : source;
    var normalized = {};
    Object.keys(skillsNode || {}).forEach(function (name) {
      var val = skillsNode[name];
      if (val && typeof val === "object") {
        normalized[name] = {
          description: String(val.description || ""),
          enabled: !!val.enabled,
        };
      } else {
        normalized[name] = {
          description: "",
          enabled: !!val,
        };
      }
    });
    return { skills: normalized };
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  var lastMcpHealthForBadge = null;

  function clearSettingsMcpBadge() {
    if (!settingsRiskBadge || !settingsRiskCount || !btnSettings) return;
    settingsRiskBadge.classList.add("hidden");
    settingsRiskBadge.classList.remove("is-risk", "is-unknown");
    settingsRiskCount.textContent = "0";
    btnSettings.title = "设置";
    btnSettings.setAttribute("aria-label", "设置");
  }

  function setSettingsMcpBadgeRisk(hasRisk, summary, missingCount) {
    if (!settingsRiskBadge || !settingsRiskCount || !btnSettings) return;
    var risk = !!hasRisk;
    if (!risk) {
      clearSettingsMcpBadge();
      return;
    }
    var missing = Number(missingCount);
    if (!Number.isFinite(missing) || missing < 0) missing = 0;
    settingsRiskBadge.classList.remove("hidden", "is-unknown");
    settingsRiskBadge.classList.add("is-risk");
    var label =
      missing > 0 ? String(missing > 99 ? "99+" : missing) : "!";
    settingsRiskCount.textContent = label;
    var tip = "设置（MCP 风险）";
    if (missing > 0) tip += "：" + String(missing) + " 项依赖缺失";
    if (summary) tip += (missing > 0 ? "；" : "：") + String(summary);
    btnSettings.title = tip;
    btnSettings.setAttribute("aria-label", tip);
  }

  function setSettingsMcpBadgeUnknown(hint) {
    if (!settingsRiskBadge || !settingsRiskCount || !btnSettings) return;
    settingsRiskBadge.classList.remove("hidden", "is-risk");
    settingsRiskBadge.classList.add("is-unknown");
    settingsRiskCount.textContent = "?";
    var tip = hint
      ? "设置（自检未读）：" + String(hint)
      : "设置（无法读取 MCP 自检，请稍后重试）";
    btnSettings.title = tip;
    btnSettings.setAttribute("aria-label", tip);
  }

  function applyDesktopMcpHealthToBadge(state) {
    if (!state || !state.loaded) return;
    if (!settingsRiskBadge || !settingsRiskCount || !btnSettings) return;
    if (state.unknown) {
      if (lastMcpHealthForBadge && lastMcpHealthForBadge.hasRisk) {
        setSettingsMcpBadgeRisk(
          true,
          lastMcpHealthForBadge.summary,
          lastMcpHealthForBadge.missingCount
        );
        return;
      }
      setSettingsMcpBadgeUnknown(state.summary || "");
      return;
    }
    var missing =
      typeof state.missingCount === "number" ? state.missingCount : 0;
    lastMcpHealthForBadge = {
      hasRisk: !!state.hasRisk,
      missingCount: missing,
      summary: state.summary || "",
    };
    if (state.hasRisk) {
      setSettingsMcpBadgeRisk(true, state.summary || "", missing);
    } else {
      clearSettingsMcpBadge();
    }
  }

  renderAppLayout(document.getElementById("app-root"));

  var params = getParams();
  var bootOverlay = document.getElementById("boot-overlay");
  var bootMessage = document.getElementById("boot-message");
  var bootStageTextEl = document.getElementById("boot-stage-text");
  var bootStageNameEl = document.getElementById("boot-stage-name");
  var bootProgressFillEl = document.getElementById("boot-progress-fill");
  var bootLogEl = document.getElementById("boot-log");
  var loginScreen = document.getElementById("login-screen");
  var appShell = document.getElementById("app-shell");
  var loginForm = document.getElementById("login-form");
  var loginError = document.getElementById("login-error");
  var loginSubmit = document.getElementById("login-submit");
  var loginTerms = document.getElementById("login-terms");
  var loginClose = document.getElementById("login-close");

  var sidebarUsername = document.getElementById("sidebar-username");
  var sidebarAvatar = document.getElementById("sidebar-avatar");
  var settingsAvatar = document.getElementById("settings-avatar");
  var settingsUsername = document.getElementById("settings-username");

  var settingsModal = document.getElementById("settings-modal");
  var btnSettings = document.getElementById("btn-settings");
  var settingsRiskBadge = document.getElementById("settings-risk-badge");
  var settingsRiskCount = document.getElementById("settings-risk-count");
  var settingsClose = document.getElementById("settings-close");
  var btnLogout = document.getElementById("btn-logout");

  var prefSecurity = document.getElementById("pref-security");
  var prefSleep = document.getElementById("pref-sleep");
  var prefTools = document.getElementById("pref-tools");
  var cfgOutputBaseDir = document.getElementById("cfg-output-base-dir");
  var cfgWechatWindowTitle = document.getElementById("cfg-wechat-window-title");
  var cfgWechatProcessName = document.getElementById("cfg-wechat-process-name");
  var cfgWechatAiReplyPrefix = document.getElementById("cfg-wechat-ai-reply-prefix");
  var cfgAutoCreateRoot = document.getElementById("cfg-auto-create-root");
  var cfgSaveLocal = document.getElementById("cfg-save-local");
  var cfgResetDefault = document.getElementById("cfg-reset-default");
  var cfgSaveHint = document.getElementById("cfg-save-hint");
  /* 允许访问路径 DOM 引用 */
  var mcpReadDirsList = document.getElementById("mcp-read-dirs-list");
  var cfgAddDirBtn = document.getElementById("cfg-add-dir-btn");
  /* 通用设置 - 模型与模板 DOM 引用 */
  var cfgImageProvider = document.getElementById("cfg-image-provider");
  var cfgLlmProvider = document.getElementById("cfg-llm-provider");
  var cfgTemplateDir = document.getElementById("cfg-template-dir");
  var cfgImageTemplateDir = document.getElementById("cfg-image-template-dir");
  /* 通用设置 - 记忆与压缩 DOM 引用 */
  var cfgMemoryCompressEnabled = document.getElementById("cfg-memory-compress-enabled");
  var cfgMemoryCompressThreshold = document.getElementById("cfg-memory-compress-threshold");
  var cfgMemoryEnableTopicSearch = document.getElementById("cfg-memory-enable-topic-search");
  var cfgMemorySearchCandidateLimit = document.getElementById("cfg-memory-search-candidate-limit");
  var cfgMemoryShortTermTasks = document.getElementById("cfg-memory-short-term-tasks");
  var cfgMemoryMidTermTasks = document.getElementById("cfg-memory-mid-term-tasks");
  var cfgMemoryRelevantTasksLimit = document.getElementById("cfg-memory-relevant-tasks-limit");
  /* 通用设置 - 沙箱与子代理 DOM 引用 */
  var cfgUseSandbox = document.getElementById("cfg-use-sandbox");
  var cfgEnableSubagents = document.getElementById("cfg-enable-subagents");
  /* 微信设置 - 附件与缓存 DOM 引用 */
  var cfgWechatAttachmentSaveDir = document.getElementById("cfg-wechat-attachment-save-dir");
  var cfgWechatAttachmentCacheFile = document.getElementById("cfg-wechat-attachment-cache-file");
  var cfgWechatAudioCacheFile = document.getElementById("cfg-wechat-audio-cache-file");
  var mcpHealthSummary = document.getElementById("mcp-health-summary");
  var mcpHealthMissing = document.getElementById("mcp-health-missing");
  var mcpHealthServers = document.getElementById("mcp-health-servers");
  var mcpHealthRefresh = document.getElementById("mcp-health-refresh");
  var btnSkills = document.getElementById("btn-skills");
  var skillsModal = document.getElementById("skills-modal");
  var skillsClose = document.getElementById("skills-close");
  var skillsSearchInput = document.getElementById("skills-search-input");
  var skillsManageLink = document.getElementById("skills-manage-link");
  var skillsList = document.getElementById("skills-list");
  var skillsSaveHint = document.getElementById("skills-save-hint");
  var skillsSyncState = document.getElementById("skills-sync-state");
  var skillsManageModal = document.getElementById("skills-manage-modal");
  var skillsManageClose = document.getElementById("skills-manage-close");
  var skillsManageList = document.getElementById("skills-manage-list");
  var skillsManageSaveHint = document.getElementById("skills-manage-save-hint");
  var skillsManageSyncState = document.getElementById("skills-manage-sync-state");
  var composerSkillChips = document.getElementById("composer-skill-chips");
  var composerMcpChips = document.getElementById("composer-mcp-chips");
  var btnMcp = document.getElementById("btn-mcp");
  var mcpModal = document.getElementById("mcp-modal");
  var mcpClose = document.getElementById("mcp-close");
  var mcpToolSearchInput = document.getElementById("mcp-tool-search-input");
  var mcpToolList = document.getElementById("mcp-tool-list");
  var mcpToolStatusHint = document.getElementById("mcp-tool-status-hint");
  var mcpToolConfirmBtn = document.getElementById("mcp-tool-confirm");
  var mcpToolCancelBtn = document.getElementById("mcp-tool-cancel");

  var conversationListEl = document.getElementById("conversation-list");
  var schedulerConversationListEl = document.getElementById("scheduler-conversation-list");
  var messagesEl = document.getElementById("messages");

  var confirmOverlay = document.getElementById("confirm-overlay");
  var confirmTitleEl = document.getElementById("confirm-dialog-title");
  var confirmDescEl = document.getElementById("confirm-dialog-desc");
  var confirmBtnOk = document.getElementById("confirm-dialog-ok");
  var confirmBtnCancel = document.getElementById("confirm-dialog-cancel");

  function setComposerBusy(busy) {
    var ta = document.getElementById("composer-input");
    var send = document.getElementById("btn-send");
    var inner = document.querySelector(".composer-inner");
    if (ta) ta.disabled = !!busy;
    if (send) send.disabled = !!busy;
    if (inner) inner.classList.toggle("composer-busy", !!busy);
  }

  var bootTickerTimer = null;
  var bootBaseMessage = "";
  var bootLogLines = [];

  function appendBootLog(message) {
    var line = String(message || "").trim();
    if (!line) return;
    var stamp = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    bootLogLines.push("[" + stamp + "] " + line);
    if (bootLogLines.length > 24) bootLogLines.shift();
    if (bootLogEl) {
      bootLogEl.textContent = bootLogLines.join("\n");
      bootLogEl.scrollTop = bootLogEl.scrollHeight;
    }
  }

  function setBootStage(stage, stageName, progressPercent) {
    if (bootStageTextEl && stage) bootStageTextEl.textContent = stage;
    if (bootStageNameEl && stageName) bootStageNameEl.textContent = stageName;
    if (bootProgressFillEl && typeof progressPercent === "number") {
      var pct = Math.max(4, Math.min(100, progressPercent));
      bootProgressFillEl.style.width = pct + "%";
    }
  }

  function startBootTicker() {
    if (bootTickerTimer) return;
    var dots = 0;
    bootTickerTimer = setInterval(function () {
      if (!bootMessage || !bootBaseMessage) return;
      dots = (dots + 1) % 4;
      bootMessage.textContent = bootBaseMessage + ".".repeat(dots);
    }, 420);
  }

  function stopBootTicker() {
    if (!bootTickerTimer) return;
    clearInterval(bootTickerTimer);
    bootTickerTimer = null;
  }

  function showBoot(message) {
    if (message) {
      bootBaseMessage = message;
      if (bootMessage) bootMessage.textContent = message;
    }
    if (bootOverlay) bootOverlay.classList.remove("hidden");
    setComposerBusy(true);
    startBootTicker();
  }

  function hideBoot() {
    if (bootOverlay) bootOverlay.classList.add("hidden");
    setComposerBusy(false);
    stopBootTicker();
    bootBaseMessage = "";
    bootLogLines = [];
    if (bootLogEl) bootLogEl.textContent = "";
  }

  async function waitForBackendReady() {
    var url = params.apiBase + "/agent/health";
    var startAt = Date.now();
    var tries = 0;
    while (true) {
      tries += 1;
      try {
        var res = await fetch(url, { method: "GET", cache: "no-store" });
        if (res.ok) {
          appendBootLog("本地服务健康检查通过");
          return true;
        }
      } catch (e) {
        /* ignore and continue polling */
      }
      if (Date.now() - startAt > 30000) {
        return false;
      }
      showBoot("正在启动本地服务，请稍候…");
      setBootStage("阶段 1/2", "启动服务", Math.min(46, 10 + tries * 4));
      if (tries === 1) appendBootLog("开始检测后端服务健康状态");
      await new Promise(function (resolve) {
        setTimeout(resolve, tries < 10 ? 450 : 900);
      });
    }
  }

  async function triggerBackendPreload(force) {
    var payload = {
      force: !!force,
      wait: false,
    };
    try {
      var res = await fetch(params.apiBase + "/agent/preload", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(payload),
      });
      // 旧后端无此接口：视为不阻塞
      if (res.status === 404) return false;
      if (res.ok) appendBootLog(force ? "已触发强制预热请求" : "已触发预热请求");
      return res.ok;
    } catch (e) {
      return false;
    }
  }

  async function getPreloadStatus() {
    try {
      var res = await fetch(params.apiBase + "/agent/preload_status", {
        method: "GET",
        cache: "no-store",
      });
      if (res.status === 404) return { unsupported: true };
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  async function waitForProjectPreload() {
    var startedAt = Date.now();
    var pollCount = 0;
    var triggered = false;
    while (Date.now() - startedAt < 120000) {
      pollCount += 1;
      if (!triggered) {
        triggered = true;
        await triggerBackendPreload(false);
        appendBootLog("进入项目能力初始化阶段");
      }

      var statusData = await getPreloadStatus();
      if (statusData && statusData.unsupported) {
        // 兼容旧版本后端：无预热状态接口时不额外阻塞
        appendBootLog("后端不支持预热状态接口，跳过二阶段等待");
        return true;
      }

      var preload = statusData && statusData.preload ? statusData.preload : null;
      if (preload && preload.done) {
        if (preload.ok) {
          setBootStage("阶段 2/2", "初始化完成", 100);
          appendBootLog("项目初始化完成");
          return true;
        }
        // 失败时再触发一次强制预热，随后继续轮询
        appendBootLog("预热失败，正在尝试强制重试");
        await triggerBackendPreload(true);
      }

      if (preload && preload.message) {
        showBoot("正在初始化项目能力（" + preload.message + "）");
        appendBootLog("预热状态：" + preload.message);
      } else {
        showBoot("正在初始化项目能力（MCP/技能）");
      }
      setBootStage("阶段 2/2", "加载能力", Math.min(96, 52 + pollCount * 2));

      await new Promise(function (resolve) {
        setTimeout(resolve, pollCount < 10 ? 450 : 900);
      });
    }
    return false;
  }


  var baseDesktopConfig = Object.assign({}, params.desktopConfig || {});
  var sessionForOutput = getSession();
  params.desktopConfig = Object.assign({}, baseDesktopConfig);
  var desktopBridge = null;
  var currentSkillsConfig = { skills: {} };
  var selectedSkillNames = [];
  var selectedMcpTools = [];
  var pendingMcpTools = [];
  var currentMcpConfig = [];
  var pendingSkillToggles = new Set();

  var tasksController = null;

  function setSkillsHint(text) {
    if (!skillsSaveHint) return;
    skillsSaveHint.textContent = text || "点击技能即可选择，发送时会自动注入技能提示词。";
  }

  function normalizeSkillNameList(names) {
    var uniq = Object.create(null);
    var out = [];
    (Array.isArray(names) ? names : []).forEach(function (name) {
      var skill = String(name || "").trim();
      if (!skill || uniq[skill]) return;
      uniq[skill] = true;
      out.push(skill);
    });
    return out;
  }

  function collectEnabledSelectedSkills() {
    var source = currentSkillsConfig && currentSkillsConfig.skills ? currentSkillsConfig.skills : {};
    return normalizeSkillNameList(selectedSkillNames).filter(function (name) {
      return !!(source[name] && source[name].enabled);
    });
  }

  function buildSkillsInjectedPrefix() {
    var active = collectEnabledSelectedSkills();
    if (!active.length) return "";
    return "<skills>" + active.join(", ") + "</skills>";
  }

  function mergeSkillsIntoUserInput(userInput) {
    var prefix = buildSkillsInjectedPrefix();
    if (!prefix) return String(userInput || "");
    var text = String(userInput || "");
    return prefix + (text ? "\n\n" + text : "");
  }

  function renderSelectedSkillChips() {
    if (!composerSkillChips) return;
    var source = currentSkillsConfig && currentSkillsConfig.skills ? currentSkillsConfig.skills : {};
    var active = normalizeSkillNameList(selectedSkillNames).filter(function (name) {
      return !!(source[name] && source[name].enabled);
    });
    selectedSkillNames = active;
    composerSkillChips.innerHTML = "";
    if (!active.length) {
      composerSkillChips.classList.add("hidden");
      return;
    }
    composerSkillChips.classList.remove("hidden");
    active.forEach(function (name) {
      var chip = document.createElement("span");
      chip.className = "skill-chip";
      var textNode = document.createElement("span");
      textNode.className = "skill-chip-name";
      textNode.textContent = name;
      var removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "skill-chip-remove";
      removeBtn.setAttribute("aria-label", "移除技能");
      removeBtn.dataset.skillName = name;
      removeBtn.textContent = "×";
      chip.appendChild(textNode);
      chip.appendChild(removeBtn);
      composerSkillChips.appendChild(chip);
    });
  }

  function setSkillToggleBusy(skillName, busy) {
    if (!skillName) return;
    var encoded = encodeURIComponent(skillName);
    var selector = '.skill-toggle[data-skill-name="' + encoded + '"]';
    var nodes = [];
    if (skillsList) {
      var selectNodes = skillsList.querySelectorAll(selector);
      for (var i = 0; i < selectNodes.length; i += 1) nodes.push(selectNodes[i]);
    }
    if (skillsManageList) {
      var manageNodes = skillsManageList.querySelectorAll(selector);
      for (var j = 0; j < manageNodes.length; j += 1) nodes.push(manageNodes[j]);
    }
    for (var n = 0; n < nodes.length; n += 1) {
      nodes[n].disabled = !!busy;
    }
  }

  function setSyncState(node, mode) {
    if (!node) return;
    var textNode = node.querySelector(".sync-text");
    var isServer = mode === "server";
    node.classList.toggle("sync-state-server", isServer);
    node.classList.toggle("sync-state-local", !isServer);
    if (textNode) {
      textNode.textContent = isServer ? "服务端已同步" : "仅本地";
    }
  }

  function renderSkillsList(config) {
    if (!skillsList) return;
    var normalized = normalizeSkillsConfig(config);
    currentSkillsConfig = normalized;
    selectedSkillNames = normalizeSkillNameList(selectedSkillNames).filter(function (name) {
      var entry = normalized.skills[name];
      return !!(entry && entry.enabled);
    });
    var allNames = Object.keys(normalized.skills || {});
    var names = allNames.filter(function (name) {
      return !!(normalized.skills[name] && normalized.skills[name].enabled);
    });
    var query = String((skillsSearchInput && skillsSearchInput.value) || "")
      .trim()
      .toLowerCase();
    var visibleNames = names.filter(function (name) {
      if (!query) return true;
      var item = normalized.skills[name] || {};
      var desc = String(item.description || "");
      var blob = (String(name || "") + " " + desc).toLowerCase();
      return blob.indexOf(query) >= 0;
    });
    if (!allNames.length) {
      skillsList.innerHTML = '<div class="skills-popover-empty">未发现可配置技能。</div>';
      renderSelectedSkillChips();
      return;
    }

    if (!names.length) {
      skillsList.innerHTML =
        '<div class="skills-popover-empty">当前没有已启用的技能。可在「技能管理」中查看各技能状态。</div>';
      renderSelectedSkillChips();
      return;
    }

    if (!visibleNames.length) {
      skillsList.innerHTML = '<div class="skills-popover-empty">无匹配技能。</div>';
      renderSelectedSkillChips();
      return;
    }

    var selected = Object.create(null);
    normalizeSkillNameList(selectedSkillNames).forEach(function (name) {
      selected[name] = true;
    });

    var html = visibleNames
      .map(function (name) {
        var item = normalized.skills[name] || {};
        var desc = String(item.description || "");
        var active = !!selected[name];
        var safeName = escapeHtml(name);
        var safeDesc = escapeHtml(desc || "暂无描述");
        var encodedName = encodeURIComponent(name);
        return (
          '<button type="button" class="skills-select-item' + (active ? " active" : "") + '" data-skill-name="' + encodedName + '">' +
          '<div class="skills-select-item-title">' + safeName + "</div>" +
          '<div class="skills-select-item-desc">' + safeDesc + "</div>" +
          "</button>"
        );
      })
      .join("");
    skillsList.innerHTML = html;
    renderSelectedSkillChips();
  }

  function setSkillsManageHint(text) {
    if (!skillsManageSaveHint) return;
    skillsManageSaveHint.textContent = text || "切换开关将自动保存。";
  }

  /** Qt WebEngine: inline slider/knob sync (same as settings switches). */
  function syncSwitchVisual(input) {
    if (!input) return;
    var label = input.closest(".switch");
    var slider = label && label.querySelector(".slider");
    if (!slider) return;
    var readonly = label && label.classList.contains("switch-readonly");
    var on = !!input.checked;
    slider.style.backgroundColor = on
      ? readonly
        ? "#8dc79a"
        : "#43a047"
      : readonly
        ? "#d6dae0"
        : "#cccccc";
    var knob = slider.querySelector(".slider-knob");
    if (knob) {
      knob.style.transform = on ? "translateX(18px)" : "translateX(0)";
    }
  }

  function syncSkillsManageSwitchVisuals() {
    if (!skillsManageList) return;
    var inputs = skillsManageList.querySelectorAll(".skill-toggle");
    for (var i = 0; i < inputs.length; i += 1) {
      syncSwitchVisual(inputs[i]);
    }
  }

  function renderSkillsManageList(config) {
    if (!skillsManageList) return;
    var normalized = normalizeSkillsConfig(config);
    var allNames = Object.keys(normalized.skills || {});
    var names = allNames.filter(function (name) {
      return !!(normalized.skills[name] && normalized.skills[name].enabled);
    });
    if (!allNames.length) {
      skillsManageList.innerHTML = '<div class="toggle-desc">未发现可配置技能。</div>';
      return;
    }
    if (!names.length) {
      skillsManageList.innerHTML =
        '<div class="toggle-desc">当前没有已启用的技能；已禁用的条目在此不展示。</div>';
      return;
    }
    var html = names
      .map(function (name) {
        var item = normalized.skills[name] || {};
        var desc = String(item.description || "");
        var checked = item.enabled ? "checked" : "";
        var safeName = escapeHtml(name);
        var safeDesc = escapeHtml(desc || "暂无描述");
        var encodedName = encodeURIComponent(name);
        return (
          '<div class="skill-item" data-skill-name="' + encodedName + '">' +
          '<div class="skill-item-head">' +
          '<h3 class="skill-item-name">' + safeName + "</h3>" +
          '<label class="switch switch-readonly">' +
          '<input type="checkbox" class="skill-toggle" data-skill-name="' + encodedName + '" ' + checked + " disabled />" +
          '<span class="slider"><span class="slider-knob" aria-hidden="true"></span></span>' +
          "</label>" +
          "</div>" +
          '<p class="skill-item-desc">' + safeDesc + "</p>" +
          "</div>"
        );
      })
      .join("");
    skillsManageList.innerHTML = html;
    syncSkillsManageSwitchVisuals();
  }

  function buildMcpInjectedPrefix() {
    var active = selectedMcpTools.slice();
    if (!active.length) return "";
    var toolNames = active.map(function (t) { return t.server_name + "." + t.tool_name; });
    return "<mcp-tools>" + toolNames.join(", ") + "</mcp-tools>";
  }

  function mergeMcpToolsIntoUserInput(userInput) {
    var prefix = buildMcpInjectedPrefix();
    if (!prefix) return String(userInput || "");
    var text = String(userInput || "");
    return prefix + (text ? "\n\n" + text : "");
  }

  function renderSelectedMcpChips() {
    if (!composerMcpChips) return;
    composerMcpChips.innerHTML = "";
    var tools = selectedMcpTools.slice();
    if (!tools.length) {
      composerMcpChips.classList.add("hidden");
      return;
    }
    composerMcpChips.classList.remove("hidden");
    tools.forEach(function (tool) {
      var chip = document.createElement("span");
      chip.className = "mcp-chip";
      var textNode = document.createElement("span");
      textNode.className = "mcp-chip-name";
      textNode.textContent = tool.server_name + "." + tool.tool_name;
      var removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "mcp-chip-remove";
      removeBtn.setAttribute("aria-label", "移除MCP工具");
      removeBtn.dataset.serverName = tool.server_name;
      removeBtn.dataset.toolName = tool.tool_name;
      removeBtn.textContent = "×";
      chip.appendChild(textNode);
      chip.appendChild(removeBtn);
      composerMcpChips.appendChild(chip);
    });
  }

  async function loadMcpToolsConfig() {
    try {
      var res = await fetch(params.apiBase + "/api/desktop/mcp_servers_config", {
        method: "GET",
        cache: "no-store",
      });
      if (!res.ok) {
        if (mcpToolStatusHint) mcpToolStatusHint.textContent = "加载MCP配置失败";
        return null;
      }
      var data = await res.json();
      if (!data || !data.ok || !Array.isArray(data.config)) {
        if (mcpToolStatusHint) mcpToolStatusHint.textContent = "未发现MCP服务配置";
        return null;
      }
      currentMcpConfig = data.config;
      return data.config;
    } catch (e) {
      if (mcpToolStatusHint) mcpToolStatusHint.textContent = "加载失败: " + (e.message || e);
      return null;
    }
  }

  function extractFirstSentence(text) {
    if (!text) return "";
    var cleaned = text.replace(/\n/g, " ").replace(/\s+/g, " ").trim();
    var match = cleaned.match(/^[^。！？\.!\?]+[。！？\.!\?]?/);
    return match ? match[0].trim() : cleaned.substring(0, 60).trim();
  }

  function renderMcpToolSelection(servers, searchText) {
    if (!mcpToolList) return;
    var filterText = (searchText || "").trim().toLowerCase();
    if (!Array.isArray(servers) || !servers.length) {
      mcpToolList.innerHTML = '<div class="mcp-tool-popover-empty">未发现可用的MCP工具。</div>';
      return;
    }

    var selectedMap = Object.create(null);
    pendingMcpTools.forEach(function (t) {
      selectedMap[t.server_name + "::" + t.tool_name] = true;
    });

    var html = "";

    for (var i = 0; i < servers.length; i++) {
      var server = servers[i];
      var srvName = String(server.server_name || "未命名服务");
      var srvDesc = extractFirstSentence(String(server.server_description || "").trim());
      var srvLoad = !!server.is_load;
      var tools = Array.isArray(server.tools) ? server.tools : [];

      var visibleTools = [];
      for (var j = 0; j < tools.length; j++) {
        var tool = tools[j];
        var tName = String(tool.tool_name || "");
        var tDesc = String(tool.tool_description || "").trim();
        if (filterText) {
          var haystack = (srvName + " " + tName + " " + tDesc).toLowerCase();
          if (haystack.indexOf(filterText) < 0) continue;
        }
        visibleTools.push(tool);
      }
      if (!visibleTools.length) continue;

      var safeSrvName = srvName.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      var safeSrvDesc = srvDesc
        ? srvDesc.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        : "";
      var selectedInServer = 0;
      for (var sc = 0; sc < visibleTools.length; sc++) {
        if (selectedMap[srvName + "::" + visibleTools[sc].tool_name]) selectedInServer++;
      }

      var isExpanded = !!filterText || selectedInServer > 0;

      html += '<div class="mcp-srv-group">' +
        '<div class="mcp-srv-header" data-server-idx="' + i + '">' +
        '<span class="mcp-srv-arrow" data-server-idx="' + i + '">' + (isExpanded ? "▾" : "▸") + '</span>' +
        '<div class="mcp-srv-info">' +
        '<span class="mcp-srv-name">' + safeSrvName + '</span>' +
        (safeSrvDesc ? '<span class="mcp-srv-desc">' + safeSrvDesc + '</span>' : '') +
        '</div>' +
        '<span class="mcp-srv-count">' + visibleTools.length + ' 工具</span>' +
        '<span class="mcp-srv-badge ' + (srvLoad ? "on" : "off") + '">' +
        (srvLoad ? "启用" : "停用") + '</span>' +
        '</div>' +
        '<div class="mcp-srv-tools' + (isExpanded ? "" : " hidden") + '" id="mcp-srv-tools-' + i + '">';

      for (var k = 0; k < visibleTools.length; k++) {
        var vTool = visibleTools[k];
        var vTName = String(vTool.tool_name || "");
        var vTDesc = extractFirstSentence(String(vTool.tool_description || "").trim());
        var safeTName = vTName.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        var safeTDesc = vTDesc
          ? vTDesc.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
          : "";
        var isSelected = !!selectedMap[srvName + "::" + vTName];

        html += '<div class="mcp-pick-item' + (isSelected ? " selected" : "") + '" data-server-name="' +
          srvName.replace(/"/g, "&quot;") + '" data-tool-name="' +
          vTName.replace(/"/g, "&quot;") + '">' +
          '<span class="mcp-pick-check">' + (isSelected ? "☑" : "☐") + '</span>' +
          '<div class="mcp-pick-info">' +
          '<span class="mcp-pick-name">' + safeTName + '</span>' +
          (safeTDesc ? '<span class="mcp-pick-desc">' + safeTDesc + '</span>' : '') +
          '</div>' +
          '</div>';
      }

      html += '</div></div>';
    }

    if (!html) {
      mcpToolList.innerHTML = '<div class="mcp-tool-popover-empty">没有匹配的MCP工具。</div>';
    } else {
      mcpToolList.innerHTML = html;
    }

    updateMcpToolStatusHint();
  }

  function updateMcpToolStatusHint() {
    if (!mcpToolStatusHint) return;
    var count = pendingMcpTools.length;
    if (count) {
      mcpToolStatusHint.textContent = "已选择 " + count + " 个MCP工具";
    } else {
      mcpToolStatusHint.textContent = "请选择需要使用的MCP工具";
    }
  }

  async function loadSkillsConfigFromBridge() {
    // config/skills_config.json 仅由管理端 WebSocket 合并写入；本地 skills/ 不反向写入该文件。
    var localRes = await getBridgeSkillsConfig(desktopBridge);
    if (!localRes || !localRes.ok) {
      setSyncState(skillsSyncState, "local");
      setSyncState(skillsManageSyncState, "local");
      setSkillsHint("加载失败：无法读取本地 config/skills_config.json");
      setSkillsManageHint("加载失败：无法读取本地 config/skills_config.json");
      return false;
    }
    var merged = normalizeSkillsConfig(localRes.config || {});
    renderSkillsList(merged);
    var adminOnline =
      typeof auth !== "undefined" &&
      auth &&
      typeof auth.isAdminOnlineConnected === "function" &&
      auth.isAdminOnlineConnected();
    var syncMode = adminOnline ? "server" : "local";
    setSyncState(skillsSyncState, syncMode);
    setSyncState(skillsManageSyncState, syncMode);
    if (adminOnline) {
      setSkillsHint("已加载技能配置（已连接管理端）。");
      setSkillsManageHint("已加载技能配置（已连接管理端）。");
    } else {
      setSkillsHint("已加载本地技能配置（登录后将尝试与管理端同步）。");
      setSkillsManageHint("已加载本地技能配置（登录后将尝试与管理端同步）。");
    }
    return true;
  }

  async function saveSkillsConfigToBridge(nextConfig, prevConfig, changedSkillName, changedEnabled) {
    // 当前版本仅保存本地配置文件。未来接入云端同步时，再补充远端写入流程。
    var localRes = await saveBridgeSkillsConfig(desktopBridge, nextConfig);
    if (!localRes || !localRes.ok) {
      setSyncState(skillsSyncState, "local");
      setSyncState(skillsManageSyncState, "local");
      setSkillsHint("本地文件保存失败。");
      setSkillsManageHint("本地文件保存失败。");
      return false;
    }
    currentSkillsConfig = normalizeSkillsConfig(localRes.config || {});
    var adminOnline =
      typeof auth !== "undefined" &&
      auth &&
      typeof auth.isAdminOnlineConnected === "function" &&
      auth.isAdminOnlineConnected();
    var syncMode = adminOnline ? "server" : "local";
    setSyncState(skillsSyncState, syncMode);
    setSyncState(skillsManageSyncState, syncMode);
    setSkillsHint("已保存本地配置（config/skills_config.json）");
    setSkillsManageHint("已保存本地配置（config/skills_config.json）");
    return true;
  }

  /** Anchor skills popover to the composer「技能」button using its real laid-out height. */
  function positionSkillsPopover() {
    if (!btnSkills || !skillsModal) return;
    var rect = btnSkills.getBoundingClientRect();
    var width = Math.min(420, Math.floor(window.innerWidth * 0.92));
    var left = rect.left;
    if (left + width > window.innerWidth - 10) {
      left = window.innerWidth - width - 10;
    }
    if (left < 10) left = 10;

    var gap = 8;
    var pad = 10;
    var maxPopoverH = Math.min(540, Math.floor(window.innerHeight * 0.62));
    var rawH = skillsModal.offsetHeight;
    if (!rawH || rawH < 24) {
      rawH = skillsModal.getBoundingClientRect().height;
    }
    if (!rawH || rawH < 24) {
      rawH = Math.min(maxPopoverH, skillsModal.scrollHeight || maxPopoverH);
    }
    var popH = Math.min(maxPopoverH, Math.ceil(rawH));

    var top = rect.top - popH - gap;
    if (top < pad) {
      top = rect.bottom + gap;
    }
    if (top + popH > window.innerHeight - pad) {
      top = Math.max(pad, window.innerHeight - pad - popH);
    }
    if (top < pad) {
      top = pad;
    }

    skillsModal.style.left = Math.round(left) + "px";
    skillsModal.style.top = Math.round(top) + "px";
  }

  function schedulePositionSkillsPopover() {
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        positionSkillsPopover();
      });
    });
  }

  function bindSettingsNav() {
    var navEl = document.getElementById("settings-nav");
    if (!navEl) return;

    navEl.addEventListener("click", function (e) {
      var item = e.target.closest(".settings-nav-item");
      if (!item) return;
      var panelName = item.getAttribute("data-panel");
      if (!panelName) return;

      var allNavItems = navEl.querySelectorAll(".settings-nav-item");
      for (var i = 0; i < allNavItems.length; i++) {
        allNavItems[i].classList.remove("active");
        allNavItems[i].setAttribute("aria-selected", "false");
      }
      item.classList.add("active");
      item.setAttribute("aria-selected", "true");

      var allPanels = document.querySelectorAll(".settings-panel");
      for (var j = 0; j < allPanels.length; j++) {
        allPanels[j].classList.add("hidden");
      }
      var targetPanel = document.getElementById("panel-" + panelName);
      if (targetPanel) {
        targetPanel.classList.remove("hidden");
      }
      /* 按需加载对应面板的后端数据 */
      if (settings && settings.switchSettingsPanel) {
        settings.switchSettingsPanel(panelName);
      }
    });
  }

  function bindWechatConfigSave() {
    var wechatSaveBtn = document.getElementById("cfg-wechat-save");
    var wechatResetBtn = document.getElementById("cfg-wechat-reset");
    var wechatHintEl = null;

    function showWechatHint(text) {
      if (!wechatSaveBtn) return;
      if (!wechatHintEl) {
        wechatHintEl = document.createElement("span");
        wechatHintEl.className = "cfg-save-inline-hint";
        wechatSaveBtn.parentNode.appendChild(wechatHintEl);
      }
      wechatHintEl.textContent = text;
      clearTimeout(wechatHintEl._timer);
      wechatHintEl._timer = setTimeout(function () {
        wechatHintEl.textContent = "";
      }, 3500);
    }

    if (wechatSaveBtn) {
      wechatSaveBtn.addEventListener("click", async function () {
        var normalizedOutputBaseDir = cfgOutputBaseDir
          ? normalizePathSlashes(cfgOutputBaseDir.value)
          : "";
        var baseCfg = pickConfigFields(params.desktopConfig);
        var payload = Object.assign({}, baseCfg, {
          output_base_dir: normalizedOutputBaseDir,
          wechat_window_title: cfgWechatWindowTitle ? cfgWechatWindowTitle.value.trim() : baseCfg.wechat_window_title || "",
          wechat_process_name: cfgWechatProcessName ? cfgWechatProcessName.value.trim() : baseCfg.wechat_process_name || "",
          wechat_ai_reply_prefix: cfgWechatAiReplyPrefix ? cfgWechatAiReplyPrefix.value.trim() : baseCfg.wechat_ai_reply_prefix || "",
          /* 微信附件与缓存 */
          wechat_attachment_save_dir: cfgWechatAttachmentSaveDir ? cfgWechatAttachmentSaveDir.value.trim() : baseCfg.wechat_attachment_save_dir || "",
          wechat_attachment_cache_file: cfgWechatAttachmentCacheFile ? cfgWechatAttachmentCacheFile.value.trim() : baseCfg.wechat_attachment_cache_file || "",
          wechat_audio_cache_file: cfgWechatAudioCacheFile ? cfgWechatAudioCacheFile.value.trim() : baseCfg.wechat_audio_cache_file || "",
        });
        if (!desktopBridge) {
          showWechatHint("保存失败，桌面桥接不可用");
          return;
        }
        var result = await saveBridgeConfig(desktopBridge, payload);
        var ok = result && result.ok && result.config;
        if (ok) {
          params.desktopConfig = Object.assign({}, result.config);
          renderDefaultOutputPath(params, sessionForOutput);
          if (cfgOutputBaseDir) cfgOutputBaseDir.value = normalizedOutputBaseDir;
        }
        showWechatHint(ok ? "已保存并生效" : "保存失败");
      });
    }

    if (wechatResetBtn) {
      wechatResetBtn.addEventListener("click", async function () {
        if (!desktopBridge) return;
        var result = await resetBridgeConfig(desktopBridge);
        if (!result || !result.ok || !result.config) return;
        params.desktopConfig = Object.assign({}, result.config);
        renderDefaultOutputPath(params, sessionForOutput);
        if (settings && settings.syncConfigToForm) settings.syncConfigToForm();
        showWechatHint("已恢复默认");
      });
    }
  }

  function bindSkillsPanel() {
    if (!btnSkills || !skillsModal || !skillsClose || !skillsList) return;

    function hideSkillsPopover() {
      skillsModal.classList.add("hidden");
      skillsModal.setAttribute("aria-hidden", "true");
    }

    btnSkills.addEventListener("click", async function (e) {
      e.stopPropagation();
      var isHidden = skillsModal.classList.contains("hidden");
      if (!isHidden) {
        hideSkillsPopover();
        return;
      }
      skillsModal.classList.remove("hidden");
      skillsModal.setAttribute("aria-hidden", "false");
      // Always reload: first paint leaves children in skillsList; skipping load would stale-cache forever.
      await loadSkillsConfigFromBridge();
      if (skillsSearchInput) {
        skillsSearchInput.value = "";
        renderSkillsList(currentSkillsConfig);
        skillsSearchInput.focus();
      }
      schedulePositionSkillsPopover();
    });

    skillsClose.addEventListener("click", function () {
      hideSkillsPopover();
    });

    window.addEventListener("resize", function () {
      if (!skillsModal.classList.contains("hidden")) {
        positionSkillsPopover();
      }
    });

    document.addEventListener("click", function (e) {
      if (skillsModal.classList.contains("hidden")) return;
      var target = e.target;
      if (target === btnSkills || (btnSkills.contains && btnSkills.contains(target))) return;
      if (skillsModal.contains(target)) return;
      hideSkillsPopover();
    });

    document.addEventListener(
      "keydown",
      function (e) {
        if (e.key === "Escape" && !skillsModal.classList.contains("hidden")) {
          e.preventDefault();
          e.stopPropagation();
          hideSkillsPopover();
        }
      },
      true
    );

    if (skillsSearchInput) {
      skillsSearchInput.addEventListener("input", function () {
        renderSkillsList(currentSkillsConfig);
        if (!skillsModal.classList.contains("hidden")) {
          schedulePositionSkillsPopover();
        }
      });
    }

    skillsList.addEventListener("click", function (e) {
      var node = e.target && e.target.closest ? e.target.closest(".skills-select-item") : null;
      if (!node) return;
      var encoded = node.getAttribute("data-skill-name") || "";
      var name = decodeURIComponent(encoded);
      var exists = selectedSkillNames.indexOf(name) >= 0;
      if (exists) {
        selectedSkillNames = selectedSkillNames.filter(function (n) {
          return n !== name;
        });
      } else {
        selectedSkillNames = normalizeSkillNameList(selectedSkillNames.concat([name]));
      }
      renderSkillsList(currentSkillsConfig);
      schedulePositionSkillsPopover();
    });

    if (composerSkillChips) {
      composerSkillChips.addEventListener("click", function (e) {
        var btn = e.target && e.target.closest ? e.target.closest(".skill-chip-remove") : null;
        if (!btn) return;
        var name = String(btn.dataset.skillName || "");
        selectedSkillNames = selectedSkillNames.filter(function (n) {
          return n !== name;
        });
        renderSelectedSkillChips();
        renderSkillsList(currentSkillsConfig);
        if (!skillsModal.classList.contains("hidden")) {
          schedulePositionSkillsPopover();
        }
      });
    }

    if (skillsManageLink) {
      skillsManageLink.addEventListener("click", async function () {
        hideSkillsPopover();
        if (skillsManageModal) {
          skillsManageModal.classList.remove("hidden");
          skillsManageModal.setAttribute("aria-hidden", "false");
        }
        await loadSkillsConfigFromBridge();
        renderSkillsManageList(currentSkillsConfig);
        setSkillsManageHint("在此切换技能开关，变更会实时生效。");
      });
    }
  }

  function bindSkillsManagePanel() {
    if (!skillsManageModal || !skillsManageClose || !skillsManageList) return;

    async function showSkillsSelectorAfterManageClose() {
      if (!skillsModal || !btnSkills) return;
      skillsModal.classList.remove("hidden");
      skillsModal.setAttribute("aria-hidden", "false");
      await loadSkillsConfigFromBridge();
      if (skillsSearchInput) {
        skillsSearchInput.value = "";
        renderSkillsList(currentSkillsConfig);
        skillsSearchInput.focus();
      }
      schedulePositionSkillsPopover();
      setSkillsHint("已返回技能选择列表。");
    }

    function hideSkillsManageModal() {
      skillsManageModal.classList.add("hidden");
      skillsManageModal.setAttribute("aria-hidden", "true");
      void showSkillsSelectorAfterManageClose();
    }

    skillsManageClose.addEventListener("click", function () {
      hideSkillsManageModal();
    });

    skillsManageModal.addEventListener("click", function (e) {
      if (e.target === skillsManageModal) {
        hideSkillsManageModal();
      }
    });

    document.addEventListener(
      "keydown",
      function (e) {
        if (
          e.key === "Escape" &&
          skillsManageModal &&
          !skillsManageModal.classList.contains("hidden")
        ) {
          e.preventDefault();
          e.stopPropagation();
          hideSkillsManageModal();
        }
      },
      true
    );

    // 技能管理页改为只读：禁止切换
    skillsManageList.addEventListener("click", function (e) {
      var node = e.target;
      if (node && node.closest && node.closest(".switch")) {
        setSkillsManageHint("当前仅支持查看技能状态，不能在此更改开关。");
      }
      e.preventDefault();
    });
  }

  function bindMcpPanel() {
    if (!btnMcp || !mcpModal || !mcpClose || !mcpToolList) return;

    function hideMcpPopover() {
      mcpModal.classList.add("hidden");
      mcpModal.setAttribute("aria-hidden", "true");
    }

    btnMcp.addEventListener("click", async function (e) {
      e.stopPropagation();
      var isHidden = mcpModal.classList.contains("hidden");
      if (!isHidden) {
        hideMcpPopover();
        return;
      }
      pendingMcpTools = selectedMcpTools.slice();
      mcpModal.classList.remove("hidden");
      mcpModal.setAttribute("aria-hidden", "false");
      var servers = await loadMcpToolsConfig();
      if (servers) {
        if (mcpToolSearchInput) mcpToolSearchInput.value = "";
        renderMcpToolSelection(servers, "");
        if (mcpToolSearchInput) mcpToolSearchInput.focus();
        centerMcpPopover();
      }
    });

    mcpClose.addEventListener("click", function () {
      pendingMcpTools = selectedMcpTools.slice();
      hideMcpPopover();
    });

    // 窗口大小变化时重新居中
    window.addEventListener("resize", function () {
      if (!mcpModal.classList.contains("hidden")) {
        centerMcpPopover();
      }
    });

    // 点击蒙层外关闭（恢复原选中状态）
    document.addEventListener("click", function (e) {
      if (mcpModal.classList.contains("hidden")) return;
      var target = e.target;
      if (target === btnMcp || (btnMcp.contains && btnMcp.contains(target))) return;
      if (mcpModal.contains(target)) return;
      if (!document.body.contains(target)) return;
      pendingMcpTools = selectedMcpTools.slice();
      hideMcpPopover();
    });

    // ESC 关闭（恢复原选中状态）
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !mcpModal.classList.contains("hidden")) {
        e.preventDefault();
        e.stopPropagation();
        pendingMcpTools = selectedMcpTools.slice();
        hideMcpPopover();
      }
    });

    // 搜索过滤
    if (mcpToolSearchInput) {
      mcpToolSearchInput.addEventListener("input", function () {
        var servers = currentMcpConfig;
        if (Array.isArray(servers) && servers.length) {
          renderMcpToolSelection(servers, mcpToolSearchInput.value);
        }
      });
    }

    // 服务展开/折叠 + 工具选择
    if (mcpToolList) {
      mcpToolList.addEventListener("click", function (e) {
        var node = e.target;
        var arrowEl = node.closest ? node.closest(".mcp-srv-arrow") : null;
        var headerEl = node.closest ? node.closest(".mcp-srv-header") : null;
        if (arrowEl || headerEl) {
          var idx = (arrowEl || headerEl).getAttribute("data-server-idx");
          if (idx != null) {
            var toolsEl = document.getElementById("mcp-srv-tools-" + idx);
            if (toolsEl) {
              var isHidden = toolsEl.classList.contains("hidden");
              toolsEl.classList.toggle("hidden", !isHidden);
              var arrows = document.querySelectorAll('.mcp-srv-arrow[data-server-idx="' + idx + '"]');
              for (var ei = 0; ei < arrows.length; ei++) {
                arrows[ei].textContent = isHidden ? "▾" : "▸";
              }
            }
          }
          return;
        }
        var toolItem = node.closest ? node.closest(".mcp-pick-item") : null;
        if (!toolItem) return;
        var srvName = toolItem.getAttribute("data-server-name");
        var toolName = toolItem.getAttribute("data-tool-name");
        if (!srvName || !toolName) return;
        toggleMcpToolSelection(srvName, toolName);
      });
    }

    // 确认按钮：提交临时选中状态并渲染 chips
    if (mcpToolConfirmBtn) {
      mcpToolConfirmBtn.addEventListener("click", function () {
        selectedMcpTools = pendingMcpTools.slice();
        hideMcpPopover();
        renderSelectedMcpChips();
      });
    }

    // 取消按钮：丢弃临时状态，恢复原选中
    if (mcpToolCancelBtn) {
      mcpToolCancelBtn.addEventListener("click", function () {
        pendingMcpTools = selectedMcpTools.slice();
        hideMcpPopover();
      });
    }

    // MCP chip 移除（弹窗外操作，直接修改 selectedMcpTools）
    if (composerMcpChips) {
      composerMcpChips.addEventListener("click", function (e) {
        var btn = e.target && e.target.closest ? e.target.closest(".mcp-chip-remove") : null;
        if (!btn) return;
        var srvName = String(btn.dataset.serverName || "");
        var toolName = String(btn.dataset.toolName || "");
        selectedMcpTools = selectedMcpTools.filter(function (t) {
          return !(t.server_name === srvName && t.tool_name === toolName);
        });
        pendingMcpTools = selectedMcpTools.slice();
        renderSelectedMcpChips();
        if (!mcpModal.classList.contains("hidden")) {
          var servers = currentMcpConfig;
          if (Array.isArray(servers) && servers.length) {
            renderMcpToolSelection(servers, mcpToolSearchInput ? mcpToolSearchInput.value : "");
          }
        }
      });
    }
  }

  function toggleMcpToolSelection(serverName, toolName) {
    if (!serverName || !toolName) return;
    var idx = -1;
    for (var i = 0; i < pendingMcpTools.length; i++) {
      if (pendingMcpTools[i].server_name === serverName && pendingMcpTools[i].tool_name === toolName) {
        idx = i;
        break;
      }
    }
    if (idx >= 0) {
      pendingMcpTools.splice(idx, 1);
    } else {
      pendingMcpTools.push({ server_name: serverName, tool_name: toolName });
    }
    var servers = currentMcpConfig;
    if (Array.isArray(servers) && servers.length) {
      renderMcpToolSelection(servers, mcpToolSearchInput ? mcpToolSearchInput.value : "");
    }
    updateMcpToolStatusHint();
  }

  function centerMcpPopover() {
    if (!mcpModal || !mcpToolList) return;
    var header = mcpModal.querySelector(".mcp-tool-popover-header");
    var searchWrap = mcpModal.querySelector(".mcp-tool-popover-search-wrap");
    var footer = mcpModal.querySelector(".mcp-tool-popover-footer");
    var modalH = mcpModal.getBoundingClientRect().height;
    var usedH = (header ? header.getBoundingClientRect().height : 0) +
                (searchWrap ? searchWrap.getBoundingClientRect().height : 0) +
                (footer ? footer.getBoundingClientRect().height : 0);
    var listH = Math.max(100, Math.floor(modalH - usedH));
    mcpToolList.style.height = listH + "px";
  }

  function setMainView(which) {
    var chatEl = document.getElementById("view-chat");
    var tasksEl = document.getElementById("view-tasks");
    var collabEl = document.getElementById("view-collab");
    var knowledgeEl = document.getElementById("view-knowledge");
    var navChat = document.getElementById("nav-view-chat");
    var navTasks = document.getElementById("nav-view-tasks");
    var navKnowledge = document.getElementById("nav-view-knowledge");
    var title = document.getElementById("top-bar-title");

    function hideAllMainViews() {
      if (chatEl) {
        chatEl.classList.add("hidden");
        chatEl.setAttribute("aria-hidden", "true");
      }
      if (tasksEl) {
        tasksEl.classList.add("hidden");
        tasksEl.setAttribute("aria-hidden", "true");
      }
      if (collabEl) {
        collabEl.classList.add("hidden");
        collabEl.setAttribute("aria-hidden", "true");
      }
      if (knowledgeEl) {
        knowledgeEl.classList.add("hidden");
        knowledgeEl.setAttribute("aria-hidden", "true");
      }
      if (navChat) {
        navChat.classList.remove("active");
        navChat.setAttribute("aria-selected", "false");
      }
      if (navTasks) {
        navTasks.classList.remove("active");
        navTasks.setAttribute("aria-selected", "false");
      }
      if (navKnowledge) {
        navKnowledge.classList.remove("active");
        navKnowledge.setAttribute("aria-selected", "false");
      }
    }

    if (which === "tasks") {
      hideAllMainViews();
      if (tasksEl) {
        tasksEl.classList.remove("hidden");
        tasksEl.setAttribute("aria-hidden", "false");
      }
      if (navTasks) {
        navTasks.classList.add("active");
        navTasks.setAttribute("aria-selected", "true");
      }
      if (title) title.textContent = "定时任务";
      if (tasksController) tasksController.refresh();
      return;
    }

    if (which === "collab") {
      hideAllMainViews();
      if (collabEl) {
        collabEl.classList.remove("hidden");
        collabEl.setAttribute("aria-hidden", "false");
      }
      if (navChat) {
        navChat.classList.add("active");
        navChat.setAttribute("aria-selected", "true");
      }
      if (title) title.textContent = "协同空间";
      return;
    }

    if (which === "knowledge") {
      hideAllMainViews();
      if (knowledgeEl) {
        knowledgeEl.classList.remove("hidden");
        knowledgeEl.setAttribute("aria-hidden", "false");
      }
      if (navKnowledge) {
        navKnowledge.classList.add("active");
        navKnowledge.setAttribute("aria-selected", "true");
      }
      if (title) title.textContent = "知识库";
      return;
    }

    hideAllMainViews();
    if (chatEl) {
      chatEl.classList.remove("hidden");
      chatEl.setAttribute("aria-hidden", "false");
    }
    if (navChat) {
      navChat.classList.add("active");
      navChat.setAttribute("aria-selected", "true");
    }
    if (title) title.textContent = "对话";
  }

  function setTopBarTitle(text) {
    var title = document.getElementById("top-bar-title");
    if (title) title.textContent = text || "协同空间";
  }

  var collabController = createCollabController({
    adminApiBase: params.adminApiBase,
    getDesktopBridge: function () {
      return desktopBridge;
    },
    getWorkspaceRoot: function () {
      return params.desktopConfig ? params.desktopConfig.workspace_root : "";
    },
    listEl: document.getElementById("collab-chain-list"),
    detailRootEl: document.getElementById("collab-detail-root"),
    sectionToggleEl: document.getElementById("collab-section-toggle"),
    sectionUnreadBadgeEl: document.getElementById("collab-section-unread-badge"),
    setMainView: setMainView,
    setTopBarTitle: setTopBarTitle,
    startConversationWithMessage: function (text, opts) {
      return chat.startConversationWithMessage(text, opts);
    },
  });
  collabController.startPoll();
  collabController.bindCollabBatchIcon();

  var chat = createChatController({
    apiBase: params.apiBase,
    conversationListEl: conversationListEl,
    schedulerConversationListEl: schedulerConversationListEl,
    messagesEl: messagesEl,
    confirmOverlay: confirmOverlay,
    confirmTitleEl: confirmTitleEl,
    confirmDescEl: confirmDescEl,
    confirmBtnOk: confirmBtnOk,
    confirmBtnCancel: confirmBtnCancel,
    workspaceRoot: params.desktopConfig ? params.desktopConfig.workspace_root : "",
    getDesktopBridge: function () {
      return desktopBridge;
    },
    onSidebarConversationOpen: function () {
      setMainView("chat");
    },
    buildUserInputBeforeSend: function (text) {
      var injected = mergeSkillsIntoUserInput(text);
      injected = mergeMcpToolsIntoUserInput(injected);
      // 一次发送后清空已选技能和MCP工具，避免后续消息误复用
      if (buildSkillsInjectedPrefix()) {
        selectedSkillNames = [];
        renderSelectedSkillChips();
        renderSkillsList(currentSkillsConfig);
      }
      if (buildMcpInjectedPrefix()) {
        selectedMcpTools = [];
        renderSelectedMcpChips();
      }
      return injected;
    },
    onAssistantStreamDone: function (conv, finalContent) {
      return collabController.tryFinalizeLastStepFromAgent(conv, finalContent);
    },
    augmentUserInputBeforeSend: function (text, messages) {
      return collabController.augmentCollabUserInputForSend(text, messages);
    },
  });

  tasksController = createTasksController({
    apiBase: params.apiBase,
    tasksRootEl: document.getElementById("tasks-root"),
    getUsername: function () {
      var sess = getSession();
      return sess && sess.user && sess.user.username ? sess.user.username : "";
    },
    switchToChat: function () {
      setMainView("chat");
    },
    startConversationWithMessage: function (text, opts) {
      return chat.startConversationWithMessage(text, opts);
    },
  });

  var knowledgeController = createKnowledgeController({
    apiBase: params.apiBase,
    knowledgeRootEl: document.getElementById("knowledge-root"),
  });

  var contactsController = createContactsController({
    contactsTree: document.getElementById("contacts-tree"),
    searchInput: document.getElementById("contacts-search"),
    searchClear: document.getElementById("contacts-search-clear"),
    toggleBtn: document.getElementById("btn-toggle-right-panel"),
    rightPanel: document.getElementById("right-panel"),
    apiBase: params.apiBase,
    adminApiBase: params.adminApiBase,
    getToken: function () {
      var s = getSession();
      return s && s.token ? s.token : "";
    },
  });

  // 注册联系人右键菜单"共享知识库"回调：切换到知识库页面并进入分享模式
  contactsController.onAction("share-knowledge", function (userId, userName) {
    setMainView("knowledge");
    if (knowledgeController && knowledgeController.enterShareMode) {
      knowledgeController.enterShareMode(userName);
    }
  });

  var navChatBtn = document.getElementById("nav-view-chat");
  var navTasksBtn = document.getElementById("nav-view-tasks");
  if (navChatBtn) {
    navChatBtn.addEventListener("click", function () {
      setMainView("chat");
    });
  }
  if (navTasksBtn) {
    navTasksBtn.addEventListener("click", function () {
      setMainView("tasks");
    });
  }

  var navKnowledgeBtn = document.getElementById("nav-view-knowledge");
  if (navKnowledgeBtn) {
    navKnowledgeBtn.addEventListener("click", function () {
      setMainView("knowledge");
    });
  }

  var settings = createSettingsController({
    settingsModal: settingsModal,
    btnSettings: btnSettings,
    settingsClose: settingsClose,
    prefSecurity: prefSecurity,
    prefSleep: prefSleep,
    prefTools: prefTools,
    cfgWorkspaceRoot: null,
    cfgOutputTemplate: null,
    cfgOutputBaseDir: cfgOutputBaseDir,
    cfgWechatWindowTitle: cfgWechatWindowTitle,
    cfgWechatProcessName: cfgWechatProcessName,
    cfgWechatAiReplyPrefix: cfgWechatAiReplyPrefix,
    cfgAutoCreateRoot: cfgAutoCreateRoot,
    cfgSaveLocal: cfgSaveLocal,
    cfgResetDefault: cfgResetDefault,
    cfgSaveHint: cfgSaveHint,
    /* 允许访问路径 */
    mcpReadDirsList: mcpReadDirsList,
    cfgAddDirBtn: cfgAddDirBtn,
    /* 通用设置 - 模型与模板 */
    cfgImageProvider: cfgImageProvider,
    cfgLlmProvider: cfgLlmProvider,
    cfgTemplateDir: cfgTemplateDir,
    cfgImageTemplateDir: cfgImageTemplateDir,
    /* 通用设置 - 记忆与压缩 */
    cfgMemoryCompressEnabled: cfgMemoryCompressEnabled,
    cfgMemoryCompressThreshold: cfgMemoryCompressThreshold,
    cfgMemoryEnableTopicSearch: cfgMemoryEnableTopicSearch,
    cfgMemorySearchCandidateLimit: cfgMemorySearchCandidateLimit,
    cfgMemoryShortTermTasks: cfgMemoryShortTermTasks,
    cfgMemoryMidTermTasks: cfgMemoryMidTermTasks,
    cfgMemoryRelevantTasksLimit: cfgMemoryRelevantTasksLimit,
    /* 通用设置 - 沙箱与子代理 */
    cfgUseSandbox: cfgUseSandbox,
    cfgEnableSubagents: cfgEnableSubagents,
    /* 微信设置 - 附件与缓存 */
    cfgWechatAttachmentSaveDir: cfgWechatAttachmentSaveDir,
    cfgWechatAttachmentCacheFile: cfgWechatAttachmentCacheFile,
    cfgWechatAudioCacheFile: cfgWechatAudioCacheFile,
    mcpHealthSummary: mcpHealthSummary,
    mcpHealthMissing: mcpHealthMissing,
    mcpHealthServers: mcpHealthServers,
    mcpHealthRefresh: mcpHealthRefresh,
    fetchMcpHealth: fetchMcpRuntimeCheck,
    onMcpHealthStateChange: function (state) {
      applyDesktopMcpHealthToBadge(state);
    },
    getConfigForForm: function () {
      return pickConfigFields(params.desktopConfig);
    },
    saveConfigFromForm: async function (formData) {
      var payload = Object.assign({}, pickConfigFields(params.desktopConfig), {
        output_base_dir: formData.output_base_dir || "",
        output_dir_template: "{output_base_dir}/{username}",
        wechat_window_title: formData.wechat_window_title || "",
        wechat_process_name: formData.wechat_process_name || "",
        wechat_ai_reply_prefix: formData.wechat_ai_reply_prefix || "",
        auto_create_workspace_root:
          typeof formData.auto_create_workspace_root === "boolean"
            ? formData.auto_create_workspace_root
            : true,
        /* 通用设置 - 模型与模板 */
        image_provider: formData.image_provider || "",
        llm_provider: formData.llm_provider || "",
        template_dir: formData.template_dir || "",
        image_template_dir: formData.image_template_dir || "",
        /* 通用设置 - 布尔型 */
        memory_compress_enabled: !!formData.memory_compress_enabled,
        memory_enable_topic_search: !!formData.memory_enable_topic_search,
        use_sandbox: !!formData.use_sandbox,
        enable_subagents: !!formData.enable_subagents,
        /* 通用设置 - 数值型 */
        memory_compress_threshold: formData.memory_compress_threshold || 3000,
        memory_short_term_tasks: formData.memory_short_term_tasks || 5,
        memory_mid_term_tasks: formData.memory_mid_term_tasks || 25,
        memory_relevant_tasks_limit: formData.memory_relevant_tasks_limit || 2,
        memory_search_candidate_limit: formData.memory_search_candidate_limit || 50,
        /* 微信设置 - 附件与缓存 */
        wechat_attachment_save_dir: formData.wechat_attachment_save_dir || "",
        wechat_attachment_cache_file: formData.wechat_attachment_cache_file || "",
        wechat_audio_cache_file: formData.wechat_audio_cache_file || "",
      });
      if (!desktopBridge) return false;
      var result = await saveBridgeConfig(desktopBridge, payload);
      if (!result || !result.ok || !result.config) return false;
      params.desktopConfig = Object.assign({}, result.config);
      renderDefaultOutputPath(params, sessionForOutput);
      return true;
    },
    resetConfigToDefault: async function () {
      if (!desktopBridge) return false;
      var result = await resetBridgeConfig(desktopBridge);
      if (!result || !result.ok || !result.config) return false;
      params.desktopConfig = Object.assign({}, result.config);
      renderDefaultOutputPath(params, sessionForOutput);
      return true;
    },
    apiBase: params.apiBase,
    adminApiBase: params.adminApiBase,
    getAuthToken: function () {
      var sess = getSession();
      return (sess && sess.token) || "";
    },
    getAdminSkillsCatalogView: function () {
      return auth.getAdminSkillsCatalogView();
    },
    getAuthorizedSkillNames: function () {
      return auth.getAuthorizedSkillNames();
    },
    getUsername: function () {
      var sess = getSession();
      return (sess && sess.user && sess.user.username) || "";
    },
    selectDirectory: async function () {
      if (!desktopBridge || !desktopBridge.select_directory) return null;
      var raw = await desktopBridge.select_directory();
      var result = JSON.parse(raw);
      if (result && result.ok && result.path) {
        return result.path;
      }
      return null;
    },
    userPrefList: document.getElementById("user-pref-list"),
    userPrefKeyInput: document.getElementById("user-pref-key-input"),
    userPrefValueInput: document.getElementById("user-pref-value-input"),
    userPrefAddBtn: document.getElementById("user-pref-add-btn"),
    userPrefError: document.getElementById("user-pref-error"),
    mateInfoCard: document.getElementById("mate-info-card"),
    mateNameEl: document.getElementById("mate-name"),
    mateCompanyEl: document.getElementById("mate-company"),
    mateDepartmentEl: document.getElementById("mate-department"),
    mateTitleEl: document.getElementById("mate-title"),
    mcpServicesBody: document.getElementById("mcp-services-body"),
    mcpServicesRefresh: document.getElementById("mcp-services-refresh"),
  });

  var auth = createAuthController({
    apiBase: params.apiBase,
    adminApiBase: params.adminApiBase,
    loginScreen: loginScreen,
    appShell: appShell,
    loginForm: loginForm,
    loginError: loginError,
    loginSubmit: loginSubmit,
    loginTerms: loginTerms,
    loginClose: loginClose,
    sidebarUsername: sidebarUsername,
    sidebarAvatar: sidebarAvatar,
    settingsAvatar: settingsAvatar,
    settingsUsername: settingsUsername,
    onSessionChange: async function (session) {
      sessionForOutput = session || null;
      renderDefaultOutputPath(params, session);
      var username = session && session.user && session.user.username ? session.user.username : "";
      await chat.setScopedUser(username);
      if (session && session.token) {
        collabController.refresh();
        collabController.startPoll();
        if (contactsController) contactsController.loadContacts();
      } else {
        collabController.clear();
        collabController.stopPoll();
      }
      var tasksPanel = document.getElementById("view-tasks");
      if (
        tasksController &&
        tasksPanel &&
        !tasksPanel.classList.contains("hidden")
      ) {
        tasksController.refresh();
      }
    },
    onCollabNotification: function (msg) {
      collabController.handleNotification(msg);
      if (
        msg &&
        (msg.action === "collab_task_assigned" ||
          msg.action === "collab_step_rejected")
      ) {
        collabController.syncInboundAttachments(msg);
      }
      collabController.refresh();
      collabController.setSectionExpanded(true);
    },
    installSkillHandler: async function (task) {
      var r = await installSkillPackageViaBridge(desktopBridge, task);
      if (r && r.ok && desktopBridge) {
        try {
          await loadSkillsConfigFromBridge();
        } catch (e) {
          /* ignore */
        }
      }
      return r;
    },
    onAdminSkillsSync: function (merged, market) {
      if (!merged || typeof merged !== "object" || !merged.skills) return;
      (async function () {
        if (!desktopBridge) return;
        var res = await saveBridgeSkillsConfig(desktopBridge, merged);
        if (!res || !res.ok) return;
        var norm = normalizeSkillsConfig(res.config || merged);
        currentSkillsConfig = norm;
        setSyncState(skillsSyncState, "server");
        setSyncState(skillsManageSyncState, "server");
        setSkillsHint("已从管理端同步技能配置；正在检查技能包更新…");
        setSkillsManageHint("已从管理端同步技能配置（只读）；正在检查技能包更新…");
        renderSkillsList(norm);
        renderSkillsManageList(norm);
        renderSelectedSkillChips();
        if (skillsModal && !skillsModal.classList.contains("hidden")) {
          schedulePositionSkillsPopover();
        }
        var m = Array.isArray(market) ? market : [];
        for (var i = 0; i < m.length; i++) {
          var it = m[i];
          if (!it || !it.name || !it.latest_version) continue;
          var need = !it.installed_version || it.upgrade_available;
          if (!need) continue;
          auth.enqueueSkillInstall({
            task_id: "",
            skill_name: it.name,
            version: String(it.latest_version),
            download_url: "",
            sha256: String(it.sha256 || ""),
          });
        }
        try {
          await auth.whenInstallsIdle();
        } catch (e) {
          /* ignore */
        }
        try {
          await fetch(params.apiBase + "/skills/reload-config-cache", {
            method: "POST",
            cache: "no-store",
          });
        } catch (e) {
          /* local serve may be down; ignore */
        }
        try {
          await loadSkillsConfigFromBridge();
        } catch (e) {
          /* ignore */
        }
        if (skillsManageModal && !skillsManageModal.classList.contains("hidden")) {
          renderSkillsManageList(currentSkillsConfig);
        }
        var inv = await getBridgeSkillInventory(desktopBridge);
        if (inv && inv.ok && Array.isArray(inv.skills) && auth.sendOnlineMessage) {
          auth.sendOnlineMessage({ action: "skill_inventory", skills: inv.skills });
        }
        setSkillsHint("已从管理端同步技能配置与技能包（若需更新）。");
        setSkillsManageHint("已从管理端同步（只读）。");
        if (typeof settings.refreshSkillsSettingsList === "function") {
          settings.refreshSkillsSettingsList();
        }
      })();
    },
  });

  chat.bindConfirmDialog();
  chat.bindGlobalEvents();
  chat.bindBatchIconButtons();
  settings.bindPrefInputs();
  settings.bindSettingsModal();
  settings.bindConfigForm();
  settings.bindReadAllowedDirs();
  bindSettingsNav();
  bindWechatConfigSave();
  bindSkillsPanel();
  bindSkillsManagePanel();
  bindMcpPanel();
  auth.bindLoginForm();
  auth.bindLoginClose();
  auth.bindLogout(btnLogout, settings.closeSettings);

  chat.renderConversationList();
  chat.renderMessages();

  document.getElementById("btn-new-chat").addEventListener("click", function (e) {
    e.stopPropagation();
    chat.createConversation();
  });

  document.getElementById("btn-send").addEventListener("click", function () {
    chat.sendComposerMessage();
  });

  // 输入框自动撑高：内容超过当前高度时自动扩大，通过 max-height 限制上限
  var composerInputEl = document.getElementById("composer-input");
  function autoGrowComposer() {
    composerInputEl.style.height = "";
    composerInputEl.style.height = composerInputEl.scrollHeight + "px";
  }
  composerInputEl.addEventListener("input", autoGrowComposer);

  composerInputEl.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;

    // Shift+Enter / Ctrl+Enter / Meta+Enter：在光标处插入换行
    if (e.shiftKey || e.ctrlKey || e.metaKey) {
      e.preventDefault();
      var ta = e.target;
      var start = ta.selectionStart;
      var end = ta.selectionEnd;
      var before = ta.value.substring(0, start);
      var after = ta.value.substring(end);
      ta.value = before + "\n" + after;
      // 光标移到换行符之后
      ta.selectionStart = ta.selectionEnd = start + 1;
      // 手动触发 input 事件以驱动 autoGrowComposer
      ta.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }

    // 纯 Enter：发送消息
    e.preventDefault();
    chat.sendComposerMessage();
  });

  (async function bootstrap() {
    desktopBridge = await initDesktopBridge();
    var bridgeCfg = await getBridgeConfig(desktopBridge);
    if (bridgeCfg) {
      params.desktopConfig = Object.assign({}, baseDesktopConfig, pickConfigFields(bridgeCfg));
    }

    setBootStage("阶段 1/2", "启动服务", 8);
    showBoot("正在启动本地服务，请稍候…");
    appendBootLog("开始启动流程");
    var ready = await waitForBackendReady();
    var preloadReady = false;
    if (ready) {
      setBootStage("阶段 2/2", "加载能力", 52);
      showBoot("正在初始化项目能力（MCP/技能）");
      preloadReady = await waitForProjectPreload();
    }
    hideBoot();

    var existing = sessionForOutput;
    if (existing) {
      setBootStage("阶段 2/2", "加载数据", 98);
      showBoot("正在加载会话数据…");
      try {
        await chat.setScopedUser(existing && existing.user ? existing.user.username : "");
      } catch (_e) {
        /* 数据加载失败不阻塞启动 */
      }
      hideBoot();
    }
    auth.applySessionToUI(existing);
    renderDefaultOutputPath(params, existing);
    if (existing) {
      auth.hideLogin();
    } else {
      auth.showLogin();
    }
    appShell.classList.toggle("dimmed", !existing);
    if (!ready) {
      auth.setLoginError("服务启动较慢，请稍后重试登录。");
    } else     if (!preloadReady) {
      auth.setLoginError("项目初始化较慢，可先登录，首条消息可能稍有等待。");
    }
    if (ready) {
      var runtimeCheck = await fetchMcpRuntimeCheck();
      if (!runtimeCheck || !runtimeCheck.ok || !runtimeCheck.check) {
        lastMcpHealthForBadge = null;
        setSettingsMcpBadgeUnknown("无法连接自检接口");
      } else {
        var chk = runtimeCheck.check;
        if (chk.checked === false) {
          lastMcpHealthForBadge = null;
          setSettingsMcpBadgeUnknown("自检尚未完成");
        } else {
          var miss =
            typeof chk.missing_count === "number" && Number.isFinite(chk.missing_count)
              ? chk.missing_count
              : Array.isArray(chk.missing_commands)
                ? chk.missing_commands.length
                : 0;
          applyDesktopMcpHealthToBadge({
            loaded: true,
            unknown: false,
            hasRisk: !chk.ok,
            summary: chk.summary || "",
            missingCount: miss,
          });
        }
      }
    }
    if (tasksController) tasksController.mount();
  })();
})();

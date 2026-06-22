import { getPrefs, savePrefs } from "./storage.js";

export function createSettingsController(options) {
  var settingsModal = options.settingsModal;
  var btnSettings = options.btnSettings;
  var settingsClose = options.settingsClose;
  var prefSecurity = options.prefSecurity;
  var prefSleep = options.prefSleep;
  var prefTools = options.prefTools;
  var cfgWorkspaceRoot = options.cfgWorkspaceRoot;
  var cfgOutputTemplate = options.cfgOutputTemplate;
  var cfgOutputBaseDir = options.cfgOutputBaseDir;
  var cfgWechatWindowTitle = options.cfgWechatWindowTitle;
  var cfgWechatProcessName = options.cfgWechatProcessName;
  var cfgWechatAiReplyPrefix = options.cfgWechatAiReplyPrefix;
  var cfgAutoCreateRoot = options.cfgAutoCreateRoot;
  var cfgSaveLocal = options.cfgSaveLocal;
  var cfgResetDefault = options.cfgResetDefault;
  var cfgSaveHint = options.cfgSaveHint;
  /* 允许访问路径 DOM 引用 */
  var mcpReadDirsList = options.mcpReadDirsList || null;
  var cfgAddDirBtn = options.cfgAddDirBtn || null;
  /* 路径列表状态 */
  var readAllowedDirs = [];
  /* 通用设置 - 模型与模板 DOM 引用 */
  var cfgImageProvider = options.cfgImageProvider || null;
  var cfgLlmProvider = options.cfgLlmProvider || null;
  var cfgTemplateDir = options.cfgTemplateDir || null;
  var cfgImageTemplateDir = options.cfgImageTemplateDir || null;
  /* 通用设置 - 记忆与压缩 DOM 引用 */
  var cfgMemoryCompressEnabled = options.cfgMemoryCompressEnabled || null;
  var cfgMemoryCompressThreshold = options.cfgMemoryCompressThreshold || null;
  var cfgMemoryEnableTopicSearch = options.cfgMemoryEnableTopicSearch || null;
  var cfgMemorySearchCandidateLimit = options.cfgMemorySearchCandidateLimit || null;
  var cfgMemoryShortTermTasks = options.cfgMemoryShortTermTasks || null;
  var cfgMemoryMidTermTasks = options.cfgMemoryMidTermTasks || null;
  var cfgMemoryRelevantTasksLimit = options.cfgMemoryRelevantTasksLimit || null;
  /* 通用设置 - 沙箱与子代理 DOM 引用 */
  var cfgUseSandbox = options.cfgUseSandbox || null;
  var cfgEnableSubagents = options.cfgEnableSubagents || null;
  /* 微信设置 - 附件与缓存 DOM 引用 */
  var cfgWechatAttachmentSaveDir = options.cfgWechatAttachmentSaveDir || null;
  var cfgWechatAttachmentCacheFile = options.cfgWechatAttachmentCacheFile || null;
  var cfgWechatAudioCacheFile = options.cfgWechatAudioCacheFile || null;
  var mcpHealthSummary = options.mcpHealthSummary;
  var mcpHealthMissing = options.mcpHealthMissing;
  var mcpHealthServers = options.mcpHealthServers;
  var mcpHealthRefresh = options.mcpHealthRefresh;
  var fetchMcpHealth = options.fetchMcpHealth || (async function () { return null; });
  var onMcpHealthStateChange =
    options.onMcpHealthStateChange || function () {};
  var getConfigForForm = options.getConfigForForm || function () { return null; };
  var saveConfigFromForm = options.saveConfigFromForm || (async function () { return false; });
  var resetConfigToDefault = options.resetConfigToDefault || (async function () { return false; });
  var apiBase = options.apiBase || "";
  var adminApiBase = options.adminApiBase || "";
  var getUsername = options.getUsername || (function () { return ""; });
  var getAuthToken = options.getAuthToken || (function () { return ""; });
  var getAdminSkillsCatalogView =
    options.getAdminSkillsCatalogView ||
    function () {
      return null;
    };
  var getAuthorizedSkillNames =
    options.getAuthorizedSkillNames ||
    function () {
      return Object.create(null);
    };
  var selectDirectory = options.selectDirectory || (function () { return Promise.resolve(null); });

  /* 用户偏好相关 DOM 元素 */
  var userPrefList = options.userPrefList || null;
  var userPrefKeyInput = options.userPrefKeyInput || null;
  var userPrefValueInput = options.userPrefValueInput || null;
  var userPrefAddBtn = options.userPrefAddBtn || null;
  var userPrefError = options.userPrefError || null;

  /* 员工信息相关 DOM 元素 */
  var mateInfoCard = options.mateInfoCard || null;
  var mateNameEl = options.mateNameEl || null;
  var mateCompanyEl = options.mateCompanyEl || null;
  var mateDepartmentEl = options.mateDepartmentEl || null;
  var mateTitleEl = options.mateTitleEl || null;

  /* Markdown prompt 卡片加载相关 */
  var promptFiles = ["rich", "department", "identity"];

  /* MCP 服务列表相关 DOM 元素 */
  var mcpServicesBody = options.mcpServicesBody || null;
  var mcpServicesRefresh = options.mcpServicesRefresh || null;

  /* 模板管理相关状态 */
  var templateCategories = [];
  var templateAllItems = [];
  var templateFilterKey = "";

  /* 用户偏好批量管理状态 */
  var prefBatchMode = false;
  var prefBatchSelectedIds = {};

  function syncProviderBadge(badgeId, checked, leftLabel, rightLabel) {
    var badge = document.getElementById(badgeId);
    if (badge) badge.textContent = checked ? rightLabel : leftLabel;
  }

  /** Qt WebEngine: drive track/knob via inline style (pseudo-class updates are unreliable). */
  function syncSwitchVisual(input) {
    if (!input) return;
    var slider = input.closest(".switch") && input.closest(".switch").querySelector(".slider");
    if (!slider) return;
    var on = !!input.checked;
    slider.style.backgroundColor = on ? "#43a047" : "#cccccc";
    var knob = slider.querySelector(".slider-knob");
    if (knob) {
      knob.style.transform = on ? "translateX(18px)" : "translateX(0)";
    }
  }

  function syncAllSettingsSwitchVisuals() {
    if (!settingsModal) return;
    var inputs = settingsModal.querySelectorAll("label.switch > input[type=checkbox]");
    for (var i = 0; i < inputs.length; i++) {
      syncSwitchVisual(inputs[i]);
    }
  }

  function blockNativeToggle(e) {
    e.preventDefault();
    e.stopImmediatePropagation();
  }

  /** Qt WebEngine: toggle on mousedown; block label click to avoid double-flip. */
  function bindQtSafeSwitch(input) {
    if (!input) return;
    var label = input.closest(".switch");
    if (!label || label.classList.contains("switch-readonly")) return;
    if (label.dataset.qtSwitchBound === "1") return;
    label.dataset.qtSwitchBound = "1";

    label.addEventListener(
      "mousedown",
      function (e) {
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        input.checked = !input.checked;
        syncSwitchVisual(input);
        input.dispatchEvent(new Event("change", { bubbles: true }));
      },
      true
    );
    label.addEventListener("mouseup", blockNativeToggle, true);
    label.addEventListener("click", blockNativeToggle, true);
    syncSwitchVisual(input);
  }

  function bindQtPlainCheckbox(input) {
    if (!input || input.dataset.qtSwitchBound === "1") return;
    input.dataset.qtSwitchBound = "1";
    input.addEventListener(
      "mousedown",
      function (e) {
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        input.checked = !input.checked;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      },
      true
    );
    input.addEventListener("click", blockNativeToggle, true);
  }

  function bindAllSettingsModalSwitches() {
    if (!settingsModal) return;
    var inputs = settingsModal.querySelectorAll(
      "label.switch:not(.switch-readonly) > input[type=checkbox]"
    );
    for (var i = 0; i < inputs.length; i++) {
      bindQtSafeSwitch(inputs[i]);
    }
    if (cfgAutoCreateRoot) bindQtPlainCheckbox(cfgAutoCreateRoot);
    syncAllSettingsSwitchVisuals();
  }

  function normalizePathSlashes(path) {
    return String(path || "")
      .trim()
      .replace(/\\/g, "/")
      .replace(/\/{2,}/g, "/");
  }

  function syncPrefsToForm() {
    var p = getPrefs();
    if (prefSecurity) prefSecurity.checked = !!p.security;
    if (prefSleep) prefSleep.checked = !!p.sleep;
    if (prefTools) prefTools.checked = !!p.tools;
  }

  function bindPrefInputs() {
    bindAllSettingsModalSwitches();
    function onChange() {
      savePrefs({
        security: prefSecurity ? prefSecurity.checked : false,
        sleep: prefSleep ? prefSleep.checked : false,
        tools: prefTools ? prefTools.checked : false,
      });
    }
    if (prefSecurity) prefSecurity.addEventListener("change", onChange);
    if (prefSleep) prefSleep.addEventListener("change", onChange);
    if (prefTools) prefTools.addEventListener("change", onChange);
  }

  /* 懒加载追踪：记录哪些面板已完成首次加载，避免重复请求 */
  var _loadedPanels = {};

  var _settingsOpening = false;

  function openSettings(e) {
    if (e) {
      e.stopPropagation();
      e.preventDefault();
    }
    if (_settingsOpening) return;
    _settingsOpening = true;
    syncPrefsToForm();
    syncConfigToForm();
    refreshMcpHealth();
    loadUserPreferences();
    loadWxworkConfigFromEnv();
    checkWxworkConnectionStatus();
    settingsModal.classList.remove("hidden");
    settingsModal.setAttribute("aria-hidden", "false");
    switchSettingsPanel("profile");
    requestAnimationFrame(function () {
      _settingsOpening = false;
    });
  }

  /**
   * 根据导航面板名称，按需调用后端接口加载数据
   * 仅在首次切换到该面板时触发加载，后续切换不重复请求
   * @param {string} panelName - 导航面板名称: profile | wechat | mcp | skills | templates
   */
  function switchSettingsPanel(panelName) {
    if (panelName !== "skills" && _loadedPanels[panelName]) return;
    if (panelName !== "skills") _loadedPanels[panelName] = true;

    switch (panelName) {
      case "profile":
        loadPromptContents();
        break;
      case "wechat":
        loadWechatModeContents();
        break;
      case "mcp":
        loadMcpServicesConfig();
        break;
      case "skills":
        loadSkillsSettingsList();
        break;
      case "templates":
        loadTemplatesList();
        break;
      case "general":
        loadReadAllowedDirs();
        break;
      default:
        break;
    }
  }

  function syncConfigToForm() {
    var cfg = getConfigForForm();
    if (!cfg) return;
    if (cfgOutputBaseDir) cfgOutputBaseDir.value = normalizePathSlashes(cfg.output_base_dir || "");
    if (cfgWechatWindowTitle) cfgWechatWindowTitle.value = cfg.wechat_window_title || "";
    if (cfgWechatProcessName) cfgWechatProcessName.value = cfg.wechat_process_name || "";
    if (cfgWechatAiReplyPrefix) cfgWechatAiReplyPrefix.value = cfg.wechat_ai_reply_prefix || "";
    if (cfgWorkspaceRoot) cfgWorkspaceRoot.value = cfg.workspace_root || "";
    if (cfgOutputTemplate) cfgOutputTemplate.value = cfg.output_dir_template || "";
    if (cfgAutoCreateRoot) cfgAutoCreateRoot.checked = !!cfg.auto_create_workspace_root;
    if (cfgSaveHint) cfgSaveHint.textContent = "保存将写入本机 .env 文件。";
    /* 通用设置 - 模型与模板（开关：向左=左侧值，向右=右侧值） */
    if (cfgImageProvider) {
      cfgImageProvider.checked = (cfg.image_provider || "wan") === "wan";
      syncProviderBadge("cfg-image-provider-badge", cfgImageProvider.checked, "gemini", "wan");
    }
    if (cfgLlmProvider) {
      cfgLlmProvider.checked = (cfg.llm_provider || "deepseek") === "dashscope";
      syncProviderBadge("cfg-llm-provider-badge", cfgLlmProvider.checked, "deepseek", "dashscope");
    }
    if (cfgTemplateDir) cfgTemplateDir.value = cfg.template_dir || "";
    if (cfgImageTemplateDir) cfgImageTemplateDir.value = cfg.image_template_dir || "";
    /* 通用设置 - 记忆与压缩 */
    if (cfgMemoryCompressEnabled) cfgMemoryCompressEnabled.checked = !!cfg.memory_compress_enabled;
    if (cfgMemoryCompressThreshold) cfgMemoryCompressThreshold.value = cfg.memory_compress_threshold || 3000;
    if (cfgMemoryEnableTopicSearch) cfgMemoryEnableTopicSearch.checked = !!cfg.memory_enable_topic_search;
    if (cfgMemorySearchCandidateLimit) cfgMemorySearchCandidateLimit.value = cfg.memory_search_candidate_limit || 50;
    if (cfgMemoryShortTermTasks) cfgMemoryShortTermTasks.value = cfg.memory_short_term_tasks || 5;
    if (cfgMemoryMidTermTasks) cfgMemoryMidTermTasks.value = cfg.memory_mid_term_tasks || 25;
    if (cfgMemoryRelevantTasksLimit) cfgMemoryRelevantTasksLimit.value = cfg.memory_relevant_tasks_limit || 2;
    /* 通用设置 - 沙箱与子代理 */
    if (cfgUseSandbox) cfgUseSandbox.checked = !!cfg.use_sandbox;
    if (cfgEnableSubagents) cfgEnableSubagents.checked = !!cfg.enable_subagents;
    /* 微信设置 - 附件与缓存 */
    if (cfgWechatAttachmentSaveDir) cfgWechatAttachmentSaveDir.value = cfg.wechat_attachment_save_dir || "";
    if (cfgWechatAttachmentCacheFile) cfgWechatAttachmentCacheFile.value = cfg.wechat_attachment_cache_file || "";
    if (cfgWechatAudioCacheFile) cfgWechatAudioCacheFile.value = cfg.wechat_audio_cache_file || "";
    syncMateInfo(cfg);
    syncAllSettingsSwitchVisuals();
  }

  function syncMateInfo(cfg) {
    var hasAny = false;
    var fields = [
      { el: mateNameEl, value: cfg.mate_name },
      { el: mateCompanyEl, value: cfg.company_name },
      { el: mateDepartmentEl, value: cfg.department_name },
      { el: mateTitleEl, value: cfg.mate_title },
    ];
    for (var i = 0; i < fields.length; i++) {
      var text = (fields[i].value || "").trim();
      if (fields[i].el) {
        fields[i].el.textContent = text || "—";
      }
      if (text) hasAny = true;
    }
    var mateGrid = mateInfoCard ? mateInfoCard.querySelector(".mate-info-grid") : null;
    if (mateGrid) {
      mateGrid.style.display = hasAny ? "" : "none";
    }
  }

  function autoSaveGeneralSetting(cfgKey, cfgValue) {
    if (!apiBase) return;
    fetch(apiBase + "/api/desktop/general_env_config_single", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cfg_key: cfgKey, cfg_value: cfgValue }),
    }).then(function (res) { return res.json(); })
      .then(function (data) {
        if (data && data.ok) {
          console.info("自动保存 .env: " + cfgKey + "=" + cfgValue);
        }
      })
      .catch(function (e) {
        console.error("自动保存 .env 失败: " + (e.message || e));
      });
  }

  function bindConfigForm() {
    /* 输出目录 - 文本输入自动保存 */
    if (cfgOutputBaseDir) {
      cfgOutputBaseDir.addEventListener("change", function () {
        var val = normalizePathSlashes(cfgOutputBaseDir.value);
        autoSaveGeneralSetting("output_base_dir", val);
        /* 同时也保存到桌面配置 */
        saveConfigFromForm({ output_base_dir: val });
      });
    }
    /* 模板目录 - 文本输入自动保存 */
    if (cfgTemplateDir) {
      cfgTemplateDir.addEventListener("change", function () {
        var val = cfgTemplateDir.value.trim();
        if (val) autoSaveGeneralSetting("template_dir", val);
      });
    }
    if (cfgImageTemplateDir) {
      cfgImageTemplateDir.addEventListener("change", function () {
        var val = cfgImageTemplateDir.value.trim();
        if (val) autoSaveGeneralSetting("image_template_dir", val);
      });
    }
    /* 图片生成供应商 toggle */
    if (cfgImageProvider) {
      cfgImageProvider.addEventListener("change", function () {
        syncProviderBadge("cfg-image-provider-badge", cfgImageProvider.checked, "gemini", "wan");
        autoSaveGeneralSetting("image_provider", cfgImageProvider.checked ? "wan" : "gemini");
      });
    }
    /* LLM 供应商 toggle */
    if (cfgLlmProvider) {
      cfgLlmProvider.addEventListener("change", function () {
        syncProviderBadge("cfg-llm-provider-badge", cfgLlmProvider.checked, "deepseek", "dashscope");
        autoSaveGeneralSetting("llm_provider", cfgLlmProvider.checked ? "dashscope" : "deepseek");
      });
    }
    /* 布尔型 toggle 自动保存 */
    if (cfgMemoryCompressEnabled) {
      cfgMemoryCompressEnabled.addEventListener("change", function () {
        autoSaveGeneralSetting("memory_compress_enabled", cfgMemoryCompressEnabled.checked ? "true" : "false");
      });
    }
    if (cfgMemoryEnableTopicSearch) {
      cfgMemoryEnableTopicSearch.addEventListener("change", function () {
        autoSaveGeneralSetting("memory_enable_topic_search", cfgMemoryEnableTopicSearch.checked ? "true" : "false");
      });
    }
    if (cfgUseSandbox) {
      cfgUseSandbox.addEventListener("change", function () {
        autoSaveGeneralSetting("use_sandbox", cfgUseSandbox.checked ? "true" : "false");
      });
    }
    if (cfgEnableSubagents) {
      cfgEnableSubagents.addEventListener("change", function () {
        autoSaveGeneralSetting("enable_subagents", cfgEnableSubagents.checked ? "true" : "false");
      });
    }
    /* 数值型输入框自动保存 */
    if (cfgMemoryCompressThreshold) {
      cfgMemoryCompressThreshold.addEventListener("change", function () {
        var val = parseInt(cfgMemoryCompressThreshold.value, 10) || 3000;
        autoSaveGeneralSetting("memory_compress_threshold", val);
      });
    }
    if (cfgMemorySearchCandidateLimit) {
      cfgMemorySearchCandidateLimit.addEventListener("change", function () {
        var val = parseInt(cfgMemorySearchCandidateLimit.value, 10) || 50;
        autoSaveGeneralSetting("memory_search_candidate_limit", val);
      });
    }
    if (cfgMemoryShortTermTasks) {
      cfgMemoryShortTermTasks.addEventListener("change", function () {
        var val = parseInt(cfgMemoryShortTermTasks.value, 10) || 5;
        autoSaveGeneralSetting("memory_short_term_tasks", val);
      });
    }
    if (cfgMemoryMidTermTasks) {
      cfgMemoryMidTermTasks.addEventListener("change", function () {
        var val = parseInt(cfgMemoryMidTermTasks.value, 10) || 25;
        autoSaveGeneralSetting("memory_mid_term_tasks", val);
      });
    }
    if (cfgMemoryRelevantTasksLimit) {
      cfgMemoryRelevantTasksLimit.addEventListener("change", function () {
        var val = parseInt(cfgMemoryRelevantTasksLimit.value, 10) || 2;
        autoSaveGeneralSetting("memory_relevant_tasks_limit", val);
      });
    }
  }

  /* ---- 允许访问路径 ---- */

  async function loadReadAllowedDirs() {
    if (!mcpReadDirsList) return;
    try {
      var res = await fetch(apiBase + "/api/desktop/mcp_read_allowed_dirs", { cache: "no-store" });
      var data = await res.json();
      if (data && data.ok && Array.isArray(data.dirs)) {
        readAllowedDirs = data.dirs;
      } else {
        readAllowedDirs = [];
      }
    } catch (e) {
      console.error("加载允许访问路径失败: " + (e.message || e));
      readAllowedDirs = [];
    }
    renderReadAllowedDirs();
  }

  function renderReadAllowedDirs() {
    if (!mcpReadDirsList) return;
    if (!readAllowedDirs.length) {
      mcpReadDirsList.innerHTML = '<div class="dir-empty">暂无配置的允许访问路径</div>';
      return;
    }
    var html = "";
    for (var i = 0; i < readAllowedDirs.length; i++) {
      var dir = String(readAllowedDirs[i] || "");
      var escaped = dir.replace(/</g, "&lt;").replace(/>/g, "&gt;");
      html +=
        '<div class="dir-item" data-dir-index="' + i + '">' +
        '<span class="dir-item-path">' + escaped + '</span>' +
        '<button type="button" class="dir-item-del" data-dir-index="' + i + '">删除</button>' +
        '</div>';
    }
    mcpReadDirsList.innerHTML = html;
    /* 绑定删除按钮 */
    var delBtns = mcpReadDirsList.querySelectorAll(".dir-item-del");
    for (var j = 0; j < delBtns.length; j++) {
      delBtns[j].addEventListener("click", function () {
        var idx = parseInt(this.getAttribute("data-dir-index"), 10);
        if (!isNaN(idx) && idx >= 0 && idx < readAllowedDirs.length) {
          deleteReadAllowedDir(idx);
        }
      });
    }
  }

  async function deleteReadAllowedDir(index) {
    readAllowedDirs.splice(index, 1);
    renderReadAllowedDirs();
    await saveReadAllowedDirs();
  }

  async function saveReadAllowedDirs() {
    try {
      var res = await fetch(apiBase + "/api/desktop/mcp_read_allowed_dirs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dirs: readAllowedDirs }),
      });
      var data = await res.json();
      if (data && data.ok) {
        console.info("允许访问路径已保存到 .env");
      }
    } catch (e) {
      console.error("保存允许访问路径失败: " + (e.message || e));
    }
  }

  async function addReadAllowedDir() {
    /* 通过回调调用桌面端原生文件夹选择对话框 */
    var chosen = null;
    try {
      chosen = await selectDirectory();
    } catch (e) {
      console.error("调用桌面目录选择失败: " + (e.message || e));
    }
    if (!chosen || !chosen.trim()) return;
    /* 规范化路径中的反斜杠 */
    chosen = chosen.replace(/\\/g, "/").replace(/\/{2,}/g, "/");
    /* 去重 */
    if (readAllowedDirs.indexOf(chosen) >= 0) {
      return;
    }
    readAllowedDirs.push(chosen);
    renderReadAllowedDirs();
    await saveReadAllowedDirs();
  }

  function bindReadAllowedDirs() {
    if (cfgAddDirBtn) {
      cfgAddDirBtn.addEventListener("click", function () {
        addReadAllowedDir();
      });
    }
  }

  function setMcpHealthLoading() {
    if (mcpHealthRefresh) mcpHealthRefresh.disabled = true;
    if (mcpHealthSummary) {
      mcpHealthSummary.classList.remove("is-error");
      mcpHealthSummary.textContent = "正在读取自检结果…";
    }
    if (mcpHealthMissing) mcpHealthMissing.innerHTML = "";
    if (mcpHealthServers) mcpHealthServers.innerHTML = "";
  }

  function renderMcpHealth(check) {
    var payload = check && typeof check === "object" ? check : {};
    var ok = !!payload.ok;
    var summary = String(payload.summary || "").trim();
    var missing = Array.isArray(payload.missing_commands) ? payload.missing_commands : [];
    var servers = Array.isArray(payload.stdio_servers) ? payload.stdio_servers : [];
    if (mcpHealthSummary) {
      mcpHealthSummary.classList.toggle("is-error", !ok);
      mcpHealthSummary.textContent = summary || (ok ? "自检通过" : "自检未通过");
    }
    if (mcpHealthMissing) {
      if (!missing.length) {
        mcpHealthMissing.innerHTML = ok
          ? '<div class="mcp-health-item">未发现缺失依赖。</div>'
          : '<div class="mcp-health-item">未返回缺失详情，请查看 serve.log。</div>';
      } else {
        mcpHealthMissing.innerHTML = missing
          .map(function (item) {
            var name = String((item && item.server_name) || "未知服务");
            var cmd = String((item && item.command) || "");
            return (
              '<div class="mcp-health-item">⚠ ' +
              name +
              "（command=" +
              cmd +
              "）</div>"
            );
          })
          .join("");
      }
    }
    if (mcpHealthServers) {
      if (!servers.length) {
        mcpHealthServers.innerHTML = "";
      } else {
        mcpHealthServers.innerHTML = servers
          .map(function (item) {
            var name = String((item && item.server_name) || "未知服务");
            var cmd = String((item && item.command) || "");
            var flag = item && item.ok ? "✓" : "✗";
            return (
              '<div class="mcp-health-item">' +
              flag +
              " " +
              name +
              "（" +
              cmd +
              "）</div>"
            );
          })
          .join("");
      }
    }
  }

  async function refreshMcpHealth() {
    if (!mcpHealthSummary && !mcpHealthMissing && !mcpHealthServers) return;
    setMcpHealthLoading();
    try {
      var data = await fetchMcpHealth();
      if (!data || !data.ok || !data.check) {
        if (mcpHealthSummary) {
          mcpHealthSummary.classList.add("is-error");
          mcpHealthSummary.textContent = "读取自检结果失败，请确认后端已启动。";
        }
        onMcpHealthStateChange({
          loaded: true,
          unknown: true,
          hasRisk: false,
          summary: "读取自检结果失败，请确认后端已启动。",
          missingCount: 0,
        });
        return;
      }
      renderMcpHealth(data.check);
      var missingList = Array.isArray(data.check.missing_commands)
        ? data.check.missing_commands
        : [];
      var missCount =
        typeof data.check.missing_count === "number" &&
        Number.isFinite(data.check.missing_count)
          ? data.check.missing_count
          : missingList.length;
      onMcpHealthStateChange({
        loaded: true,
        unknown: false,
        hasRisk: !data.check.ok,
        summary: String(data.check.summary || ""),
        missingCount: missCount,
      });
    } finally {
      if (mcpHealthRefresh) mcpHealthRefresh.disabled = false;
    }
  }

  /* ---- 用户偏好 ---- */

  async function loadUserPreferences() {
    if (!userPrefList) return;
    var user = getUsername();
    if (!user) {
      userPrefList.innerHTML = '<div class="pref-empty">请先登录</div>';
      return;
    }
    userPrefList.innerHTML = '<div class="pref-empty">加载中…</div>';
    try {
      var res = await fetch(
        apiBase +
          "/api/desktop/user_preferences?username=" +
          encodeURIComponent(user),
        { cache: "no-store" }
      );
      var data = await res.json();
      if (!data || !data.ok) {
        userPrefList.innerHTML =
          '<div class="pref-empty">' +
          (data && data.message ? data.message : "加载失败") +
          "</div>";
        return;
      }
      renderUserPreferencesList(data.preferences || []);
    } catch (e) {
      userPrefList.innerHTML =
        '<div class="pref-empty">加载失败: ' + (e.message || e) + "</div>";
    }
  }

  function renderUserPreferencesList(preferences) {
    if (!userPrefList) return;
    if (!preferences.length) {
      userPrefList.innerHTML =
        '<div class="pref-empty">暂无偏好记录，AI 会在对话中自动学习您的偏好</div>';
      updatePrefBatchIcon();
      return;
    }
    var html = "";
    for (var i = 0; i < preferences.length; i++) {
      var pref = preferences[i];
      var key = String(pref.pref_key || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      var value = String(pref.pref_value || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      var time = pref.updated_at
        ? String(pref.updated_at).replace(/\..*/, "").replace("T", " ")
        : "";
      var checked = prefBatchSelectedIds[pref.id] ? " checked" : "";
      html +=
        '<div class="pref-card' +
        (prefBatchMode ? " batch-mode" : "") +
        '" data-pref-id="' +
        pref.id +
        '">' +
        (prefBatchMode
          ? '<input type="checkbox" class="pref-checkbox pref-batch-select" data-pref-id="' +
            pref.id +
            '"' +
            checked +
            ' />'
          : ""
        ) +
        '<div class="pref-card-body">' +
        '<div class="pref-card-key">' +
        key +
        "</div>" +
        '<div class="pref-card-value">' +
        value +
        "</div>" +
        (time ? '<div class="pref-card-time">' + time + "</div>" : "") +
        "</div>" +
        (prefBatchMode
          ? ""
          : '<div class="pref-card-actions">' +
            '<button type="button" class="pref-edit-btn" data-pref-id="' +
            pref.id +
            '" data-pref-key="' +
            key +
            '" data-pref-value="' +
            value +
            '">编辑</button>' +
            '<button type="button" class="pref-del-btn" data-pref-id="' +
            pref.id +
            '">删除</button>' +
            "</div>"
        ) +
        "</div>";
    }

    userPrefList.innerHTML = html;

    /* 填充偏好标题行的批量操作内联控件 */
    var prefSlot = document.getElementById("pref-batch-slot");
    var prefTitle = document.getElementById("user-pref-section-title");
    if (prefBatchMode && prefSlot && prefTitle) {
      var selectedCount = preferences.filter(function (p) { return prefBatchSelectedIds[p.id]; }).length;
      prefSlot.innerHTML =
        '<span class="batch-info-inline">' +
        (selectedCount > 0 ? "已选" + selectedCount : "") +
        "</span>" +
        '<button type="button" class="batch-sm-btn" id="pref-batch-select-all">全选</button>' +
        '<button type="button" class="batch-sm-btn" id="pref-batch-cancel">取消</button>' +
        '<button type="button" class="batch-sm-btn batch-sm-del" id="pref-batch-delete"' +
        (selectedCount === 0 ? " disabled" : "") +
        ">删除</button>";
      prefTitle.classList.add("batch-mode");
    } else {
      if (prefSlot) prefSlot.innerHTML = "";
      if (prefTitle) prefTitle.classList.remove("batch-mode");
    }

    if (!prefBatchMode) {
      /* 绑定删除按钮 */
      var delBtns = userPrefList.querySelectorAll(".pref-del-btn");
      for (var d = 0; d < delBtns.length; d++) {
        delBtns[d].addEventListener("click", function (e) {
          var prefId = parseInt(this.getAttribute("data-pref-id"), 10);
          if (!prefId || !window.confirm("确定删除该偏好记录？")) return;
          deleteUserPreference(prefId);
        });
      }

      /* 绑定编辑按钮 */
      var editBtns = userPrefList.querySelectorAll(".pref-edit-btn");
      for (var ed = 0; ed < editBtns.length; ed++) {
        editBtns[ed].addEventListener("click", function (e) {
          var prefKey = this.getAttribute("data-pref-key") || "";
          var prefValue = this.getAttribute("data-pref-value") || "";
          if (userPrefKeyInput) userPrefKeyInput.value = prefKey;
          if (userPrefValueInput) userPrefValueInput.value = prefValue;
          if (userPrefAddBtn) userPrefAddBtn.textContent = "更新";
          if (userPrefAddBtn) userPrefAddBtn.dataset.prefId = this.getAttribute("data-pref-id");
        });
      }
    }

    /* 批量模式复选框事件 */
    if (prefBatchMode) {
      bindPrefBatchEvents(preferences);
    }

    updatePrefBatchIcon();
  }

  async function addUserPreference() {
    var key = (userPrefKeyInput ? userPrefKeyInput.value : "").trim();
    var value = (userPrefValueInput ? userPrefValueInput.value : "").trim();
    var user = getUsername();
    if (!user) {
      showPrefError("请先登录");
      return;
    }
    if (!key) {
      showPrefError("请输入偏好名称");
      return;
    }
    if (!value) {
      showPrefError("请输入偏好内容");
      return;
    }
    hidePrefError();
    try {
      var res = await fetch(apiBase + "/api/desktop/user_preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          username: user,
          pref_key: key,
          pref_value: value,
        }),
      });
      var data = await res.json();
      if (!data || !data.ok) {
        showPrefError(data && data.message ? data.message : "保存失败");
        return;
      }
      /* 清空输入框，重新加载 */
      if (userPrefKeyInput) userPrefKeyInput.value = "";
      if (userPrefValueInput) userPrefValueInput.value = "";
      if (userPrefAddBtn) {
        userPrefAddBtn.textContent = "添加";
        delete userPrefAddBtn.dataset.prefId;
      }
      loadUserPreferences();
    } catch (e) {
      showPrefError("保存失败: " + (e.message || e));
    }
  }

  async function deleteUserPreference(prefId) {
    var user = getUsername();
    if (!user) return;
    try {
      var res = await fetch(
        apiBase +
          "/api/desktop/user_preferences/" +
          encodeURIComponent(prefId) +
          "?username=" +
          encodeURIComponent(user),
        { method: "DELETE", cache: "no-store" }
      );
      var data = await res.json();
      if (!data || !data.ok) {
        showPrefError(data && data.message ? data.message : "删除失败");
        return;
      }
      hidePrefError();
      loadUserPreferences();
    } catch (e) {
      showPrefError("删除失败: " + (e.message || e));
    }
  }

  function showPrefError(msg) {
    if (userPrefError) {
      userPrefError.textContent = msg;
      userPrefError.classList.remove("hidden");
    }
  }

  function hidePrefError() {
    if (userPrefError) {
      userPrefError.textContent = "";
      userPrefError.classList.add("hidden");
    }
  }

  function bindUserPrefInputs() {
    if (userPrefAddBtn) {
      userPrefAddBtn.addEventListener("click", addUserPreference);
    }
    if (userPrefKeyInput) {
      userPrefKeyInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") addUserPreference();
      });
    }
    if (userPrefValueInput) {
      userPrefValueInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") addUserPreference();
      });
    }
  }

  /* ---- 偏好批量管理 ---- */

  function bindPrefBatchEvents(preferences) {
    var checkboxes = userPrefList.querySelectorAll(".pref-batch-select");
    for (var i = 0; i < checkboxes.length; i++) {
      checkboxes[i].addEventListener("click", function (e) {
        e.stopPropagation();
        var pid = this.getAttribute("data-pref-id");
        if (prefBatchSelectedIds[pid]) {
          delete prefBatchSelectedIds[pid];
        } else {
          prefBatchSelectedIds[pid] = true;
        }
        loadUserPreferences();
      });
    }

    var selectAllBtn = document.querySelector("#pref-batch-select-all");
    if (selectAllBtn) {
      selectAllBtn.addEventListener("click", function () {
        var allSelected = preferences.every(function (p) { return prefBatchSelectedIds[p.id]; });
        if (allSelected) {
          preferences.forEach(function (p) { delete prefBatchSelectedIds[p.id]; });
        } else {
          preferences.forEach(function (p) { prefBatchSelectedIds[p.id] = true; });
        }
        loadUserPreferences();
      });
    }

    var cancelBtn = document.querySelector("#pref-batch-cancel");
    if (cancelBtn) {
      cancelBtn.addEventListener("click", function () {
        prefBatchMode = false;
        prefBatchSelectedIds = {};
        loadUserPreferences();
      });
    }

    var delBtn = document.querySelector("#pref-batch-delete");
    if (delBtn) {
      delBtn.addEventListener("click", function () {
        batchDeletePreferences();
      });
    }
  }

  function batchDeletePreferences() {
    if (!userPrefList) return;
    var selectedIds = Object.keys(prefBatchSelectedIds).filter(function (id) { return prefBatchSelectedIds[id]; });
    if (!selectedIds.length) return;
    if (!window.confirm("确定删除选中的 " + selectedIds.length + " 条偏好记录？")) return;
    var user = getUsername();
    if (!user) return;
    var errors = [];
    var done = 0;
    selectedIds.forEach(function (prefId) {
      fetch(
        apiBase +
          "/api/desktop/user_preferences/" +
          encodeURIComponent(prefId) +
          "?username=" +
          encodeURIComponent(user),
        { method: "DELETE", cache: "no-store" }
      )
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (!data || !data.ok) {
            errors.push(data && data.message ? data.message : "删除失败");
          }
        })
        .catch(function (err) {
          errors.push(err.message || err);
        })
        .finally(function () {
          done += 1;
          if (done >= selectedIds.length) {
            prefBatchMode = false;
            prefBatchSelectedIds = {};
            loadUserPreferences();
            if (errors.length) {
              showPrefError("部分删除失败: " + errors.join("; "));
            }
          }
        });
    });
  }

  function togglePrefBatchMode() {
    prefBatchMode = !prefBatchMode;
    prefBatchSelectedIds = {};
    loadUserPreferences();
  }

  function updatePrefBatchIcon() {
    var btn = document.getElementById("user-pref-batch-btn");
    if (btn) btn.classList.toggle("is-active", prefBatchMode);
  }

  function bindPrefBatchIcon() {
    var btn = document.getElementById("user-pref-batch-btn");
    if (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        togglePrefBatchMode();
      });
    }
  }

  function closeSettings() {
    settingsModal.classList.add("hidden");
    settingsModal.setAttribute("aria-hidden", "true");
  }

  function handleOverlayClick(e) {
    if (e.target === settingsModal) {
      closeSettings();
    }
  }

  function bindSettingsModal() {
    btnSettings.addEventListener("click", openSettings);
    settingsClose.addEventListener("click", function (e) {
      e.stopPropagation();
      closeSettings();
    });
    settingsModal.addEventListener("click", handleOverlayClick);
    if (mcpHealthRefresh) {
      mcpHealthRefresh.addEventListener("click", function (e) {
        e.stopPropagation();
        refreshMcpHealth();
      });
    }
    bindPromptCardToggles();
    bindWxworkConfig();
  }

  /* ---- 企微设置交互 ---- */

  function bindWxworkConfig() {
    /* 密码可见/隐藏切换 */
    var botIdInput = document.getElementById("cfg-wxwork-bot-id");
    var botIdToggle = document.getElementById("cfg-wxwork-bot-id-toggle");
    var secretInput = document.getElementById("cfg-wxwork-secret");
    var secretToggle = document.getElementById("cfg-wxwork-secret-toggle");

    if (botIdToggle && botIdInput) {
      botIdToggle.addEventListener("click", function () {
        var isPassword = botIdInput.type === "password";
        botIdInput.type = isPassword ? "text" : "password";
        botIdToggle.classList.toggle("is-visible", isPassword);
      });
    }
    if (secretToggle && secretInput) {
      secretToggle.addEventListener("click", function () {
        var isPassword = secretInput.type === "password";
        secretInput.type = isPassword ? "text" : "password";
        secretToggle.classList.toggle("is-visible", isPassword);
      });
    }

    /* 保存企微配置到 .env */
    var wxworkSaveBtn = document.getElementById("cfg-wxwork-save");
    var wxworkHintEl = document.getElementById("cfg-wxwork-hint");
    if (wxworkSaveBtn) {
      wxworkSaveBtn.addEventListener("click", async function () {
        var botId = (botIdInput ? botIdInput.value : "").trim();
        var secret = (secretInput ? secretInput.value : "").trim();
        if (!botId && !secret) {
          if (wxworkHintEl) wxworkHintEl.textContent = "请至少填写一个配置项。";
          return;
        }
        try {
          var res = await fetch(apiBase + "/api/desktop/wxwork_env_config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              WXWORK_BOT_ID: botId,
              WXWORK_SECRET: secret,
            }),
          });
          var data = await res.json();
          if (data && data.ok) {
            if (wxworkHintEl) wxworkHintEl.textContent = "已写入 .env 文件并立即生效。";
          } else {
            if (wxworkHintEl) wxworkHintEl.textContent = (data && data.message) || "保存失败，请检查配置。";
          }
        } catch (e) {
          if (wxworkHintEl) wxworkHintEl.textContent = "保存失败: " + (e.message || e);
        }
      });
    }

    /* 连接企微长连接 */
    var connectBtn = document.getElementById("cfg-wxwork-connect");
    var disconnectBtn = document.getElementById("cfg-wxwork-disconnect");
    var connectionHintEl = document.getElementById("cfg-wxwork-connection-hint");

    function setWxworkConnectedState(running, message) {
      if (!connectBtn || !disconnectBtn) return;
      if (running) {
        connectBtn.style.display = "none";
        disconnectBtn.style.display = "";
        disconnectBtn.disabled = false;
        if (connectionHintEl) connectionHintEl.textContent = message || "企微长连接运行中";
      } else {
        connectBtn.style.display = "";
        connectBtn.disabled = false;
        connectBtn.textContent = "连接";
        disconnectBtn.style.display = "none";
        if (connectionHintEl) connectionHintEl.textContent = message || "企微长连接未启动";
      }
    }

    /* 连接企微长连接 —— 启动后二次验证确保进程真正存活 */
    if (connectBtn) {
      connectBtn.addEventListener("click", async function () {
        connectBtn.disabled = true;
        connectBtn.textContent = "连接中…";
        if (connectionHintEl) connectionHintEl.textContent = "正在启动企微长连接服务…";
        var controller = new AbortController();
        var timeoutId = setTimeout(function () { controller.abort(); }, 15000);
        try {
          var res = await fetch(apiBase + "/api/desktop/wxwork_connect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            signal: controller.signal,
          });
          clearTimeout(timeoutId);
          if (!res.ok) {
            setWxworkConnectedState(false, "服务端错误 (HTTP " + res.status + ")，请确认后端已重启。");
            return;
          }
          var data = await res.json();
          if (data && data.ok) {
            /* API 返回成功，但进程可能在后续几秒内崩溃，需二次验证 */
            if (connectionHintEl) connectionHintEl.textContent = (data.message || "企微长连接已启动") + "，正在验证…";
            setTimeout(async function () {
              try {
                var verifyRes = await fetch(apiBase + "/api/desktop/wxwork_connect", {
                  method: "GET", cache: "no-store",
                });
                var verifyData = await verifyRes.json();
                if (verifyData && verifyData.ok && verifyData.running) {
                  setWxworkConnectedState(true, "企微长连接运行中 (PID=" + (verifyData.pid || "") + ")");
                } else {
                  /* 二次验证发现进程已退出，更新 UI 为未连接状态 */
                  setWxworkConnectedState(false, "企微长连接启动后很快退出，请检查配置或查看日志。");
                }
              } catch (e) {
                setWxworkConnectedState(false, "验证连接状态失败: " + (e.message || e));
              }
            }, 3000);
          } else {
            setWxworkConnectedState(false, (data && data.message) || "启动失败，请检查配置。");
          }
        } catch (e) {
          clearTimeout(timeoutId);
          if (e.name === "AbortError") {
            setWxworkConnectedState(false, "连接请求超时，请确认后端服务正常运行。");
          } else {
            setWxworkConnectedState(false, "启动请求失败: " + (e.message || e));
          }
        }
      });
    }

    if (disconnectBtn) {
      disconnectBtn.addEventListener("click", async function () {
        disconnectBtn.disabled = true;
        disconnectBtn.textContent = "断开中…";
        if (connectionHintEl) connectionHintEl.textContent = "正在断开企微长连接…";
        var controller = new AbortController();
        var timeoutId = setTimeout(function () { controller.abort(); }, 10000);
        try {
          var res = await fetch(apiBase + "/api/desktop/wxwork_disconnect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            signal: controller.signal,
          });
          clearTimeout(timeoutId);
          if (!res.ok) {
            setWxworkConnectedState(true, "断开失败 (HTTP " + res.status + ")");
            return;
          }
          var data = await res.json();
          if (data && data.ok) {
            setWxworkConnectedState(false, data.message || "企微长连接已断开");
          } else {
            setWxworkConnectedState(true, (data && data.message) || "断开失败");
          }
        } catch (e) {
          clearTimeout(timeoutId);
          if (e.name === "AbortError") {
            setWxworkConnectedState(true, "断开请求超时，请稍后重试。");
          } else {
            setWxworkConnectedState(true, "断开请求失败: " + (e.message || e));
          }
        }
      });
    }

    window._checkWxworkConnectionStatus = async function () {
      try {
        var res = await fetch(apiBase + "/api/desktop/wxwork_connect", {
          method: "GET",
          cache: "no-store",
        });
        var data = await res.json();
        if (data && data.ok && data.running) {
          setWxworkConnectedState(true, data.message || "企微长连接运行中");
        } else {
          setWxworkConnectedState(false, (data && data.message) || "企微长连接未启动");
        }
      } catch (e) {
        setWxworkConnectedState(false, "无法连接后端服务");
      }
    };
  }

  async function loadWxworkConfigFromEnv() {
    var botNameInput = document.getElementById("cfg-wxwork-bot-name");
    var botIdInput = document.getElementById("cfg-wxwork-bot-id");
    var secretInput = document.getElementById("cfg-wxwork-secret");
    try {
      var res = await fetch(apiBase + "/api/desktop/wxwork_env_config", {
        method: "GET",
        cache: "no-store",
      });
      var data = await res.json();
      if (data && data.ok && data.values) {
        if (botNameInput) botNameInput.value = data.values.WXWORK_BOT_NAME || "";
        if (botIdInput) botIdInput.value = data.values.WXWORK_BOT_ID || "";
        if (secretInput) secretInput.value = data.values.WXWORK_SECRET || "";
      }
    } catch (e) {
      /* 读取失败时保留空值，不影响面板显示 */
    }
  }

  /* ---- 技能设置交互 ---- */

  async function fetchAdminSkillsCatalogFromApi() {
    var base = String(adminApiBase || "").replace(/\/$/, "");
    var token = String(getAuthToken() || "").trim();
    if (!base || !token) return null;
    var res = await fetch(base + "/api/admin/skills/paginated?page=1&page_size=200", {
      cache: "no-store",
      headers: { Authorization: "Bearer " + token },
    });
    if (!res.ok) return null;
    var body = await res.json();
    var rows = body && Array.isArray(body.data) ? body.data : [];
    if (!rows.length) return null;
    var allowed = getAuthorizedSkillNames();
    var skills = {};
    rows.forEach(function (item) {
      if (!item || !item.name) return;
      var name = String(item.name);
      skills[name] = {
        description: String(item.description || "").trim(),
        enabled: item.enabled !== false,
        authorized: !!allowed[name],
      };
    });
    return { skills: skills, source: "api" };
  }

  async function resolveAdminSkillsCatalogView() {
    var cached = getAdminSkillsCatalogView();
    if (cached && cached.skills && Object.keys(cached.skills).length) return cached;
    return fetchAdminSkillsCatalogFromApi();
  }

  async function loadSkillsSettingsList() {
    var listEl = document.getElementById("skills-settings-list");
    var hintEl = document.getElementById("skills-settings-hint");
    if (!listEl) return;
    listEl.innerHTML = '<div class="pref-empty">加载中…</div>';
    try {
      var catalogView = await resolveAdminSkillsCatalogView();
      if (catalogView && catalogView.skills) {
        renderSkillsSettingsList(catalogView.skills, listEl, hintEl);
        return;
      }
      if (!getAuthToken()) {
        listEl.innerHTML =
          '<div class="pref-empty">请先登录管理端账号，以查看与管理端一致的技能目录。</div>';
        if (hintEl) hintEl.textContent = "未登录";
        return;
      }
      listEl.innerHTML =
        '<div class="pref-empty">正在等待管理端同步技能目录，请稍后重试或重新打开本页。</div>';
      if (hintEl) hintEl.textContent = "等待 WebSocket config_sync";
    } catch (e) {
      listEl.innerHTML = '<div class="pref-empty">加载失败: ' + (e.message || e) + '</div>';
      if (hintEl) hintEl.textContent = "加载技能目录失败";
    }
  }

  function renderSkillsSettingsList(skills, listEl, hintEl) {
    var allNames = Object.keys(skills || {});
    var names = allNames.filter(function (name) {
      return !!(skills[name] && skills[name].enabled);
    });
    if (!names.length) {
      listEl.innerHTML =
        '<div class="pref-empty">管理端当前没有已启用的技能。</div>';
      if (hintEl) {
        hintEl.textContent = allNames.length
          ? "共 " + allNames.length + " 个技能均未在管理端启用"
          : "管理端未返回技能";
      }
      return;
    }
    names.sort(function (a, b) {
      var aa = !!(skills[a] && skills[a].authorized);
      var ab = !!(skills[b] && skills[b].authorized);
      if (aa !== ab) return aa ? -1 : 1;
      return a.localeCompare(b);
    });
    var authorizedCount = 0;
    var html = "";
    for (var i = 0; i < names.length; i++) {
      var name = names[i];
      var item = skills[name] || {};
      var authorized = !!item.authorized;
      var desc = String(item.description || "").trim();
      if (authorized) authorizedCount++;
      var safeName = name.replace(/</g, "&lt;").replace(/>/g, "&gt;");
      var safeDesc = desc
        ? desc.replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, " ")
        : "暂无描述";
      var badges =
        '<span class="skills-settings-item-badge is-enabled">启用</span>';
      if (!authorized) {
        badges +=
          '<span class="skills-settings-item-badge is-restricted">暂无权限</span>';
      }
      html +=
        '<div class="skills-settings-item">' +
        '<div class="skills-settings-item-body">' +
        '<div class="skills-settings-item-name">' +
        safeName +
        "</div>" +
        '<div class="skills-settings-item-desc">' +
        safeDesc +
        "</div>" +
        "</div>" +
        '<div class="skills-settings-item-badges">' +
        badges +
        "</div>" +
        "</div>";
    }
    listEl.innerHTML = html;
    if (hintEl) {
      hintEl.textContent =
        "仅展示管理端已启用的技能，共 " +
        names.length +
        " 个；您当前可使用 " +
        authorizedCount +
        " 个。";
    }
  }

  /* ---- 模板管理交互 ---- */

  /**
   * 分类图标映射
   */
  function _templateCategoryIcon(categoryKey) {
    if (categoryKey === "report") return "📄";
    if (categoryKey === "image") return "🖼";
    if (categoryKey === "video") return "🎬";
    return "📄";
  }

  /**
   * 格式化文件大小
   */
  function _formatTemplateFileSize(size) {
    if (!size) return "0 B";
    var units = ["B", "KB", "MB", "GB"];
    var i = 0;
    var s = size;
    while (s >= 1024 && i < units.length - 1) { s /= 1024; i++; }
    return s.toFixed(i > 0 ? 1 : 0) + " " + units[i];
  }

  /**
   * 格式化时间戳为可读日期
   */
  function _formatTemplateTime(ts) {
    if (!ts) return "—";
    var d = new Date(ts);
    if (isNaN(d.getTime())) return String(ts).slice(0, 10);
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  /**
   * 加载模板分类和模板列表
   */
  async function loadTemplatesList() {
    var listEl = document.getElementById("templates-settings-list");
    var hintEl = document.getElementById("templates-settings-hint");
    var tabsEl = document.getElementById("templates-filter-tabs");
    if (!listEl) return;
    listEl.innerHTML = '<div class="pref-empty">加载中…</div>';
    if (tabsEl) tabsEl.innerHTML = "";

    try {
      /* 桌面端模板 API（无需 admin 鉴权） */
      var base = apiBase;
      /* 并行请求分类和模板列表 */
      var catRes = await fetch(base + "/api/desktop/templates/categories", { cache: "no-store" });
      var catData = await catRes.json();
      var tplRes = await fetch(base + "/api/desktop/templates/list", { cache: "no-store" });
      var tplData = await tplRes.json();

      if (!catData || !catData.ok) {
        listEl.innerHTML = '<div class="pref-empty">加载分类失败</div>';
        return;
      }
      templateCategories = catData.categories || [];

      if (!tplData || !tplData.ok) {
        listEl.innerHTML = '<div class="pref-empty">加载模板列表失败</div>';
        return;
      }
      templateAllItems = tplData.data || [];
      templateFilterKey = "";

      /* 渲染分类筛选标签 */
      renderTemplateFilterTabs(tabsEl);
      /* 渲染模板列表 */
      renderTemplatesList(listEl, hintEl);
    } catch (e) {
      listEl.innerHTML = '<div class="pref-empty">加载失败: ' + (e.message || e) + '</div>';
      if (hintEl) hintEl.textContent = "加载模板数据失败";
    }
  }

  /**
   * 渲染分类筛选标签
   */
  function renderTemplateFilterTabs(tabsEl) {
    if (!tabsEl) return;
    var html = '<button type="button" class="template-filter-tab active" data-filter="">全部</button>';
    for (var i = 0; i < templateCategories.length; i++) {
      var cat = templateCategories[i];
      var key = cat.category_key || "";
      var name = cat.category_name || key;
      var icon = _templateCategoryIcon(key);
      html += '<button type="button" class="template-filter-tab" data-filter="' +
        key.replace(/"/g, "&quot;") + '">' + icon + " " + name + '</button>';
    }
    tabsEl.innerHTML = html;

    /* 绑定筛选事件 */
    tabsEl.addEventListener("click", function (e) {
      var btn = e.target.closest && e.target.closest(".template-filter-tab");
      if (!btn) return;
      var filterKey = btn.getAttribute("data-filter") || "";
      templateFilterKey = filterKey;
      /* 更新激活状态 */
      var allTabs = tabsEl.querySelectorAll(".template-filter-tab");
      for (var j = 0; j < allTabs.length; j++) {
        allTabs[j].classList.toggle("active", allTabs[j].getAttribute("data-filter") === filterKey);
      }
      var listEl = document.getElementById("templates-settings-list");
      var hintEl = document.getElementById("templates-settings-hint");
      renderTemplatesList(listEl, hintEl);
    });
  }

  /**
   * 渲染模板列表
   */
  function renderTemplatesList(listEl, hintEl) {
    if (!listEl) return;
    /* 按分类筛选 */
    var items = templateAllItems;
    if (templateFilterKey) {
      items = items.filter(function (t) { return (t.category_key || "") === templateFilterKey; });
    }
    if (!items.length) {
      listEl.innerHTML = '<div class="pref-empty">暂无可用模板</div>';
      if (hintEl) hintEl.textContent = "没有匹配的模板";
      return;
    }

    var html = "";
    for (var i = 0; i < items.length; i++) {
      var t = items[i];
      var icon = _templateCategoryIcon(t.category_key);
      var safeName = String(t.template_name || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      var safeKey = String(t.template_key || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      var safeDesc = String(t.description || "").trim();
      if (safeDesc) {
        safeDesc = safeDesc.replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, " ");
      }
      var catName = String(t.category_name || t.category_key || "");
      var version = t.version != null ? "v" + t.version : "";
      var updated = _formatTemplateTime(t.updated_at);
      var fileSize = t.file_size ? _formatTemplateFileSize(t.file_size) : "";
      var isActive = t.is_active === 1;

      /* 元信息行：分类 · 版本 · 大小 · 更新时间 */
      var metaParts = [];
      if (catName) metaParts.push(catName);
      if (version) metaParts.push(version);
      if (fileSize) metaParts.push(fileSize);
      if (updated) metaParts.push(updated);
      var metaLine = metaParts.join(" · ");

      /* 封面缩略图：使用原始 cover_url，不触发下载 URL 生成 */
      var coverUrl = t.cover_url || "";
      var thumbHtml = "";
      if (coverUrl) {
        thumbHtml =
          '<div class="templates-settings-item-thumb" data-cover-url="' +
          coverUrl.replace(/"/g, "&quot;") + '" title="点击放大查看">' +
          '<img src="' + coverUrl.replace(/"/g, "&quot;") + '" alt="' + safeName + '" loading="lazy">' +
          '</div>';
      }

      html +=
        '<div class="templates-settings-item">' +
        '<div class="templates-settings-item-icon">' + icon + '</div>' +
        '<div class="templates-settings-item-body">' +
        '<div class="templates-settings-item-name">' + safeName + '</div>' +
        '<div class="templates-settings-item-key">' + safeKey + '</div>' +
        (safeDesc ? '<div class="templates-settings-item-desc">' + safeDesc + '</div>' : '') +
        (metaLine ? '<div class="templates-settings-item-meta">' + metaLine + '</div>' : '') +
        '</div>' +
        (thumbHtml ? thumbHtml : '') +
        '<span class="skills-settings-item-badge ' +
        (isActive ? "is-enabled" : "is-disabled") +
        '">' +
        (isActive ? "启用" : "禁用") +
        '</span>' +
        '</div>';
    }
    listEl.innerHTML = html;

    /* 绑定缩略图点击事件，点击显示大图 */
    var thumbs = listEl.querySelectorAll(".templates-settings-item-thumb");
    for (var k = 0; k < thumbs.length; k++) {
      thumbs[k].addEventListener("click", function (evt) {
        var url = evt.currentTarget.getAttribute("data-cover-url");
        if (url) _showTemplateCoverPreview(url);
      });
    }

    /* 更新提示信息 */
    var totalCount = templateAllItems.length;
    var filteredCount = items.length;
    var catCount = templateCategories.length;
    if (hintEl) {
      if (templateFilterKey) {
        hintEl.textContent = "筛选结果: " + filteredCount + " 个模板（共 " + totalCount + " 个，" + catCount + " 个分类）";
      } else {
        hintEl.textContent = "共 " + totalCount + " 个模板，" + catCount + " 个分类";
      }
    }
  }

  /**
   * 显示模板封面大图预览弹窗
   */
  function _showTemplateCoverPreview(imageUrl) {
    if (!imageUrl) return;
    var overlay = document.createElement("div");
    overlay.className = "template-cover-preview-overlay";
    overlay.innerHTML =
      '<div class="template-cover-preview-box">' +
      '<img src="' + imageUrl.replace(/"/g, "&quot;") + '" alt="封面预览">' +
      '</div>';
    document.body.appendChild(overlay);

    /* 点击遮罩或图片关闭 */
    overlay.addEventListener("click", function () {
      if (overlay.parentNode) {
        overlay.parentNode.removeChild(overlay);
      }
    });
    /* 按 ESC 关闭 */
    var escHandler = function (e) {
      if (e.key === "Escape" && overlay.parentNode) {
        overlay.parentNode.removeChild(overlay);
        document.removeEventListener("keydown", escHandler);
      }
    };
    document.addEventListener("keydown", escHandler);
  }

  /* ---- Markdown prompt 卡片加载与渲染 ---- */

  function loadPromptContents() {
    for (var i = 0; i < promptFiles.length; i++) {
      loadSinglePromptContent(promptFiles[i]);
    }
  }

  function loadSinglePromptContent(filename) {
    var bodyEl = document.getElementById("prompt-body-" + filename);
    if (!bodyEl) return;
    bodyEl.innerHTML = '<div class="prompt-card-loading">加载中…</div>';
    fetch(apiBase + "/api/desktop/prompt_content?file=" + encodeURIComponent(filename), {
      cache: "no-store",
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data && data.ok && data.content) {
          renderPromptContent(bodyEl, data.content);
        } else {
          bodyEl.innerHTML = '<div class="prompt-card-empty">暂无内容</div>';
        }
      })
      .catch(function (e) {
        bodyEl.innerHTML = '<div class="prompt-card-empty">加载失败: ' + (e.message || e) + '</div>';
      });
  }

  function renderPromptContent(containerEl, markdownText) {
    var html;
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
      try {
        html = DOMPurify.sanitize(marked.parse(markdownText));
      } catch (e) {
        html = escapeHtmlContent(markdownText);
      }
    } else {
      html = escapeHtmlContent(markdownText);
    }
    containerEl.innerHTML = '<div class="prompt-card-md">' + html + '</div>';
  }

  function escapeHtmlContent(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\n/g, "<br>");
  }

  function bindPromptCardToggles() {
    for (var i = 0; i < promptFiles.length; i++) {
      var filename = promptFiles[i];
      var toggleEl = document.getElementById("prompt-toggle-" + filename);
      var bodyEl = document.getElementById("prompt-body-" + filename);
      var rowEl = document.querySelector('.prompt-toggle-row[data-prompt="' + filename + '"]');
      if (!toggleEl || !bodyEl || !rowEl) continue;
      (function (toggle, body, row) {
        row.addEventListener("click", function () {
          var isHidden = body.classList.contains("hidden");
          body.classList.toggle("hidden", !isHidden);
          toggle.textContent = isHidden ? "▲" : "▼";
        });
      })(toggleEl, bodyEl, rowEl);
    }
  }

  /* ---- MCP 服务及工具说明加载与渲染 ---- */

  function loadMcpServicesConfig() {
    if (!mcpServicesBody) return;
    mcpServicesBody.innerHTML = '<div class="prompt-card-loading">加载中…</div>';
    fetch(apiBase + "/api/desktop/mcp_servers_config", { cache: "no-store" })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data && data.ok && data.config) {
          renderMcpServicesConfig(data.config);
        } else {
          mcpServicesBody.innerHTML = '<div class="prompt-card-empty">未发现 MCP 服务配置。</div>';
        }
      })
      .catch(function (e) {
        mcpServicesBody.innerHTML = '<div class="prompt-card-empty">加载失败: ' + (e.message || e) + '</div>';
      });
  }

  function renderMcpServicesConfig(servers) {
    if (!mcpServicesBody) return;
    if (!Array.isArray(servers) || !servers.length) {
      mcpServicesBody.innerHTML = '<div class="prompt-card-empty">未发现 MCP 服务配置。</div>';
      return;
    }
    var html = "";
    for (var i = 0; i < servers.length; i++) {
      var server = servers[i];
      var name = String(server.server_name || "未命名服务");
      var desc = String(server.server_description || "").trim();
      var isLoad = !!server.is_load;
      var tools = Array.isArray(server.tools) ? server.tools : [];
      var safeName = name.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      var safeDesc = desc
        ? desc.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        : "暂无描述";
      html +=
        '<div class="mcp-service-item">' +
        '<div class="mcp-service-header">' +
        '<div class="mcp-service-head-left">' +
        '<span class="mcp-service-name">' + safeName + '</span>' +
        '<span class="mcp-service-badge ' + (isLoad ? "is-enabled" : "is-disabled") + '">' +
        (isLoad ? "已启用" : "未启用") +
        '</span>' +
        '</div>' +
        '<span class="mcp-service-expand" data-service-idx="' + i + '">▶</span>' +
        '</div>' +
        '<p class="mcp-service-desc">' + safeDesc + '</p>' +
        '<div class="mcp-service-tools hidden" id="mcp-tools-' + i + '">' +
        '<div class="mcp-tools-title">工具列表（' + tools.length + '）</div>';
      for (var j = 0; j < tools.length; j++) {
        var tool = tools[j];
        var toolName = String(tool.tool_name || "未命名工具");
        var toolDesc = String(tool.tool_description || "").trim();
        var toolLoad = !!tool.is_load;
        var safeToolName = toolName.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        var safeToolDesc = toolDesc
          ? toolDesc.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").substring(0, 300)
          : "暂无描述";
        html +=
          '<div class="mcp-tool-item">' +
          '<div class="mcp-tool-head">' +
          '<span class="mcp-tool-name">' + safeToolName + '</span>' +
          '<span class="mcp-tool-badge ' + (toolLoad ? "is-enabled" : "is-disabled") + '">' +
          (toolLoad ? "启用" : "禁用") +
          '</span>' +
          '</div>' +
          '<div class="mcp-tool-desc">' + safeToolDesc + '</div>' +
          '</div>';
      }
      html += '</div></div>';
    }
    mcpServicesBody.innerHTML = html;

    /* 绑定展开/折叠事件 */
    var expandEls = mcpServicesBody.querySelectorAll(".mcp-service-expand");
    for (var k = 0; k < expandEls.length; k++) {
      (function (el, idx) {
        el.addEventListener("click", function () {
          var toolsEl = document.getElementById("mcp-tools-" + idx);
          if (!toolsEl) return;
          var isHidden = toolsEl.classList.contains("hidden");
          toolsEl.classList.toggle("hidden", !isHidden);
          el.textContent = isHidden ? "▼" : "▶";
        });
      })(expandEls[k], k);
    }
  }

  /* 绑定 MCP 服务刷新按钮 */
  if (mcpServicesRefresh) {
    mcpServicesRefresh.addEventListener("click", function () {
      loadMcpServicesConfig();
    });
  }

  /* ---- 微信聊天模式管理 ---- */

  function loadWechatModeContents() {
    var listEl = document.getElementById("wechat-mode-list");
    var countEl = document.getElementById("wechat-mode-count");
    if (!listEl) return;
    listEl.innerHTML = '<div class="prompt-card-loading">加载中…</div>';
    fetch(apiBase + "/api/desktop/wechat_mode_references", { cache: "no-store" })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data && data.ok && Array.isArray(data.files)) {
          renderWechatModeList(data.files);
        } else {
          listEl.innerHTML = '<div class="prompt-card-empty">加载失败</div>';
          if (countEl) countEl.textContent = "加载失败";
        }
      })
      .catch(function (e) {
        listEl.innerHTML = '<div class="prompt-card-empty">加载失败: ' + (e.message || e) + '</div>';
        if (countEl) countEl.textContent = "加载失败";
      });
  }

  function renderWechatModeList(files) {
    var listEl = document.getElementById("wechat-mode-list");
    var countEl = document.getElementById("wechat-mode-count");
    if (!listEl) return;
    if (!files.length) {
      listEl.innerHTML = '<div class="prompt-card-empty">暂无联系人对话模式文件</div>';
      if (countEl) countEl.textContent = "暂无联系人";
      return;
    }
    if (countEl) countEl.textContent = "共 " + files.length + " 个联系人";

    var html = "";
    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      var safeName = String(f.name).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      var safeFilename = String(f.filename).replace(/&/g, "&amp;");
      html +=
        '<div class="toggle-row prompt-toggle-row" data-mode-file="' + safeName + '">' +
        '<div>' +
        '<div class="toggle-title contact-title">💬 ' + safeName + '</div>' +
        '<div class="toggle-desc">' + safeFilename + ' — 点击展开查看详情</div>' +
        '</div>' +
        '<div class="mode-card-actions">' +
        '<button class="mode-btn-edit" data-action="edit" data-mode-file="' + safeName + '">✏️ 编辑</button>' +
        '<span class="prompt-card-toggle">▼</span>' +
        '</div>' +
        '</div>' +
        '<div class="prompt-card-body hidden" id="mode-body-' + safeName + '">' +
        '<div class="mode-preview" id="mode-preview-' + safeName + '"></div>' +
        '<div class="mode-editor hidden" id="mode-editor-' + safeName + '">' +
        '<textarea class="mode-textarea" id="mode-textarea-' + safeName + '"></textarea>' +
        '<div class="mode-editor-actions">' +
        '<button class="mode-btn-save" data-action="save" data-mode-file="' + safeName + '">💾 保存</button>' +
        '<button class="mode-btn-cancel" data-action="cancel" data-mode-file="' + safeName + '">取消</button>' +
        '</div>' +
        '</div>' +
        '</div>';
    }
    listEl.innerHTML = html;

    /* 用文件内容渲染预览 */
    for (var j = 0; j < files.length; j++) {
      var f2 = files[j];
      var previewEl = document.getElementById("mode-preview-" + f2.name);
      if (previewEl) {
        renderPromptContent(previewEl, f2.content);
      }
      /* 把原始内容存到 textarea */
      var textareaEl = document.getElementById("mode-textarea-" + f2.name);
      if (textareaEl) {
        textareaEl.value = f2.content;
      }
    }

    bindWechatModeToggles();
    bindWechatModeEditButtons(files);
  }

  function bindWechatModeToggles() {
    var rows = document.querySelectorAll(".prompt-toggle-row[data-mode-file]");
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var fileName = row.getAttribute("data-mode-file");
      var bodyEl = document.getElementById("mode-body-" + fileName);
      var toggleEl = row.querySelector(".prompt-card-toggle");
      if (!bodyEl || !toggleEl) continue;
      (function (r, body, toggle, fname) {
        r.addEventListener("click", function (e) {
          /* 编辑按钮点击不触发折叠 */
          if (e.target && e.target.getAttribute && e.target.getAttribute("data-action")) return;
          var isHidden = body.classList.contains("hidden");
          body.classList.toggle("hidden", !isHidden);
          toggle.textContent = isHidden ? "▲" : "▼";
        });
      })(row, bodyEl, toggleEl, fileName);
    }
  }

  function bindWechatModeEditButtons(files) {
    var listEl = document.getElementById("wechat-mode-list");
    if (!listEl) return;
    var fileMap = {};
    for (var i = 0; i < files.length; i++) {
      fileMap[files[i].name] = files[i];
    }

    listEl.addEventListener("click", function (e) {
      var target = e.target;
      if (!target || !target.getAttribute) return;
      var action = target.getAttribute("data-action");
      var fileName = target.getAttribute("data-mode-file");
      if (!action || !fileName) return;

      var previewEl = document.getElementById("mode-preview-" + fileName);
      var editorEl = document.getElementById("mode-editor-" + fileName);
      var textareaEl = document.getElementById("mode-textarea-" + fileName);
      var bodyEl = document.getElementById("mode-body-" + fileName);

      if (action === "edit") {
        if (!previewEl || !editorEl || !bodyEl) return;
        /* 确保卡片展开 */
        bodyEl.classList.remove("hidden");
        var toggleEl = listEl.querySelector('.prompt-toggle-row[data-mode-file="' + fileName + '"] .prompt-card-toggle');
        if (toggleEl) toggleEl.textContent = "▲";
        /* 切换到编辑模式 */
        previewEl.classList.add("hidden");
        editorEl.classList.remove("hidden");
        if (textareaEl) textareaEl.focus();
      } else if (action === "save") {
        if (!previewEl || !editorEl || !textareaEl) return;
        var newContent = textareaEl.value;
        var fInfo = fileMap[fileName];
        var filename = fInfo ? fInfo.filename : (fileName + ".md");
        fetch(apiBase + "/api/desktop/wechat_mode_reference_save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: filename, content: newContent }),
          cache: "no-store",
        })
          .then(function (res) { return res.json(); })
          .then(function (data) {
            if (data && data.ok) {
              /* 更新预览 */
              renderPromptContent(previewEl, newContent);
              fileMap[fileName] = { name: fileName, filename: filename, content: newContent };
              editorEl.classList.add("hidden");
              previewEl.classList.remove("hidden");
            } else {
              alert("保存失败: " + (data ? data.message : "未知错误"));
            }
          })
          .catch(function (err) {
            alert("保存失败: " + (err.message || err));
          });
      } else if (action === "cancel") {
        if (!previewEl || !editorEl || !textareaEl) return;
        editorEl.classList.add("hidden");
        previewEl.classList.remove("hidden");
      }
    });
  }

  async function checkWxworkConnectionStatus() {
    if (typeof window._checkWxworkConnectionStatus === "function") {
      await window._checkWxworkConnectionStatus();
    }
  }

  return {
    openSettings: openSettings,
    closeSettings: closeSettings,
    syncConfigToForm: syncConfigToForm,
    switchSettingsPanel: switchSettingsPanel,
    bindPrefInputs: bindPrefInputs,
    bindSettingsModal: bindSettingsModal,
    bindConfigForm: bindConfigForm,
    bindReadAllowedDirs: bindReadAllowedDirs,
    loadReadAllowedDirs: loadReadAllowedDirs,
    bindUserPrefInputs: bindUserPrefInputs,
    bindPrefBatchIcon: bindPrefBatchIcon,
    refreshSkillsSettingsList: loadSkillsSettingsList,
  };
}

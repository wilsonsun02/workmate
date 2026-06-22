/**
 * 桌面端定时任务：列表、历史、快捷模板，对接 /scheduler API。
 */

import { showToast } from "./toast.js";
import { suppressSchedulerFeedToastForExecution } from "./scheduler_toast_dedupe.js";

var TASK_QUICK_TEMPLATES = [
  "设置每日「8:00」的自动定时任务，根据我的星座「双子座」提供今日的行动注意指引发送给我",
  "提醒我喝水，在「每日 10:00」执行，从「今天」开始并「持续生效」，任务创建后设置为「立即启用」",
  "设置「每天」为我推送当天最新的「10条」科技新闻，每条新闻总结要精简。",
];

function truncate(s, maxLen) {
  var t = String(s != null ? s : "").trim();
  if (!t) return "";
  if (t.length <= maxLen) return t;
  return t.slice(0, maxLen) + "…";
}

function executionStatusZh(code) {
  var c = String(code || "").toLowerCase();
  if (c === "success") return "成功";
  if (c === "failed") return "失败";
  if (c === "running") return "运行中";
  return String(code || "—");
}

function taskStatusZh(code) {
  var c = String(code || "").toLowerCase();
  if (c === "active") return "已启用";
  if (c === "paused") return "已暂停";
  if (c === "completed") return "已完成";
  if (c === "failed") return "失败";
  return String(code || "—");
}

export function createTasksController(options) {
  var apiBase = String(options.apiBase || "").replace(/\/$/, "");
  var getUsername = options.getUsername;
  var root = options.tasksRootEl;
  var switchToChat = options.switchToChat;
  var startConversationWithMessage = options.startConversationWithMessage;

  var state = {
    tab: "list",
    tasks: [],
    executions: [],
    historyFilters: { taskId: "", status: "", date: "" },
  };
  var docClickBound = false;
  var batchDeleteMode = false;
  var batchSelectedTaskIds = {};
  var histCalView = {
    y: new Date().getFullYear(),
    m: new Date().getMonth(),
  };

  function pad2(n) {
    return String(n < 10 ? "0" + n : n);
  }

  function username() {
    return (getUsername && getUsername()) || "";
  }

  async function fetchJson(url, init) {
    var res = await fetch(url, init || { cache: "no-store" });
    var data = null;
    try {
      data = await res.json();
    } catch (_e) {
      data = null;
    }
    if (!res.ok) {
      var detail = data && data.detail ? data.detail : res.statusText;
      throw new Error(String(res.status) + (detail ? ": " + detail : ""));
    }
    return data;
  }

  async function loadTasks() {
    var user = username();
    if (!user) {
      state.tasks = [];
      return;
    }
    var data = await fetchJson(
      apiBase + "/scheduler/tasks?username=" + encodeURIComponent(user)
    );
    state.tasks = data && data.success && Array.isArray(data.tasks) ? data.tasks : [];
  }

  async function loadExecutions() {
    var user = username();
    if (!user) {
      state.executions = [];
      return;
    }
    var q =
      "?username=" +
      encodeURIComponent(user) +
      "&limit=200";
    if (state.historyFilters.taskId) {
      q += "&task_id=" + encodeURIComponent(state.historyFilters.taskId);
    }
    if (state.historyFilters.status) {
      q += "&status=" + encodeURIComponent(state.historyFilters.status);
    }
    if (state.historyFilters.date) {
      var d = state.historyFilters.date;
      q += "&from_date=" + encodeURIComponent(d) + "&to_date=" + encodeURIComponent(d);
    }
    var data = await fetchJson(apiBase + "/scheduler/user_executions" + q);
    state.executions =
      data && data.success && Array.isArray(data.executions) ? data.executions : [];
  }

  async function pauseTask(taskId) {
    var user = username();
    await fetchJson(
      apiBase +
        "/scheduler/tasks/" +
        encodeURIComponent(taskId) +
        "/pause?username=" +
        encodeURIComponent(user),
      { method: "POST" }
    );
  }

  async function resumeTask(taskId) {
    var user = username();
    await fetchJson(
      apiBase +
        "/scheduler/tasks/" +
        encodeURIComponent(taskId) +
        "/resume?username=" +
        encodeURIComponent(user),
      { method: "POST" }
    );
  }

  async function deleteTask(taskId) {
    var user = username();
    await fetchJson(
      apiBase +
        "/scheduler/tasks/" +
        encodeURIComponent(taskId) +
        "?username=" +
        encodeURIComponent(user),
      { method: "DELETE" }
    );
  }

  async function runTaskNow(taskId) {
    var user = username();
    var url =
      apiBase +
      "/scheduler/tasks/" +
      encodeURIComponent(taskId) +
      "/run?username=" +
      encodeURIComponent(user);
    var res = await fetch(url, { method: "POST", cache: "no-store" });
    var data = null;
    try {
      data = await res.json();
    } catch (_e) {
      data = null;
    }
    if (!res.ok) {
      var detail =
        data && data.error != null
          ? data.error
          : data && data.detail != null
            ? data.detail
            : res.statusText;
      var err = new Error(String(res.status) + (detail ? ": " + detail : ""));
      if (data && data.execution_id) err.executionId = data.execution_id;
      throw err;
    }
    return data;
  }

  async function cancelExecutionRecord(executionId) {
    var user = username();
    return fetchJson(
      apiBase +
        "/scheduler/executions/" +
        encodeURIComponent(executionId) +
        "/cancel?username=" +
        encodeURIComponent(user),
      { method: "POST" }
    );
  }

  async function deleteUserExecutionsApi(body) {
    return fetchJson(apiBase + "/scheduler/user_executions/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function renderHero() {
    var pills = TASK_QUICK_TEMPLATES.map(function (text, idx) {
      return (
        '<button type="button" class="task-template-pill" data-template-index="' +
        idx +
        '">' +
        truncate(text, 120) +
        " →</button>"
      );
    }).join("");
    return (
      '<div class="tasks-hero">' +
      '<div class="tasks-hero-icon" aria-hidden="true">⏰</div>' +
      "<h2 class=\"tasks-hero-title\">选择下方对话，开启你的第一个任务吧</h2>" +
      '<div class="task-template-pills">' +
      pills +
      "</div>" +
      "</div>"
    );
  }

  /** 仅在没有任务时展示推荐区（已登录且无定时任务） */
  function renderHeroIfEmpty() {
    if (!username() || state.tasks.length > 0) return "";
    return renderHero();
  }

  function renderTaskCard(task) {
    var title = task.task_name || task.task_id || "未命名任务";
    var desc =
      task.task_description || task.task_prompt || task.cron_expression || "";
    var cronLabel = task.cron_human || task.cron_expression || "—";
    var st = task.status || "";
    var canToggle = st === "active" || st === "paused";
    var switchOn = st === "active";
    var switchDisabled = !canToggle ? " disabled" : "";
    var checkedAttr = switchOn ? " checked" : "";
    var batchClass = batchDeleteMode ? " batch-mode" : "";
    var batchChecked = batchSelectedTaskIds[task.task_id] ? " checked" : "";

    return (
      '<article class="task-card' + batchClass + '" data-task-id="' +
      escapeHtml(task.task_id) +
      '">' +
      (batchDeleteMode
        ? '<input type="checkbox" class="task-checkbox task-batch-select" data-task-id="' +
          escapeHtml(task.task_id) +
          '"' +
          batchChecked +
          ' />'
        : ""
      ) +
      '<div class="task-card-main">' +
      '<div class="task-card-icon" aria-hidden="true">⏰</div>' +
      '<div class="task-card-body">' +
      '<div class="task-card-title-row">' +
      "<h3 class=\"task-card-title\">" +
      escapeHtml(title) +
      "</h3>" +
      '<label class="task-switch">' +
      '<input type="checkbox" class="task-switch-input"' +
      checkedAttr +
      switchDisabled +
      ' data-action="toggle" />' +
      '<span class="task-switch-slider"></span>' +
      "</label>" +
      "</div>" +
      '<p class="task-card-desc">' +
      escapeHtml(truncate(desc, 180)) +
      "</p>" +
      '<div class="task-card-meta">' +
      '<span class="task-card-meta-item">' +
      escapeHtml(cronLabel) +
      "</span>" +
      '<span class="task-card-meta-status">' +
      escapeHtml(taskStatusZh(st)) +
      "</span>" +
      "</div>" +
      "</div>" +
      '<div class="task-card-menu-wrap">' +
      '<button type="button" class="task-card-more" data-action="menu" aria-label="更多">⋯</button>' +
      '<div class="task-card-dropdown hidden">' +
      '<button type="button" data-action="run">立即执行</button>' +
      '<button type="button" data-action="delete">删除</button>' +
      "</div>" +
      "</div>" +
      "</div>" +
      "</article>"
    );
  }

  function escapeHtml(s) {
    return String(s != null ? s : "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderTaskList() {
    if (!username()) {
      return '<p class="tasks-hint">请先登录后管理定时任务。</p>';
    }
    var html = "";
    if (!state.tasks.length) {
      html += '<p class="tasks-empty-list">暂无定时任务，可使用上方模板快速创建。</p>';
    } else {
      html += state.tasks.map(renderTaskCard).join("");
    }
    return html;
  }

  function renderHistoryRow(ex) {
    var summary = truncate(ex.result_summary || "", 120);
    var err = ex.error_message ? truncate(ex.error_message, 200) : "";
    var st = String(ex.status || "").toLowerCase();
    var stopBtn =
      st === "running"
        ? '<button type="button" class="exec-stop-btn" data-execution-id="' +
          escapeHtml(ex.execution_id) +
          '" title="仅更新历史记录状态，用于清理服务重启后的「运行中」残留">停止</button>'
        : "";
    var endTimeDisplay = ex.end_time
      ? '<span class="exec-time exec-end-time">结束：' + escapeHtml(ex.end_time) + "</span>"
      : "";
    return (
      '<div class="exec-row" data-execution-id="' +
      escapeHtml(ex.execution_id) +
      '">' +
      '<div class="exec-row-head">' +
      '<label class="exec-row-check" title="选择">' +
      '<input type="checkbox" class="exec-select-cb" data-execution-id="' +
      escapeHtml(ex.execution_id) +
      '" />' +
      "</label>" +
      '<span class="exec-badge exec-badge-' +
      escapeHtml(st) +
      '">' +
      escapeHtml(executionStatusZh(ex.status)) +
      "</span>" +
      '<div class="exec-row-meta">' +
      '<span class="exec-time">开始：' +
      escapeHtml(ex.start_time || "") +
      "</span>" +
      endTimeDisplay +
      stopBtn +
      "</div>" +
      "</div>" +
      '<div class="exec-task-id">' +
      escapeHtml(ex.task_id || "") +
      "</div>" +
      (summary ? '<div class="exec-summary">' + escapeHtml(summary) + "</div>" : "") +
      (err
        ? '<details class="exec-error-details"><summary>查看错误</summary><pre class="exec-error-pre">' +
          escapeHtml(err) +
          "</pre></details>"
        : "") +
      "</div>"
    );
  }

  function renderHistory() {
    if (!username()) {
      return '<p class="tasks-hint">请先登录后查看执行历史。</p>';
    }
    if (!state.executions.length) {
      return (
        '<div class="tasks-history-empty">' +
        "<p>暂无执行历史</p>" +
        "<p class=\"tasks-history-empty-sub\">定时任务执行后将在此处显示历史记录</p>" +
        "</div>"
      );
    }
    return state.executions.map(renderHistoryRow).join("");
  }

  function renderHistoryToolbar() {
    if (!username()) return "";
    return (
      '<div class="tasks-history-toolbar">' +
      '<label class="hist-toolbar-select-all">' +
      '<input type="checkbox" id="hist-select-all" />' +
      "<span>全选本页</span></label>" +
      '<button type="button" class="btn-ghost-sm" id="hist-delete-selected">删除所选</button>' +
      '<button type="button" class="btn-ghost-sm hist-btn-danger" id="hist-clear-filtered">' +
      "清空当前筛选" +
      "</button>" +
      '<span class="hist-toolbar-hint">「清空」按上方任务/状态/日期条件删除库中全部匹配记录（条件全空则删除您的全部执行历史）。</span>' +
      "</div>"
    );
  }

  function renderFilters() {
    var taskItems =
      '<button type="button" class="tasks-dd-item" data-value="" role="option">全部任务</button>' +
      state.tasks
        .map(function (t) {
          return (
            '<button type="button" class="tasks-dd-item" data-value="' +
            escapeHtml(t.task_id) +
            '" role="option">' +
            escapeHtml(truncate(t.task_name || t.task_id, 48)) +
            "</button>"
          );
        })
        .join("");
    return (
      '<div class="tasks-filters">' +
      '<div class="tasks-dd tasks-dd-task">' +
      '<input type="hidden" id="hist-filter-task" value="" />' +
      '<button type="button" class="tasks-dd-trigger" aria-expanded="false" aria-haspopup="listbox">' +
      '<span class="tasks-dd-label">全部任务</span>' +
      '<span class="tasks-dd-chevron" aria-hidden="true">▾</span>' +
      "</button>" +
      '<div class="tasks-dd-menu hidden" role="listbox">' +
      taskItems +
      "</div>" +
      "</div>" +
      '<div class="tasks-dd tasks-dd-status">' +
      '<input type="hidden" id="hist-filter-status" value="" />' +
      '<button type="button" class="tasks-dd-trigger" aria-expanded="false" aria-haspopup="listbox">' +
      '<span class="tasks-dd-label">全部状态</span>' +
      '<span class="tasks-dd-chevron" aria-hidden="true">▾</span>' +
      "</button>" +
      '<div class="tasks-dd-menu hidden" role="listbox">' +
      '<button type="button" class="tasks-dd-item" data-value="" role="option">全部状态</button>' +
      '<button type="button" class="tasks-dd-item" data-value="success" role="option">成功</button>' +
      '<button type="button" class="tasks-dd-item" data-value="failed" role="option">失败</button>' +
      '<button type="button" class="tasks-dd-item" data-value="running" role="option">运行中</button>' +
      "</div>" +
      "</div>" +
      '<div class="hist-date-field">' +
      '<input type="hidden" id="hist-filter-date" value="" />' +
      '<button type="button" class="hist-date-trigger" id="hist-date-trigger" aria-haspopup="dialog" aria-expanded="false">' +
      '<span class="hist-date-trigger-icon" aria-hidden="true">📅</span>' +
      '<span id="hist-date-trigger-label">选择日期</span>' +
      "</button>" +
      '<button type="button" class="hist-date-clear btn-ghost-sm hidden" id="hist-date-clear">清除</button>' +
      '<div class="hist-cal-popover hidden" id="hist-cal-popover" role="dialog" aria-label="日历">' +
      '<div class="hist-cal-header">' +
      '<button type="button" class="hist-cal-nav" id="hist-cal-prev" aria-label="上月">‹</button>' +
      '<span id="hist-cal-caption" class="hist-cal-caption"></span>' +
      '<button type="button" class="hist-cal-nav" id="hist-cal-next" aria-label="下月">›</button>' +
      "</div>" +
      '<div class="hist-cal-weekdays">' +
      "<span>日</span><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span>" +
      "</div>" +
      '<div id="hist-cal-grid" class="hist-cal-grid"></div>' +
      "</div>" +
      "</div>" +
      '<button type="button" class="tasks-filter-apply" id="hist-apply-filter">筛选</button>' +
      "</div>"
    );
  }

  function fullRender() {
    if (!root) return;
    var listClass = state.tab === "list" ? " active" : "";
    var histClass = state.tab === "history" ? " active" : "";
    root.innerHTML =
      '<div class="tasks-inner">' +
      '<div class="tasks-tabs' + (batchDeleteMode ? ' batch-mode' : '') + '">' +
      '<button type="button" class="tasks-tab' +
      listClass +
      '" data-tab="list">任务列表</button>' +
      '<span class="tasks-batch-slot" id="tasks-batch-slot"></span>' +
      (username() ? '<button type="button" class="batch-icon-btn' + (batchDeleteMode ? ' is-active' : '') + '" id="tasks-batch-icon-btn" title="批量管理">✓</button>' : '') +
      '<button type="button" class="tasks-tab' +
      histClass +
      '" data-tab="history">历史任务</button>' +
      "</div>" +
      '<div id="tasks-tab-list" class="tasks-tab-panel' +
      (state.tab === "list" ? "" : " hidden") +
      '">' +
      renderHeroIfEmpty() +
      '<div class="tasks-list-wrap">' +
      renderTaskList() +
      "</div>" +
      "</div>" +
      '<div id="tasks-tab-history" class="tasks-tab-panel' +
      (state.tab === "history" ? "" : " hidden") +
      '">' +
      renderFilters() +
      (state.tab === "history" ? renderHistoryToolbar() : "") +
      '<div class="tasks-history-list">' +
      renderHistory() +
      "</div>" +
      "</div>" +
      "</div>";
    /* 填充任务标签行的批量操作内联控件 */
    if (batchDeleteMode) {
      fillTasksBatchSlot();
    }
    bind();
  }

  function fillTasksBatchSlot() {
    var slot = document.getElementById("tasks-batch-slot");
    if (!slot) return;
    var selectedCount = state.tasks.filter(function (t) { return batchSelectedTaskIds[t.task_id]; }).length;
    slot.innerHTML =
      '<span class="batch-info-inline">' +
      (selectedCount > 0 ? "已选" + selectedCount : "") +
      "</span>" +
      '<button type="button" class="batch-sm-btn" id="tasks-batch-select-all">全选</button>' +
      '<button type="button" class="batch-sm-btn" id="tasks-batch-cancel">取消</button>' +
      '<button type="button" class="batch-sm-btn batch-sm-del" id="tasks-batch-delete"' +
      (selectedCount === 0 ? " disabled" : "") +
      ">删除</button>";
  }

  function closeAllMenus() {
    if (!root) return;
    root.querySelectorAll(".task-card-dropdown").forEach(function (el) {
      el.classList.add("hidden");
    });
  }

  function closeHistCal() {
    if (!root) return;
    var pop = root.querySelector("#hist-cal-popover");
    var trig = root.querySelector("#hist-date-trigger");
    if (pop) {
      pop.classList.add("hidden");
    }
    if (trig) {
      trig.setAttribute("aria-expanded", "false");
    }
  }

  function syncHistDateUI() {
    if (!root) return;
    var hidden = root.querySelector("#hist-filter-date");
    var label = root.querySelector("#hist-date-trigger-label");
    var clearBtn = root.querySelector("#hist-date-clear");
    var v = hidden && hidden.value ? hidden.value : "";
    if (label) {
      if (!v) {
        label.textContent = "选择日期";
      } else {
        var parts = v.split("-");
        if (parts.length === 3) {
          label.textContent =
            parseInt(parts[0], 10) +
            "年" +
            parseInt(parts[1], 10) +
            "月" +
            parseInt(parts[2], 10) +
            "日";
        } else {
          label.textContent = v;
        }
      }
    }
    if (clearBtn) {
      if (v) clearBtn.classList.remove("hidden");
      else clearBtn.classList.add("hidden");
    }
  }

  function renderHistCalGrid() {
    if (!root) return;
    var grid = root.querySelector("#hist-cal-grid");
    var cap = root.querySelector("#hist-cal-caption");
    var hidden = root.querySelector("#hist-filter-date");
    if (!grid || !cap) return;
    var y = histCalView.y;
    var m = histCalView.m;
    cap.textContent = y + "年" + (m + 1) + "月";
    var firstDow = new Date(y, m, 1).getDay();
    var daysInMonth = new Date(y, m + 1, 0).getDate();
    var selected = hidden && hidden.value ? hidden.value : "";
    var today = new Date();
    var html = "";
    var i;
    for (i = 0; i < firstDow; i++) {
      html += '<span class="hist-cal-cell hist-cal-pad"></span>';
    }
    for (var d = 1; d <= daysInMonth; d++) {
      var iso = y + "-" + pad2(m + 1) + "-" + pad2(d);
      var cl = "hist-cal-cell hist-cal-day";
      if (iso === selected) cl += " is-selected";
      if (
        y === today.getFullYear() &&
        m === today.getMonth() &&
        d === today.getDate()
      ) {
        cl += " is-today";
      }
      html +=
        '<button type="button" class="' +
        cl +
        '" data-iso="' +
        iso +
        '">' +
        d +
        "</button>";
    }
    grid.innerHTML = html;
    grid.querySelectorAll(".hist-cal-day").forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var iso = btn.getAttribute("data-iso");
        if (hidden) hidden.value = iso || "";
        syncHistDateUI();
        closeHistCal();
      });
    });
  }

  function openHistCal() {
    if (!root) return;
    var pop = root.querySelector("#hist-cal-popover");
    var trig = root.querySelector("#hist-date-trigger");
    var hidden = root.querySelector("#hist-filter-date");
    if (!pop) return;
    var v = hidden && hidden.value ? hidden.value : "";
    if (v) {
      var p = v.split("-");
      if (p.length === 3) {
        histCalView.y = parseInt(p[0], 10);
        histCalView.m = parseInt(p[1], 10) - 1;
      }
    } else {
      var now = new Date();
      histCalView.y = now.getFullYear();
      histCalView.m = now.getMonth();
    }
    pop.classList.remove("hidden");
    if (trig) trig.setAttribute("aria-expanded", "true");
    renderHistCalGrid();
  }

  function bindHistDatePicker() {
    if (!root) return;
    var trig = root.querySelector("#hist-date-trigger");
    var pop = root.querySelector("#hist-cal-popover");
    var clearBtn = root.querySelector("#hist-date-clear");
    var prev = root.querySelector("#hist-cal-prev");
    var next = root.querySelector("#hist-cal-next");
    if (!trig || !pop) return;

    trig.addEventListener("click", function (e) {
      e.stopPropagation();
      if (pop.classList.contains("hidden")) {
        openHistCal();
      } else {
        closeHistCal();
      }
    });

    if (prev) {
      prev.addEventListener("click", function (e) {
        e.stopPropagation();
        histCalView.m -= 1;
        if (histCalView.m < 0) {
          histCalView.m = 11;
          histCalView.y -= 1;
        }
        renderHistCalGrid();
      });
    }
    if (next) {
      next.addEventListener("click", function (e) {
        e.stopPropagation();
        histCalView.m += 1;
        if (histCalView.m > 11) {
          histCalView.m = 0;
          histCalView.y += 1;
        }
        renderHistCalGrid();
      });
    }

    pop.addEventListener("click", function (e) {
      e.stopPropagation();
    });

    if (clearBtn) {
      clearBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        var hidden = root.querySelector("#hist-filter-date");
        if (hidden) hidden.value = "";
        syncHistDateUI();
        closeHistCal();
      });
    }
  }

  function closeAllFilterDropdowns() {
    if (!root) return;
    root.querySelectorAll(".tasks-dd-menu").forEach(function (el) {
      el.classList.add("hidden");
    });
    root.querySelectorAll(".tasks-dd-trigger").forEach(function (el) {
      el.setAttribute("aria-expanded", "false");
      el.classList.remove("is-open");
    });
  }

  function syncFilterDropdownLabels() {
    if (!root) return;
    var taskHidden = root.querySelector("#hist-filter-task");
    var statHidden = root.querySelector("#hist-filter-status");
    var taskWrap = root.querySelector(".tasks-dd-task");
    var statWrap = root.querySelector(".tasks-dd-status");
    if (taskHidden && taskWrap) {
      var tv = taskHidden.value || "";
      var tlab = taskWrap.querySelector(".tasks-dd-label");
      var ttext = "全部任务";
      if (tv) {
        var found = null;
        for (var i = 0; i < state.tasks.length; i++) {
          if (state.tasks[i].task_id === tv) {
            found = state.tasks[i];
            break;
          }
        }
        ttext = found
          ? truncate(found.task_name || found.task_id, 36)
          : truncate(tv, 36);
      }
      if (tlab) tlab.textContent = ttext;
      taskWrap.querySelectorAll(".tasks-dd-item").forEach(function (item) {
        var v = item.getAttribute("data-value") || "";
        item.classList.toggle("is-selected", v === tv);
      });
    }
    if (statHidden && statWrap) {
      var sv = statHidden.value || "";
      var slab = statWrap.querySelector(".tasks-dd-label");
      var stMap = {
        "": "全部状态",
        success: "成功",
        failed: "失败",
        running: "运行中",
      };
      if (slab) slab.textContent = stMap[sv] != null ? stMap[sv] : sv || "全部状态";
      statWrap.querySelectorAll(".tasks-dd-item").forEach(function (item) {
        var v = item.getAttribute("data-value") || "";
        item.classList.toggle("is-selected", v === sv);
      });
    }
  }

  function bindFilterDropdowns() {
    if (!root) return;
    root.querySelectorAll(".tasks-dd").forEach(function (wrap) {
      var trig = wrap.querySelector(".tasks-dd-trigger");
      var menu = wrap.querySelector(".tasks-dd-menu");
      var hidden = wrap.querySelector('input[type="hidden"]');
      if (!trig || !menu || !hidden) return;

      trig.addEventListener("click", function (e) {
        e.stopPropagation();
        closeHistCal();
        var wasOpen = !menu.classList.contains("hidden");
        closeAllFilterDropdowns();
        if (!wasOpen) {
          menu.classList.remove("hidden");
          trig.setAttribute("aria-expanded", "true");
          trig.classList.add("is-open");
        }
      });

      menu.addEventListener("click", function (e) {
        e.stopPropagation();
      });

      menu.querySelectorAll(".tasks-dd-item").forEach(function (item) {
        item.addEventListener("click", function (e) {
          e.stopPropagation();
          var v = item.getAttribute("data-value");
          if (v === null) v = "";
          hidden.value = v;
          menu.querySelectorAll(".tasks-dd-item").forEach(function (x) {
            x.classList.toggle(
              "is-selected",
              (x.getAttribute("data-value") || "") === v
            );
          });
          var lab = wrap.querySelector(".tasks-dd-label");
          if (lab) lab.textContent = (item.textContent || "").trim();
          menu.classList.add("hidden");
          trig.setAttribute("aria-expanded", "false");
          trig.classList.remove("is-open");
        });
      });
    });
  }

  function bind() {
    if (!root) return;

    root.querySelectorAll(".tasks-tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var tab = btn.getAttribute("data-tab");
        if (!tab || tab === state.tab) return;
        state.tab = tab;
        if (tab === "history") {
          loadTasks()
            .then(function () {
              return loadExecutions();
            })
            .then(function () {
              fullRender();
            })
            .catch(function (e) {
              window.alert("加载历史失败：" + (e.message || e));
              fullRender();
            });
        } else {
          fullRender();
        }
      });
    });

    root.querySelectorAll(".task-template-pill").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var idx = parseInt(btn.getAttribute("data-template-index"), 10);
        var text = TASK_QUICK_TEMPLATES[idx];
        if (!text || !startConversationWithMessage) return;
        if (!username()) {
          window.alert("请先登录");
          return;
        }
        startConversationWithMessage(text, { autoSend: false }).then(function () {
          if (switchToChat) switchToChat();
        });
      });
    });

    root.querySelectorAll(".task-switch-input").forEach(function (inp) {
      inp.addEventListener("click", function (e) {
        e.stopPropagation();
      });
      inp.addEventListener("change", function () {
        var card = inp.closest(".task-card");
        if (!card) return;
        var taskId = card.getAttribute("data-task-id") || "";
        if (!taskId) return;
        var newVal = inp.checked;
        inp.disabled = true;
        var p = newVal ? resumeTask(taskId) : pauseTask(taskId);
        p.then(function () {
          return loadTasks();
        })
          .then(function () {
            fullRender();
          })
          .catch(function (err) {
            window.alert("操作失败：" + (err.message || err));
            inp.checked = !newVal;
          })
          .finally(function () {
            inp.disabled = false;
          });
      });
    });

    root.querySelectorAll(".task-card-more").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var wrap = btn.closest(".task-card-menu-wrap");
        if (!wrap) return;
        var dd = wrap.querySelector(".task-card-dropdown");
        if (!dd) return;
        var open = dd.classList.contains("hidden");
        closeAllMenus();
        if (open) dd.classList.remove("hidden");
      });
    });

    root.querySelectorAll('.task-card-dropdown [data-action="run"]').forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var card = btn.closest(".task-card");
        closeAllMenus();
        var taskId = card.getAttribute("data-task-id") || "";
        if (!taskId) return;
        showToast("任务已开始执行，完成后可在「历史任务」中查看记录…", {
          type: "info",
          duration: 4200,
        });
        runTaskNow(taskId)
          .then(function (data) {
            if (data && data.execution_id) {
              suppressSchedulerFeedToastForExecution(data.execution_id, 15000);
            }
            var tail =
              data && data.execution_id
                ? " 记录：" + data.execution_id
                : "";
            showToast("执行已完成。" + tail, { type: "success", duration: 5000 });
          })
          .catch(function (err) {
            if (err && err.executionId) {
              suppressSchedulerFeedToastForExecution(err.executionId, 15000);
            }
            showToast("执行失败：" + (err.message || err), {
              type: "error",
              duration: 6000,
            });
          })
          .finally(function () {
            closeAllMenus();
          });
      });
    });

    root.querySelectorAll(".exec-stop-btn").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var id = btn.getAttribute("data-execution-id") || "";
        if (!id) return;
        if (
          !window.confirm(
            "将该条记录标记为「已停止」？用于清理服务重启后仍显示「运行中」的遗留状态（无法在界面真正终止后台进程）。"
          )
        ) {
          return;
        }
        btn.disabled = true;
        cancelExecutionRecord(id)
          .then(function () {
            showToast("已更新该条执行记录。", { type: "success", duration: 3200 });
            return loadExecutions();
          })
          .then(function () {
            fullRender();
          })
          .catch(function (err) {
            showToast("操作失败：" + (err.message || err), {
              type: "error",
              duration: 5000,
            });
            btn.disabled = false;
          });
      });
    });

    root.querySelectorAll(".exec-row-check").forEach(function (lab) {
      lab.addEventListener("click", function (e) {
        e.stopPropagation();
      });
    });

    var selAll = root.querySelector("#hist-select-all");
    if (selAll) {
      selAll.addEventListener("change", function () {
        var on = selAll.checked;
        root.querySelectorAll(".exec-select-cb").forEach(function (cb) {
          cb.checked = on;
        });
      });
    }

    var delSel = root.querySelector("#hist-delete-selected");
    if (delSel) {
      delSel.addEventListener("click", function () {
        var ids = [];
        root.querySelectorAll(".exec-select-cb:checked").forEach(function (cb) {
          var id = cb.getAttribute("data-execution-id");
          if (id) ids.push(id);
        });
        if (!ids.length) {
          showToast("请先勾选要删除的记录", { type: "info", duration: 3200 });
          return;
        }
        if (
          !window.confirm(
            "确定删除已选的 " + ids.length + " 条执行记录？此操作不可恢复。"
          )
        ) {
          return;
        }
        deleteUserExecutionsApi({ username: username(), execution_ids: ids })
          .then(function (data) {
            var n = data && typeof data.deleted === "number" ? data.deleted : ids.length;
            showToast("已删除 " + n + " 条记录。", { type: "success", duration: 3200 });
            return loadExecutions();
          })
          .then(function () {
            fullRender();
          })
          .catch(function (err) {
            showToast("删除失败：" + (err.message || err), {
              type: "error",
              duration: 5000,
            });
          });
      });
    }

    var clrFilt = root.querySelector("#hist-clear-filtered");
    if (clrFilt) {
      clrFilt.addEventListener("click", function () {
        var ft = root.querySelector("#hist-filter-task");
        var fs = root.querySelector("#hist-filter-status");
        var fd = root.querySelector("#hist-filter-date");
        var tid = ft && ft.value ? ft.value.trim() : "";
        var st = fs && fs.value ? fs.value.trim() : "";
        var d = fd && fd.value ? fd.value.trim() : "";
        var body = { username: username() };
        if (tid) body.task_id = tid;
        if (st) body.status = st;
        if (d) {
          body.from_date = d;
          body.to_date = d;
        }
        var msg =
          "将删除符合当前任务/状态/日期筛选的全部执行记录（数据库中所有匹配项，不限本页显示的条数）。确定吗？";
        if (!tid && !st && !d) {
          msg =
            "当前未设置筛选条件，将删除您账号下的全部执行历史。此操作不可恢复，确定吗？";
        }
        if (!window.confirm(msg)) return;
        deleteUserExecutionsApi(body)
          .then(function (data) {
            var n = data && typeof data.deleted === "number" ? data.deleted : 0;
            showToast("已删除 " + n + " 条记录。", { type: "success", duration: 3600 });
            return loadExecutions();
          })
          .then(function () {
            fullRender();
          })
          .catch(function (err) {
            showToast("清空失败：" + (err.message || err), {
              type: "error",
              duration: 5000,
            });
          });
      });
    }

    root.querySelectorAll('.task-card-dropdown [data-action="delete"]').forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var card = btn.closest(".task-card");
        closeAllMenus();
        var taskId = card.getAttribute("data-task-id") || "";
        if (!taskId) return;
        if (!window.confirm("确定删除该定时任务？")) return;
        deleteTask(taskId)
          .then(function () {
            return loadTasks();
          })
          .then(function () {
            fullRender();
          })
          .catch(function (err) {
            window.alert("删除失败：" + (err.message || err));
          });
      });
    });

    var apply = root.querySelector("#hist-apply-filter");
    if (apply) {
      apply.addEventListener("click", function () {
        var ft = root.querySelector("#hist-filter-task");
        var fs = root.querySelector("#hist-filter-status");
        var fd = root.querySelector("#hist-filter-date");
        state.historyFilters.taskId = ft && ft.value ? ft.value : "";
        state.historyFilters.status = fs && fs.value ? fs.value : "";
        state.historyFilters.date = fd && fd.value ? fd.value : "";
        loadExecutions()
          .then(function () {
            fullRender();
          })
          .catch(function (e) {
            window.alert("加载历史失败：" + (e.message || e));
          });
      });
    }

    var hft = root.querySelector("#hist-filter-task");
    if (hft) hft.value = state.historyFilters.taskId != null ? state.historyFilters.taskId : "";
    var hfs = root.querySelector("#hist-filter-status");
    if (hfs) hfs.value = state.historyFilters.status != null ? state.historyFilters.status : "";
    var hfd = root.querySelector("#hist-filter-date");
    if (hfd) hfd.value = state.historyFilters.date != null ? state.historyFilters.date : "";
    syncFilterDropdownLabels();
    bindHistDatePicker();
    bindFilterDropdowns();

    if (!docClickBound) {
      docClickBound = true;
      document.addEventListener("click", function (ev) {
        closeAllMenus();
        if (root && !ev.target.closest(".hist-date-field")) {
          closeHistCal();
        }
        if (!ev.target.closest(".tasks-dd")) {
          closeAllFilterDropdowns();
        }
      });
    }

    /* ---- 批量删除 ---- */

    var batchIcon = root.querySelector("#tasks-batch-icon-btn");
    if (batchIcon) {
      batchIcon.addEventListener("click", function () {
        batchDeleteMode = !batchDeleteMode;
        batchSelectedTaskIds = {};
        fullRender();
      });
    }

    root.querySelectorAll(".task-batch-select").forEach(function (cb) {
      cb.addEventListener("click", function (e) {
        e.stopPropagation();
        var taskId = cb.getAttribute("data-task-id");
        if (batchSelectedTaskIds[taskId]) {
          delete batchSelectedTaskIds[taskId];
        } else {
          batchSelectedTaskIds[taskId] = true;
        }
        fullRender();
      });
    });

    var batchSelectAll = root.querySelector("#tasks-batch-select-all");
    if (batchSelectAll) {
      batchSelectAll.addEventListener("click", function () {
        var allSelected = state.tasks.every(function (t) { return batchSelectedTaskIds[t.task_id]; });
        if (allSelected) {
          state.tasks.forEach(function (t) { delete batchSelectedTaskIds[t.task_id]; });
        } else {
          state.tasks.forEach(function (t) { batchSelectedTaskIds[t.task_id] = true; });
        }
        fullRender();
      });
    }

    var batchCancel = root.querySelector("#tasks-batch-cancel");
    if (batchCancel) {
      batchCancel.addEventListener("click", function () {
        batchDeleteMode = false;
        batchSelectedTaskIds = {};
        fullRender();
      });
    }

    var batchDelete = root.querySelector("#tasks-batch-delete");
    if (batchDelete) {
      batchDelete.addEventListener("click", function () {
        var selectedIds = Object.keys(batchSelectedTaskIds).filter(function (id) { return batchSelectedTaskIds[id]; });
        if (!selectedIds.length) return;
        if (!window.confirm("确定删除选中的 " + selectedIds.length + " 个定时任务？")) return;
        var errors = [];
        var done = 0;
        selectedIds.forEach(function (taskId) {
          deleteTask(taskId)
            .then(function () {
              delete batchSelectedTaskIds[taskId];
            })
            .catch(function (err) {
              errors.push(err.message || err);
            })
            .finally(function () {
              done += 1;
              if (done >= selectedIds.length) {
                batchDeleteMode = false;
                batchSelectedTaskIds = {};
                loadTasks().then(function () { fullRender(); });
                if (errors.length) {
                  window.alert("部分删除失败: " + errors.join("; "));
                }
              }
            });
        });
      });
    }
  }

  function mount() {
    state.tab = "list";
    fullRender();
    if (!username()) return Promise.resolve();
    return loadTasks()
      .then(function () {
        fullRender();
      })
      .catch(function (e) {
        window.alert("加载任务失败：" + (e.message || e));
      });
  }

  function refresh() {
    if (!username()) {
      fullRender();
      return Promise.resolve();
    }
    return loadTasks()
      .then(function () {
        if (state.tab === "history") {
          return loadExecutions();
        }
      })
      .then(function () {
        fullRender();
      })
      .catch(function (e) {
        window.alert("刷新失败：" + (e.message || e));
      });
  }

  return {
    mount: mount,
    refresh: refresh,
  };
}

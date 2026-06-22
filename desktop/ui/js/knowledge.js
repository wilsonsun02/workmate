/**
 * 桌面端知识库：分类管理、文件管理，对接 /knowledge API。
 */
import { showToast } from "./toast.js";
import { assistantMarkdownToHtml } from "./markdown.js?v=2026052814";
import { getSession } from "./storage.js";

var PAGE_SIZE = 10;
var SUMMARY_MAX_CHARS = 300;

function currentUsername() {
  var sess = getSession();
  if (sess && sess.user && sess.user.username) return sess.user.username;
  return "";
}

function usernameParam() {
  var u = currentUsername();
  return u ? "&username=" + encodeURIComponent(u) : "";
}

function usernameParamNoAmp() {
  var u = currentUsername();
  return u ? "?username=" + encodeURIComponent(u) : "";
}

export function createKnowledgeController(options) {
  var apiBase = String(options.apiBase || "").replace(/\/$/, "");
  var root = options.knowledgeRootEl;

  var state = {
    tab: "personal",
    categories: [],
    files: [],
    currentCategory: null,
    searchQuery: "",
    lastSearchKeyword: "",
    categoryPage: 1,
    filePage: 1,
    shareSubTab: "received",   // 分享知识库子Tab：received / sent
    shareReceivedFiles: [],    // 收到的分享文件
    shareSentFiles: [],        // 发出的分享文件
    shareTargetUser: "",       // 从联系人右键菜单传入的分享目标用户
  };

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

  async function loadCategories() {
    try {
      var kbType = state.tab === "enterprise" ? "company" : state.tab;
      var data = await fetchJson(
        apiBase + "/knowledge/categories?type=" + kbType + usernameParam()
      );
      state.categories = data.success ? data.categories || [] : [];
    } catch (e) {
      state.categories = [];
    }
  }

  async function loadFiles(category) {
    try {
      var kbType = state.tab === "enterprise" ? "company" : state.tab;
      var url = apiBase + "/knowledge/files?type=" + kbType + usernameParam();
      if (category) {
        url += "&category=" + encodeURIComponent(category);
      }
      var data = await fetchJson(url);
      state.files = data.success ? data.files || [] : [];
    } catch (e) {
      state.files = [];
    }
  }

  function render() {
    if (!root) return;
    root.innerHTML = "";
    root.className = "knowledge-root";

    var inner = document.createElement("div");
    inner.className = "knowledge-inner";

    // 顶部操作栏：Tab切换 + 搜索 + 操作按钮
    inner.appendChild(renderTopBar());

    // 分享知识库Tab
    if (state.tab === "shared") {
      inner.appendChild(renderShareView());
      root.appendChild(inner);
      return;
    }

    // 面包屑（有分类时显示）
    if (state.currentCategory) {
      inner.appendChild(renderBreadcrumb());
    }

    // 主体内容
    if (state.currentCategory) {
      inner.appendChild(renderFileList());
    } else {
      inner.appendChild(renderCategoryList());
    }

    root.appendChild(inner);
  }

  function renderTopBar() {
    var topBar = document.createElement("div");
    topBar.className = "knowledge-topbar";

    // Tab切换按钮
    var tabs = document.createElement("div");
    tabs.className = "knowledge-tabs";

    var personalTab = document.createElement("button");
    personalTab.className = "knowledge-tab" + (state.tab === "personal" ? " active" : "");
    personalTab.textContent = "个人知识库";
    personalTab.addEventListener("click", function () {
      if (state.tab === "personal") return;
      state.tab = "personal";
      state.currentCategory = null;
      state.searchQuery = "";
      state.lastSearchKeyword = "";
      state.categoryPage = 1;
      state.filePage = 1;
      refresh();
    });

    var enterpriseTab = document.createElement("button");
    enterpriseTab.className = "knowledge-tab" + (state.tab === "enterprise" ? " active" : "");
    enterpriseTab.textContent = "企业知识库";
    enterpriseTab.addEventListener("click", function () {
      if (state.tab === "enterprise") return;
      state.tab = "enterprise";
      state.currentCategory = null;
      state.searchQuery = "";
      state.lastSearchKeyword = "";
      state.categoryPage = 1;
      state.filePage = 1;
      refresh();
    });

    tabs.appendChild(personalTab);
    tabs.appendChild(enterpriseTab);

    // 分享知识库Tab
    var sharedTab = document.createElement("button");
    sharedTab.className = "knowledge-tab" + (state.tab === "shared" ? " active" : "");
    sharedTab.textContent = "分享知识库";
    sharedTab.addEventListener("click", function () {
      if (state.tab === "shared") return;
      state.tab = "shared";
      state.currentCategory = null;
      state.searchQuery = "";
      state.lastSearchKeyword = "";
      state.shareSubTab = "received";
      refresh();
    });

    tabs.appendChild(sharedTab);
    topBar.appendChild(tabs);

    // 右侧：搜索 + 操作按钮
    var right = document.createElement("div");
    right.className = "knowledge-topbar-right";

    // 搜索区域（个人和企业知识库都支持）
    var searchWrap = document.createElement("div");
    searchWrap.className = "knowledge-search-wrap";

    var searchInput = document.createElement("input");
    searchInput.type = "text";
    searchInput.className = "knowledge-search-input";
    searchInput.placeholder = "搜索文件...";
    searchInput.value = state.searchQuery;
    searchInput.addEventListener("input", function () {
      state.searchQuery = this.value.trim();
    });
    searchInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && state.searchQuery) {
        doSearch();
      }
    });
    searchWrap.appendChild(searchInput);

    var searchBtn = document.createElement("button");
    searchBtn.className = "kb-btn kb-search-btn";
    searchBtn.textContent = "🔍";
    searchBtn.title = "搜索";
    searchBtn.addEventListener("click", function () {
      if (state.searchQuery) {
        doSearch();
      }
    });
    searchWrap.appendChild(searchBtn);

    right.appendChild(searchWrap);

    // 清除搜索按钮
    if (state.currentCategory === "__search__" && state.lastSearchKeyword) {
      var clearBtn = document.createElement("button");
      clearBtn.className = "kb-btn small";
      clearBtn.textContent = "清除搜索";
      clearBtn.addEventListener("click", function () {
        state.searchQuery = "";
        state.lastSearchKeyword = "";
        state.currentCategory = null;
        state.filePage = 1;
        refresh();
      });
      right.appendChild(clearBtn);
    }

    // 个人知识库专属操作按钮
    if (state.tab === "personal") {
      // 新建分类按钮（分类列表页）
      if (!state.currentCategory || state.currentCategory === "__search__") {
        var newBtn = document.createElement("button");
        newBtn.className = "kb-btn primary";
        newBtn.textContent = "+ 新建";
        newBtn.addEventListener("click", showCreateCategoryModal);
        right.appendChild(newBtn);
      }

      // 上传/添加URL按钮（文件列表页）
      if (state.currentCategory && state.currentCategory !== "__search__") {
        var uploadBtn = document.createElement("button");
        uploadBtn.className = "kb-btn primary";
        uploadBtn.textContent = "上传文件";
        uploadBtn.addEventListener("click", showUploadModal);
        right.appendChild(uploadBtn);

        var urlBtn = document.createElement("button");
        urlBtn.className = "kb-btn";
        urlBtn.textContent = "添加URL";
        urlBtn.addEventListener("click", showAddUrlModal);
        right.appendChild(urlBtn);
      }
    }

    topBar.appendChild(right);
    return topBar;
  }

  function renderBreadcrumb() {
    var breadcrumb = document.createElement("div");
    breadcrumb.className = "knowledge-breadcrumb";

    var rootItem = document.createElement("span");
    rootItem.className = "knowledge-breadcrumb-item";
    rootItem.textContent = "知识库";
    rootItem.addEventListener("click", function () {
      state.currentCategory = null;
      state.searchQuery = "";
      state.lastSearchKeyword = "";
      state.filePage = 1;
      render();
      loadData();
    });
    breadcrumb.appendChild(rootItem);

    if (state.currentCategory && state.currentCategory !== "__search__") {
      var sep = document.createElement("span");
      sep.className = "knowledge-breadcrumb-sep";
      sep.textContent = "›";
      breadcrumb.appendChild(sep);

      var catItem = document.createElement("span");
      catItem.className = "knowledge-breadcrumb-current";
      catItem.textContent = state.currentCategory;
      breadcrumb.appendChild(catItem);
    }

    return breadcrumb;
  }

  // 分页数据计算
  function paginate(items, page) {
    var total = items.length;
    var totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    var currentPage = Math.min(Math.max(1, page), totalPages);
    var start = (currentPage - 1) * PAGE_SIZE;
    var end = Math.min(start + PAGE_SIZE, total);
    return {
      items: items.slice(start, end),
      currentPage: currentPage,
      totalPages: totalPages,
      total: total,
    };
  }

  // 渲染分页控件
  function renderPagination(currentPage, totalPages, onPageChange) {
    var pagination = document.createElement("div");
    pagination.className = "kb-pagination";

    // 上一页
    var prevBtn = document.createElement("button");
    prevBtn.className = "kb-pagination-btn";
    prevBtn.textContent = "‹";
    prevBtn.disabled = currentPage <= 1;
    prevBtn.addEventListener("click", function () {
      if (currentPage > 1) onPageChange(currentPage - 1);
    });
    pagination.appendChild(prevBtn);

    // 页码按钮（最多显示5页）
    var startPage = Math.max(1, currentPage - 2);
    var endPage = Math.min(totalPages, startPage + 4);
    if (endPage - startPage < 4) {
      startPage = Math.max(1, endPage - 4);
    }

    for (var i = startPage; i <= endPage; i++) {
      var pageBtn = document.createElement("button");
      pageBtn.className = "kb-pagination-btn" + (i === currentPage ? " active" : "");
      pageBtn.textContent = String(i);
      (function (p) {
        pageBtn.addEventListener("click", function () {
          onPageChange(p);
        });
      })(i);
      pagination.appendChild(pageBtn);
    }

    // 下一页
    var nextBtn = document.createElement("button");
    nextBtn.className = "kb-pagination-btn";
    nextBtn.textContent = "›";
    nextBtn.disabled = currentPage >= totalPages;
    nextBtn.addEventListener("click", function () {
      if (currentPage < totalPages) onPageChange(currentPage + 1);
    });
    pagination.appendChild(nextBtn);

    // 页码信息
    var info = document.createElement("span");
    info.className = "kb-pagination-info";
    info.textContent = currentPage + " / " + totalPages;
    pagination.appendChild(info);

    return pagination;
  }

  function renderCategoryList() {
    var wrapper = document.createElement("div");

    if (state.tab === "enterprise" && state.categories.length === 0) {
      var empty = document.createElement("div");
      empty.className = "knowledge-empty";
      empty.innerHTML = '<div class="knowledge-empty-icon">📚</div><div>企业知识库由管理端维护，暂无内容</div>';
      wrapper.appendChild(empty);
      return wrapper;
    }

    if (state.categories.length === 0) {
      var empty2 = document.createElement("div");
      empty2.className = "knowledge-empty";
      empty2.innerHTML = '<div class="knowledge-empty-icon">📁</div><div>暂无知识库分类，点击"+ 新建"创建</div>';
      wrapper.appendChild(empty2);
      return wrapper;
    }

    var paginated = paginate(state.categories, state.categoryPage);
    state.categoryPage = paginated.currentPage;

    var list = document.createElement("div");
    list.className = "knowledge-category-list";

    paginated.items.forEach(function (cat) {
      var card = document.createElement("div");
      card.className = "knowledge-category-card";

      var info = document.createElement("div");
      info.className = "knowledge-category-info";

      var icon = document.createElement("span");
      icon.className = "knowledge-category-icon";
      icon.textContent = "\uD83D\uDCC1";

      var details = document.createElement("div");

      var nameEl = document.createElement("div");
      nameEl.className = "knowledge-category-name";
      nameEl.textContent = cat.display_name || cat.name;

      var meta = document.createElement("div");
      meta.className = "knowledge-category-meta";
      meta.textContent = (cat.file_count || 0) + " 个文件";

      details.appendChild(nameEl);
      details.appendChild(meta);
      info.appendChild(icon);
      info.appendChild(details);

      var actionsDiv = document.createElement("div");
      actionsDiv.className = "knowledge-category-actions";

      if (state.tab !== "enterprise") {
        var delBtn = document.createElement("button");
        delBtn.className = "kb-btn danger small";
        delBtn.textContent = "删除";
        delBtn.addEventListener("click", function (e) {
          e.stopPropagation();
        confirmDeleteCategory(cat.name);
      });
      actionsDiv.appendChild(delBtn);
      }

      card.appendChild(info);
      card.appendChild(actionsDiv);

      card.addEventListener("click", function () {
        state.currentCategory = cat.name;
        state.lastSearchKeyword = "";
        state.filePage = 1;
        loadFiles(cat.name).then(function () {
          render();
        });
      });

      list.appendChild(card);
    });

    wrapper.appendChild(list);

    // 分页控件
    if (paginated.totalPages > 1) {
      wrapper.appendChild(renderPagination(paginated.currentPage, paginated.totalPages, function (page) {
        state.categoryPage = page;
        render();
      }));
    }

    return wrapper;
  }

  function highlightKeyword(text, keyword) {
    if (!keyword || !text) return escapeHtml(text);
    var escaped = escapeHtml(text);
    var kw = escapeHtml(keyword);
    var parts = kw.split(/\s+/).filter(function (k) { return k.length > 0; });
    if (parts.length === 0) return escaped;

    var result = escaped;
    parts.forEach(function (part) {
      var regex = new RegExp("(" + part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
      result = result.replace(regex, '<mark class="kb-highlight">$1</mark>');
    });
    return result;
  }

  function renderFileList() {
    var wrapper = document.createElement("div");

    // 搜索状态提示
    if (state.currentCategory === "__search__") {
      var searchBanner = document.createElement("div");
      searchBanner.className = "knowledge-search-banner";
      searchBanner.innerHTML = '搜索 "<b>' + escapeHtml(state.lastSearchKeyword) + '</b>" 共找到 <b>' + state.files.length + '</b> 个文件';
      wrapper.appendChild(searchBanner);
    }

    if (state.files.length === 0) {
      var empty = document.createElement("div");
      empty.className = "knowledge-empty";
      empty.innerHTML = '<div class="knowledge-empty-icon">📄</div><div>暂无文件，点击"上传文件"或"添加URL"</div>';
      wrapper.appendChild(empty);
      return wrapper;
    }

    var paginated = paginate(state.files, state.filePage);
    state.filePage = paginated.currentPage;

    var list = document.createElement("div");
    list.className = "knowledge-file-list";

    var kw = state.lastSearchKeyword || "";

    paginated.items.forEach(function (file) {
      var card = document.createElement("div");
      card.className = "knowledge-file-card";

      var headerDiv = document.createElement("div");
      headerDiv.className = "knowledge-file-header";

      var nameEl = document.createElement("span");
      nameEl.className = "knowledge-file-name";
      nameEl.innerHTML = highlightKeyword(file.original_filename, kw);

      var typeEl = document.createElement("span");
      typeEl.className = "knowledge-file-type";
      typeEl.textContent = file.file_type || "";

      headerDiv.appendChild(nameEl);
      headerDiv.appendChild(typeEl);

      // 摘要区域：超过阈值时折叠显示，点击"加载全部"展开
      var summary = document.createElement("div");
      summary.className = "knowledge-file-summary";

      var rawSummary = file.summary || "暂无摘要";
      var plainLen = rawSummary.replace(/<[^>]*>/g, "").length;

      if (plainLen > SUMMARY_MAX_CHARS) {
        // 折叠状态：截断文本 + 渐变遮罩 + 展开按钮
        var summaryWrap = document.createElement("div");
        summaryWrap.className = "summary-collapsible summary-collapsed";

        var summaryText = document.createElement("div");
        summaryText.className = "summary-text";
        summaryText.innerHTML = highlightKeyword(rawSummary, kw);

        // 渐变遮罩层，暗示内容被截断
        var summaryFade = document.createElement("div");
        summaryFade.className = "summary-fade";

        var toggleBtn = document.createElement("button");
        toggleBtn.className = "summary-toggle-btn";
        toggleBtn.textContent = "加载全部";

        // 点击切换展开/收起
        toggleBtn.addEventListener("click", function () {
          var isCollapsed = summaryWrap.classList.contains("summary-collapsed");
          if (isCollapsed) {
            summaryWrap.classList.remove("summary-collapsed");
            summaryWrap.classList.add("summary-expanded");
            toggleBtn.textContent = "收起";
            summaryFade.style.display = "none";
          } else {
            summaryWrap.classList.remove("summary-expanded");
            summaryWrap.classList.add("summary-collapsed");
            toggleBtn.textContent = "加载全部";
            summaryFade.style.display = "";
          }
        });

        summaryWrap.appendChild(summaryText);
        summaryWrap.appendChild(summaryFade);
        summary.appendChild(summaryWrap);
        summary.appendChild(toggleBtn);
      } else {
        // 短摘要直接显示
        summary.innerHTML = highlightKeyword(rawSummary, kw);
      }

      var actionsDiv = document.createElement("div");
      actionsDiv.className = "knowledge-file-actions";

      var viewEditBtn = document.createElement("button");
      viewEditBtn.className = "kb-btn small";
      // 企业知识库仅支持预览，按钮文案为"查看"；个人知识库为"查看/编辑"
      viewEditBtn.textContent = state.tab === "enterprise" ? "查看" : "查看/编辑";
      viewEditBtn.addEventListener("click", function () {
        showFileDetailModal(file.id);
      });

      var delBtn = document.createElement("button");
      delBtn.className = "kb-btn small danger";
      delBtn.textContent = "删除";
      delBtn.addEventListener("click", function () {
        confirmDeleteFile(file.id, file.original_filename);
      });

      actionsDiv.appendChild(viewEditBtn);
      if (state.tab !== "enterprise") {
        // 个人知识库：显示移动、分享、删除按钮
        var moveBtn = document.createElement("button");
        moveBtn.className = "kb-btn small";
        moveBtn.textContent = "移动";
        moveBtn.addEventListener("click", function () {
          showMoveFileModal(file.id, file.category);
        });
        actionsDiv.appendChild(moveBtn);

        var shareBtn = document.createElement("button");
        shareBtn.className = "kb-btn small";
        shareBtn.textContent = "分享";
        shareBtn.addEventListener("click", function () {
          showShareModal([file.id]);
        });
        actionsDiv.appendChild(shareBtn);

        actionsDiv.appendChild(delBtn);
      }

      card.appendChild(headerDiv);
      card.appendChild(summary);
      card.appendChild(actionsDiv);
      list.appendChild(card);
    });

    wrapper.appendChild(list);

    // 分页控件
    if (paginated.totalPages > 1) {
      wrapper.appendChild(renderPagination(paginated.currentPage, paginated.totalPages, function (page) {
        state.filePage = page;
        render();
      }));
    }

    return wrapper;
  }

  // ===== 弹窗通用 =====
  function openModal(htmlContent, onReady) {
    var overlay = document.createElement("div");
    overlay.className = "kb-modal-overlay";

    var modal = document.createElement("div");
    modal.innerHTML = htmlContent;
    overlay.appendChild(modal.firstElementChild || modal.firstChild);
    document.body.appendChild(overlay);

    var modalEl = overlay.querySelector(".kb-modal");
    var closeFn = function () {
      document.body.removeChild(overlay);
    };

    if (onReady) {
      onReady(modalEl, closeFn, overlay);
    }

    return { overlay: overlay, close: closeFn };
  }

  // ===== 弹窗：创建分类 =====
  function showCreateCategoryModal() {
    var html =
      '<div class="kb-modal kb-modal-sm">' +
      '<div class="kb-modal-title">新建知识库分类</div>' +
      '<div class="kb-modal-body">' +
      '<label class="kb-label">分类名称</label>' +
      '<input class="kb-input" id="kb-category-name-input" placeholder="例如：兆企、铝交易中心" />' +
      "</div>" +
      '<div class="kb-modal-footer">' +
      '<button class="kb-btn" id="kb-category-cancel">取消</button>' +
      '<button class="kb-btn primary" id="kb-category-confirm">创建</button>' +
      "</div>" +
      "</div>";

    openModal(html, function (modal, close) {
      var nameInput = modal.querySelector("#kb-category-name-input");
      modal.querySelector("#kb-category-cancel").addEventListener("click", close);
      modal.querySelector("#kb-category-confirm").addEventListener("click", async function () {
        var name = nameInput.value.trim();
        if (!name) { showToast("请输入分类名称", "error"); return; }
        var btn = modal.querySelector("#kb-category-confirm");
        btn.disabled = true; btn.textContent = "创建中...";
        try {
          var data = await fetchJson(apiBase + "/knowledge/categories" + usernameParamNoAmp(), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name, type: state.tab }),
          });
          if (data.success) { showToast("分类创建成功"); close(); refresh(); }
          else { showToast(data.error || "创建失败", "error"); }
        } catch (e) { showToast("创建失败: " + e.message, "error"); }
        btn.disabled = false; btn.textContent = "创建";
      });
      setTimeout(function () { nameInput.focus(); }, 100);
    });
  }

  // ===== 弹窗：删除分类确认 =====
  function confirmDeleteCategory(name) {
    var html =
      '<div class="kb-modal kb-modal-sm">' +
      '<div class="kb-modal-title">确认删除</div>' +
      '<div class="kb-modal-body">确定要删除分类 <b>' + escapeHtml(name) + '</b> 及其所有文件吗？此操作不可恢复。</div>' +
      '<div class="kb-modal-footer">' +
      '<button class="kb-btn" id="kb-del-cat-cancel">取消</button>' +
      '<button class="kb-btn danger" id="kb-del-cat-confirm">确认删除</button>' +
      "</div></div>";

    openModal(html, function (modal, close) {
      modal.querySelector("#kb-del-cat-cancel").addEventListener("click", close);
      modal.querySelector("#kb-del-cat-confirm").addEventListener("click", async function () {
        try {
          var data = await fetchJson(apiBase + "/knowledge/categories/" + encodeURIComponent(name) + "?type=" + state.tab + usernameParam(), { method: "DELETE" });
          if (data.success) { showToast("分类已删除"); close(); refresh(); }
          else { showToast(data.error || "删除失败", "error"); }
        } catch (e) { showToast("删除失败: " + e.message, "error"); }
      });
    });
  }

  // ===== 弹窗：上传文件（支持多文件） =====
  function showUploadModal() {
    var html =
      '<div class="kb-modal kb-modal-sm">' +
      '<div class="kb-modal-title">上传文件到 ' + escapeHtml(state.currentCategory) + '</div>' +
      '<div class="kb-modal-body">' +
      '<label class="kb-label">选择文件（支持 word/ppt/pdf/txt/md/csv/excel，可多选）</label>' +
      '<input type="file" class="kb-input" id="kb-upload-input" accept=".docx,.doc,.pptx,.ppt,.pdf,.txt,.md,.csv,.xls,.xlsx" multiple />' +
      '<div id="kb-upload-file-list" class="kb-upload-file-list"></div>' +
      '<div id="kb-upload-status" style="margin-top:0.75rem;font-size:0.85rem;color:var(--text-muted)"></div>' +
      "</div>" +
      '<div class="kb-modal-footer">' +
      '<button class="kb-btn" id="kb-upload-cancel">取消</button>' +
      '<button class="kb-btn primary" id="kb-upload-confirm">上传并转换</button>' +
      "</div></div>";

    openModal(html, function (modal, close) {
      var fileInput = modal.querySelector("#kb-upload-input");
      var fileListEl = modal.querySelector("#kb-upload-file-list");
      var statusEl = modal.querySelector("#kb-upload-status");

      // 文件选择后显示文件列表
      fileInput.addEventListener("change", function () {
        fileListEl.innerHTML = "";
        var files = fileInput.files;
        if (!files || files.length === 0) return;
        for (var i = 0; i < files.length; i++) {
          var item = document.createElement("div");
          item.className = "kb-upload-file-item";
          item.setAttribute("data-index", String(i));
          item.innerHTML =
            '<span class="kb-upload-file-name">' + escapeHtml(files[i].name) + '</span>' +
            '<span class="kb-upload-file-size">' + formatFileSize(files[i].size) + '</span>' +
            '<span class="kb-upload-file-status kb-upload-pending">待上传</span>';
          fileListEl.appendChild(item);
        }
      });

      modal.querySelector("#kb-upload-cancel").addEventListener("click", close);
      modal.querySelector("#kb-upload-confirm").addEventListener("click", async function () {
        var files = fileInput.files;
        if (!files || files.length === 0) { showToast("请选择文件", "error"); return; }

        var btn = modal.querySelector("#kb-upload-confirm");
        btn.disabled = true; btn.textContent = "上传中...";
        statusEl.textContent = "正在上传并转换 " + files.length + " 个文件，请稍候...";

        // 构建多文件 FormData
        var formData = new FormData();
        for (var i = 0; i < files.length; i++) {
          formData.append("files", files[i]);
        }

        try {
          var data = await fetchJson(
            apiBase + "/knowledge/files/batch-upload?category=" + encodeURIComponent(state.currentCategory) + "&type=" + state.tab + usernameParam(),
            { method: "POST", body: formData }
          );

          if (data.success) {
            // 更新每个文件的状态
            var results = data.results || [];
            results.forEach(function (r, idx) {
              var itemEl = fileListEl.querySelector('[data-index="' + idx + '"]');
              if (!itemEl) return;
              var statusSpan = itemEl.querySelector(".kb-upload-file-status");
              if (r.success) {
                statusSpan.className = "kb-upload-file-status kb-upload-success";
                statusSpan.textContent = "✓ 成功";
              } else {
                statusSpan.className = "kb-upload-file-status kb-upload-error";
                statusSpan.textContent = "✗ " + (r.error || "失败");
              }
            });

            var failCount = data.total - data.success_count;
            if (failCount === 0) {
              showToast("全部 " + data.success_count + " 个文件上传成功");
              setTimeout(function () { close(); refresh(); }, 800);
            } else {
              statusEl.textContent = "完成：成功 " + data.success_count + " 个，失败 " + failCount + " 个";
              showToast(data.success_count + "/" + data.total + " 个文件上传成功", "error");
              refresh();
            }
          } else {
            showToast(data.error || "上传失败", "error");
          }
        } catch (e) {
          showToast("上传失败: " + e.message, "error");
        }
        btn.disabled = false; btn.textContent = "上传并转换";
      });
    });
  }

  // 格式化文件大小
  function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  // ===== 弹窗：添加URL（支持多URL） =====
  function showAddUrlModal() {
    var html =
      '<div class="kb-modal kb-modal-sm">' +
      '<div class="kb-modal-title">添加URL到 ' + escapeHtml(state.currentCategory) + '</div>' +
      '<div class="kb-modal-body">' +
      '<div class="kb-form-group">' +
      '<label class="kb-label">网页URL（每行一个，支持多个）</label>' +
      '<textarea class="kb-textarea" id="kb-url-input" rows="5" placeholder="https://example.com/article1&#10;https://example.com/article2&#10;https://example.com/article3"></textarea>' +
      "</div>" +
      '<div id="kb-url-list" class="kb-upload-file-list"></div>' +
      '<div id="kb-url-status" style="font-size:0.85rem;color:var(--text-muted)"></div>' +
      "</div>" +
      '<div class="kb-modal-footer">' +
      '<button class="kb-btn" id="kb-url-cancel">取消</button>' +
      '<button class="kb-btn primary" id="kb-url-confirm">添加并转换</button>' +
      "</div></div>";

    openModal(html, function (modal, close) {
      var urlInput = modal.querySelector("#kb-url-input");
      var urlListEl = modal.querySelector("#kb-url-list");
      var statusEl = modal.querySelector("#kb-url-status");
      modal.querySelector("#kb-url-cancel").addEventListener("click", close);
      modal.querySelector("#kb-url-confirm").addEventListener("click", async function () {
        var rawText = urlInput.value.trim();
        if (!rawText) { showToast("请输入URL", "error"); return; }

        // 按行分割，过滤空行，去重
        var urls = rawText.split(/[\n\r]+/).map(function (u) { return u.trim(); }).filter(function (u) { return u.length > 0; });
        if (urls.length === 0) { showToast("请输入有效的URL", "error"); return; }

        // 去重
        var uniqueUrls = [];
        var seen = {};
        urls.forEach(function (u) {
          if (!seen[u]) { seen[u] = true; uniqueUrls.push(u); }
        });
        urls = uniqueUrls;

        // 显示URL列表
        urlListEl.innerHTML = "";
        urls.forEach(function (url, idx) {
          var item = document.createElement("div");
          item.className = "kb-upload-file-item";
          item.setAttribute("data-index", String(idx));
          item.innerHTML =
            '<span class="kb-upload-file-name kb-url-name" title="' + escapeHtml(url) + '">' + escapeHtml(url) + '</span>' +
            '<span class="kb-upload-file-status kb-upload-pending">待处理</span>';
          urlListEl.appendChild(item);
        });

        var btn = modal.querySelector("#kb-url-confirm");
        btn.disabled = true; btn.textContent = "转换中...";
        statusEl.textContent = "正在渲染 " + urls.length + " 个网页并转换...（可能需要几十秒）";

        try {
          var kbType = state.tab === "enterprise" ? "company" : state.tab;
          var data = await fetchJson(apiBase + "/knowledge/files/batch-url?type=" + kbType + usernameParam(), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ urls: urls, category: state.currentCategory }),
          });

          if (data.success) {
            // 更新每个URL的状态
            var results = data.results || [];
            results.forEach(function (r, idx) {
              var itemEl = urlListEl.querySelector('[data-index="' + idx + '"]');
              if (!itemEl) return;
              var statusSpan = itemEl.querySelector(".kb-upload-file-status");
              if (r.success) {
                statusSpan.className = "kb-upload-file-status kb-upload-success";
                statusSpan.textContent = "✓ 成功";
              } else {
                statusSpan.className = "kb-upload-file-status kb-upload-error";
                statusSpan.textContent = "✗ " + (r.error || "失败");
              }
            });

            var failCount = data.total - data.success_count;
            if (failCount === 0) {
              showToast("全部 " + data.success_count + " 个URL添加成功");
              setTimeout(function () { close(); refresh(); }, 800);
            } else {
              statusEl.textContent = "完成：成功 " + data.success_count + " 个，失败 " + failCount + " 个";
              showToast(data.success_count + "/" + data.total + " 个URL添加成功", "error");
              refresh();
            }
          } else {
            showToast(data.error || "添加失败", "error");
          }
        } catch (e) {
          showToast("添加失败: " + e.message, "error");
        }
        btn.disabled = false; btn.textContent = "添加并转换";
        statusEl.textContent = "";
      });
      setTimeout(function () { urlInput.focus(); }, 100);
    });
  }

  // ===== 弹窗：查看/编辑文件（固定高度，切换Tab不变化） =====
  // 企业知识库仅支持预览，不支持编辑
  function showFileDetailModal(fileId) {
    var isEnterprise = state.tab === "enterprise";
    var kbType = isEnterprise ? "company" : state.tab;

    var editBtnHtml = isEnterprise ? "" : '<button class="kb-mode-btn" id="kb-mode-edit">编辑</button>';
    var saveBtnHidden = isEnterprise ? "hidden" : "hidden";

    var html =
      '<div class="kb-modal kb-modal-lg kb-modal-fixed-height">' +
      '<div class="kb-modal-header">' +
      '<div class="kb-modal-title" id="kb-file-title">文件详情</div>' +
      '<div class="kb-file-mode-bar">' +
      '<button class="kb-mode-btn active" id="kb-mode-view">预览</button>' +
      editBtnHtml +
      "</div>" +
      "</div>" +
      '<div class="kb-modal-body-fixed">' +
      '<div id="kb-file-view" class="knowledge-viewer-content">加载中...</div>' +
      '<textarea class="kb-textarea kb-textarea-fixed hidden" id="kb-edit-textarea"></textarea>' +
      "</div>" +
      '<div id="kb-file-status" class="kb-modal-status"></div>' +
      '<div class="kb-modal-footer">' +
      '<button class="kb-btn" id="kb-file-close">关闭</button>' +
      '<button class="kb-btn primary ' + saveBtnHidden + '" id="kb-file-save">保存</button>' +
      "</div></div>";

    openModal(html, function (modal, close) {
      var titleEl = modal.querySelector("#kb-file-title");
      var viewDiv = modal.querySelector("#kb-file-view");
      var editArea = modal.querySelector("#kb-edit-textarea");
      var statusEl = modal.querySelector("#kb-file-status");
      var modeViewBtn = modal.querySelector("#kb-mode-view");
      var modeEditBtn = modal.querySelector("#kb-mode-edit");
      var saveBtn = modal.querySelector("#kb-file-save");
      var closeBtn = modal.querySelector("#kb-file-close");

      var currentContent = "";

      function setMode(edit) {
        if (edit) {
          viewDiv.classList.add("hidden");
          editArea.classList.remove("hidden");
          saveBtn.classList.remove("hidden");
          modeViewBtn.classList.remove("active");
          modeEditBtn.classList.add("active");
          editArea.value = currentContent;
        } else {
          editArea.classList.add("hidden");
          viewDiv.classList.remove("hidden");
          saveBtn.classList.add("hidden");
          if (modeEditBtn) {
            modeEditBtn.classList.remove("active");
          }
          modeViewBtn.classList.add("active");
          try {
            viewDiv.innerHTML = assistantMarkdownToHtml(currentContent) || "（空内容）";
          } catch (e) {
            viewDiv.textContent = currentContent || "（空内容）";
          }
        }
      }

      closeBtn.addEventListener("click", close);
      modeViewBtn.addEventListener("click", function () { setMode(false); });
      if (modeEditBtn) {
        modeEditBtn.addEventListener("click", function () { setMode(true); });
      }

      // 使用 usernameParam()（& 前缀）而非 usernameParamNoAmp()（? 前缀），
      // 避免 URL 中出现双 ? 导致后端无法正确解析 type 参数
      fetchJson(apiBase + "/knowledge/files/" + encodeURIComponent(fileId) + "?type=" + kbType + usernameParam())
        .then(function (data) {
          if (data.success && data.content !== undefined) {
            currentContent = data.content;
            titleEl.textContent = data.file ? data.file.original_filename : "文件详情";
            setMode(false);
          } else {
            currentContent = "无法加载文件内容";
            setMode(false);
          }
        })
        .catch(function () {
          currentContent = "加载失败";
          setMode(false);
        });

      saveBtn.addEventListener("click", async function () {
        var newContent = editArea.value;
        if (newContent === currentContent) { showToast("内容未修改"); return; }
        saveBtn.disabled = true; saveBtn.textContent = "保存中...";
        statusEl.textContent = "正在保存...";
        try {
          var data = await fetchJson(apiBase + "/knowledge/files/" + encodeURIComponent(fileId) + "?type=" + kbType + usernameParam(), {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: newContent }),
          });
          if (data.success) {
            currentContent = newContent;
            showToast("保存成功，摘要已更新");
            setMode(false);
            refresh();
          } else {
            showToast(data.error || "保存失败", "error");
          }
        } catch (e) { showToast("保存失败: " + e.message, "error"); }
        saveBtn.disabled = false; saveBtn.textContent = "保存";
        statusEl.textContent = "";
      });
    });
  }

  // ===== 弹窗：删除文件确认 =====
  function confirmDeleteFile(fileId, filename) {
    var html =
      '<div class="kb-modal kb-modal-sm">' +
      '<div class="kb-modal-title">确认删除</div>' +
      '<div class="kb-modal-body">确定要删除文件 <b>' + escapeHtml(filename) + '</b> 吗？此操作不可恢复。</div>' +
      '<div class="kb-modal-footer">' +
      '<button class="kb-btn" id="kb-del-file-cancel">取消</button>' +
      '<button class="kb-btn danger" id="kb-del-file-confirm">确认删除</button>' +
      "</div></div>";

    openModal(html, function (modal, close) {
      modal.querySelector("#kb-del-file-cancel").addEventListener("click", close);
      modal.querySelector("#kb-del-file-confirm").addEventListener("click", async function () {
        try {
          var kbType = state.tab === "enterprise" ? "company" : state.tab;
          var data = await fetchJson(apiBase + "/knowledge/files/" + encodeURIComponent(fileId) + "?type=" + kbType + usernameParam(), { method: "DELETE" });
          if (data.success) { showToast("文件已删除"); close(); refresh(); }
          else { showToast(data.error || "删除失败", "error"); }
        } catch (e) { showToast("删除失败: " + e.message, "error"); }
      });
    });
  }

  // ===== 搜索 =====
  async function doSearch() {
    if (!state.searchQuery) return;
    state.lastSearchKeyword = state.searchQuery;
    state.filePage = 1;
    try {
      var kbType = state.tab === "enterprise" ? "company" : state.tab;
      var data = await fetchJson(
        apiBase + "/knowledge/search?q=" + encodeURIComponent(state.searchQuery) + "&type=" + kbType + usernameParam()
      );
      state.files = data.success ? data.files || [] : [];
      state.currentCategory = "__search__";
      render();
    } catch (e) {
      showToast("搜索失败: " + e.message, "error");
    }
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function loadData() {
    await loadCategories();
    render();
  }

  async function refresh() {
    if (!root) return;
    if (state.tab === "shared") {
      await loadShareData();
      render();
      return;
    }
    if (state.currentCategory && state.currentCategory !== "__search__") {
      await loadFiles(state.currentCategory);
    } else {
      await loadCategories();
    }
    render();
  }

  // ===== 分享知识库视图 =====

  /** 加载分享数据 */
  async function loadShareData() {
    try {
      var receivedRes = await fetchJson(apiBase + "/knowledge/shares/received" + usernameParamNoAmp());
      state.shareReceivedFiles = receivedRes.success ? receivedRes.files || [] : [];
    } catch (e) {
      state.shareReceivedFiles = [];
    }
    try {
      var sentRes = await fetchJson(apiBase + "/knowledge/shares/sent" + usernameParamNoAmp());
      state.shareSentFiles = sentRes.success ? sentRes.files || [] : [];
    } catch (e) {
      state.shareSentFiles = [];
    }
  }

  /** 渲染分享知识库视图 */
  function renderShareView() {
    var wrapper = document.createElement("div");

    // 子Tab切换：收到的分享 / 发出的分享
    var subTabs = document.createElement("div");
    subTabs.className = "knowledge-tabs share-sub-tabs";

    var receivedTab = document.createElement("button");
    receivedTab.className = "knowledge-tab" + (state.shareSubTab === "received" ? " active" : "");
    receivedTab.textContent = "收到的分享";
    receivedTab.addEventListener("click", function () {
      state.shareSubTab = "received";
      render();
    });

    var sentTab = document.createElement("button");
    sentTab.className = "knowledge-tab" + (state.shareSubTab === "sent" ? " active" : "");
    sentTab.textContent = "发出的分享";
    sentTab.addEventListener("click", function () {
      state.shareSubTab = "sent";
      render();
    });

    subTabs.appendChild(receivedTab);
    subTabs.appendChild(sentTab);
    wrapper.appendChild(subTabs);

    // 内容区
    var files = state.shareSubTab === "received" ? state.shareReceivedFiles : state.shareSentFiles;

    if (files.length === 0) {
      var empty = document.createElement("div");
      empty.className = "knowledge-empty";
      empty.innerHTML = state.shareSubTab === "received"
        ? '<div class="knowledge-empty-icon">📭</div><div>暂无收到的分享</div>'
        : '<div class="knowledge-empty-icon">📤</div><div>暂无发出的分享</div>';
      wrapper.appendChild(empty);
      return wrapper;
    }

    var list = document.createElement("div");
    list.className = "knowledge-file-list";

    files.forEach(function (file) {
      var card = document.createElement("div");
      card.className = "knowledge-file-card";

      var headerDiv = document.createElement("div");
      headerDiv.className = "knowledge-file-header";

      var nameEl = document.createElement("span");
      nameEl.className = "knowledge-file-name";
      nameEl.textContent = file.original_filename || file.md_filename;

      var typeEl = document.createElement("span");
      typeEl.className = "knowledge-file-type";
      typeEl.textContent = file.file_type || "";

      headerDiv.appendChild(nameEl);
      headerDiv.appendChild(typeEl);

      // 分享信息行
      var shareInfo = document.createElement("div");
      shareInfo.className = "knowledge-file-share-info";
      if (state.shareSubTab === "received") {
        shareInfo.textContent = "来自: " + (file.owner_username || "未知");
      } else {
        shareInfo.textContent = "分享给: " + (file.target_username || "未知");
      }

      var summary = document.createElement("div");
      summary.className = "knowledge-file-summary";
      summary.textContent = file.summary || "暂无摘要";

      var actionsDiv = document.createElement("div");
      actionsDiv.className = "knowledge-file-actions";

      // 查看按钮
      var viewBtn = document.createElement("button");
      viewBtn.className = "kb-btn small";
      viewBtn.textContent = "查看";
      viewBtn.addEventListener("click", function () {
        showFileDetailModal(file.id);
      });
      actionsDiv.appendChild(viewBtn);

      // 发出的分享可取消
      if (state.shareSubTab === "sent") {
        var cancelBtn = document.createElement("button");
        cancelBtn.className = "kb-btn small danger";
        cancelBtn.textContent = "取消分享";
        cancelBtn.addEventListener("click", function () {
          confirmCancelShare(file.share_id, file.original_filename);
        });
        actionsDiv.appendChild(cancelBtn);
      }

      card.appendChild(headerDiv);
      card.appendChild(shareInfo);
      card.appendChild(summary);
      card.appendChild(actionsDiv);
      list.appendChild(card);
    });

    wrapper.appendChild(list);
    return wrapper;
  }

  // ===== 分享弹窗 =====

  /** 显示分享弹窗（选择目标用户） */
  function showShareModal(fileIds) {
    var html =
      '<div class="kb-modal kb-modal-sm">' +
      '<div class="kb-modal-title">分享知识库文件</div>' +
      '<div class="kb-modal-body">' +
      '<label class="kb-label">分享给（输入用户名）</label>' +
      '<input class="kb-input" id="kb-share-target-input" placeholder="请输入对方用户名" />' +
      '<div class="kb-form-group" style="margin-top:0.75rem">' +
      '<span class="kb-label">已选择 ' + fileIds.length + ' 个文件</span>' +
      '</div>' +
      '</div>' +
      '<div class="kb-modal-footer">' +
      '<button class="kb-btn" id="kb-share-cancel">取消</button>' +
      '<button class="kb-btn primary" id="kb-share-confirm">确认分享</button>' +
      '</div>' +
      '</div>';

    openModal(html, function (modal, close) {
      var targetInput = modal.querySelector("#kb-share-target-input");
      modal.querySelector("#kb-share-cancel").addEventListener("click", close);
      modal.querySelector("#kb-share-confirm").addEventListener("click", async function () {
        var target = targetInput.value.trim();
        if (!target) { showToast("请输入目标用户名", "error"); return; }
        var btn = modal.querySelector("#kb-share-confirm");
        btn.disabled = true; btn.textContent = "分享中...";
        try {
          var data = await fetchJson(apiBase + "/knowledge/shares" + usernameParamNoAmp(), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ file_ids: fileIds, target_username: target }),
          });
          if (data.success) {
            showToast("分享成功 " + (data.success_count || 0) + " 个文件");
            if (data.errors && data.errors.length) {
              showToast(data.errors.join("; "), "error");
            }
            close(); refresh();
          } else {
            showToast(data.error || "分享失败", "error");
          }
        } catch (e) { showToast("分享失败: " + e.message, "error"); }
        btn.disabled = false; btn.textContent = "确认分享";
      });
      setTimeout(function () { targetInput.focus(); }, 100);
    });
  }

  /** 从联系人右键菜单进入分享模式，预填目标用户，先选择文件 */
  function showShareModalWithTarget(targetUserName) {
    if (!state.currentCategory || state.currentCategory === "__search__") {
      showToast("请先进入一个知识库分类，再选择文件分享", "error");
      return;
    }
    var fileIds = state.files.map(function (f) { return f.id; });
    if (!fileIds.length) {
      showToast("当前分类下没有文件可分享", "error");
      return;
    }

    var html =
      '<div class="kb-modal kb-modal-sm">' +
      '<div class="kb-modal-title">分享知识库文件</div>' +
      '<div class="kb-modal-body">' +
      '<label class="kb-label">分享给</label>' +
      '<input class="kb-input" id="kb-share-target-input" value="' + escapeHtml(targetUserName) + '" readonly />' +
      '<div class="kb-form-group" style="margin-top:0.75rem">' +
      '<label class="kb-label">选择要分享的文件</label>' +
      '<div id="kb-share-file-list" class="kb-share-file-checklist"></div>' +
      '</div>' +
      '</div>' +
      '<div class="kb-modal-footer">' +
      '<button class="kb-btn" id="kb-share-cancel">取消</button>' +
      '<button class="kb-btn primary" id="kb-share-confirm">确认分享</button>' +
      '</div>' +
      '</div>';

    openModal(html, function (modal, close) {
      var fileListEl = modal.querySelector("#kb-share-file-list");
      state.files.forEach(function (f) {
        var label = document.createElement("label");
        label.className = "kb-share-file-item";
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = f.id;
        cb.className = "kb-share-file-checkbox";
        var span = document.createElement("span");
        span.textContent = f.original_filename || f.md_filename;
        label.appendChild(cb);
        label.appendChild(span);
        fileListEl.appendChild(label);
      });

      modal.querySelector("#kb-share-cancel").addEventListener("click", close);
      modal.querySelector("#kb-share-confirm").addEventListener("click", async function () {
        var checkboxes = modal.querySelectorAll(".kb-share-file-checkbox:checked");
        var selectedIds = [];
        for (var i = 0; i < checkboxes.length; i++) {
          selectedIds.push(checkboxes[i].value);
        }
        if (!selectedIds.length) { showToast("请至少选择一个文件", "error"); return; }
        var btn = modal.querySelector("#kb-share-confirm");
        btn.disabled = true; btn.textContent = "分享中...";
        try {
          var data = await fetchJson(apiBase + "/knowledge/shares" + usernameParamNoAmp(), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ file_ids: selectedIds, target_username: targetUserName }),
          });
          if (data.success) {
            showToast("分享成功 " + (data.success_count || 0) + " 个文件");
            close(); refresh();
          } else {
            showToast(data.error || "分享失败", "error");
          }
        } catch (e) { showToast("分享失败: " + e.message, "error"); }
        btn.disabled = false; btn.textContent = "确认分享";
      });
    });
  }

  // ===== 取消分享确认 =====

  function confirmCancelShare(shareId, fileName) {
    var html =
      '<div class="kb-modal kb-modal-sm">' +
      '<div class="kb-modal-title">确认取消分享</div>' +
      '<div class="kb-modal-body">确定要取消分享文件 <b>' + escapeHtml(fileName) + '</b> 吗？</div>' +
      '<div class="kb-modal-footer">' +
      '<button class="kb-btn" id="kb-cancel-share-no">取消</button>' +
      '<button class="kb-btn danger" id="kb-cancel-share-yes">确认取消</button>' +
      '</div></div>';

    openModal(html, function (modal, close) {
      modal.querySelector("#kb-cancel-share-no").addEventListener("click", close);
      modal.querySelector("#kb-cancel-share-yes").addEventListener("click", async function () {
        try {
          var data = await fetchJson(apiBase + "/knowledge/shares/" + shareId + usernameParamNoAmp(), {
            method: "DELETE",
          });
          if (data.success) { showToast("已取消分享"); close(); refresh(); }
          else { showToast(data.error || "取消失败", "error"); }
        } catch (e) { showToast("取消分享失败: " + e.message, "error"); }
      });
    });
  }

  // ===== 移动文件弹窗 =====

  function showMoveFileModal(fileId, currentCategory) {
    var categories = state.categories.filter(function (c) { return c.name !== currentCategory; });
    if (!categories.length) {
      showToast("没有其他分类可移动", "error");
      return;
    }

    var optionsHtml = categories.map(function (c) {
      return '<option value="' + escapeHtml(c.name) + '">' + escapeHtml(c.display_name || c.name) + '</option>';
    }).join("");

    var html =
      '<div class="kb-modal kb-modal-sm">' +
      '<div class="kb-modal-title">移动文件</div>' +
      '<div class="kb-modal-body">' +
      '<label class="kb-label">移动到分类</label>' +
      '<select class="kb-input" id="kb-move-target-select">' + optionsHtml + '</select>' +
      '</div>' +
      '<div class="kb-modal-footer">' +
      '<button class="kb-btn" id="kb-move-cancel">取消</button>' +
      '<button class="kb-btn primary" id="kb-move-confirm">确认移动</button>' +
      '</div>' +
      '</div>';

    openModal(html, function (modal, close) {
      modal.querySelector("#kb-move-cancel").addEventListener("click", close);
      modal.querySelector("#kb-move-confirm").addEventListener("click", async function () {
        var targetCat = modal.querySelector("#kb-move-target-select").value;
        if (!targetCat) { showToast("请选择目标分类", "error"); return; }
        var btn = modal.querySelector("#kb-move-confirm");
        btn.disabled = true; btn.textContent = "移动中...";
        try {
          var data = await fetchJson(
            apiBase + "/knowledge/files/" + fileId + "/move?type=personal" + usernameParam(),
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ target_category: targetCat }),
            }
          );
          if (data.success) { showToast("移动成功"); close(); refresh(); }
          else { showToast(data.error || "移动失败", "error"); }
        } catch (e) { showToast("移动失败: " + e.message, "error"); }
        btn.disabled = false; btn.textContent = "确认移动";
      });
    });
  }

  refresh();

  return {
    refresh: refresh,
    /** 从联系人右键菜单进入分享模式，预填目标用户 */
    enterShareMode: function (targetUserName) {
      state.shareTargetUser = targetUserName || "";
      state.tab = "personal";
      state.currentCategory = null;
      refresh().then(function () {
        // 如果有预填目标用户，自动打开分享弹窗（选择文件后分享）
        if (state.shareTargetUser) {
          showShareModalWithTarget(state.shareTargetUser);
          state.shareTargetUser = "";
        }
      });
    },
  };
}

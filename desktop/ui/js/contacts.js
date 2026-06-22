export function createContactsController(options) {
  var contactsTree = options.contactsTree;
  var searchInput = options.searchInput;
  var searchClear = options.searchClear;
  var toggleBtn = options.toggleBtn;
  var rightPanel = options.rightPanel;
  var apiBase = options.apiBase || "";
  var getToken = options.getToken || function () { return ""; };

  var departments = [];
  var users = [];
  var expandedDepts = {};
  var searchQuery = "";

  /** 右键菜单DOM引用 */
  var contextMenu = null;

  /** 右键菜单动作回调列表 */
  var _actionCallbacks = {};

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /**
   * 将扁平部门列表构建为树形结构
   * 返回根部门数组，每个部门对象包含 _children 子部门数组
   */
  function buildDeptTree(flatDepts) {
    var map = {};
    var roots = [];
    for (var i = 0; i < flatDepts.length; i++) {
      var d = flatDepts[i];
      var copy = Object.assign({}, d, { _children: [] });
      map[d.id] = copy;
    }
    for (var j = 0; j < flatDepts.length; j++) {
      var dept = map[flatDepts[j].id];
      if (dept.parent_id && map[dept.parent_id]) {
        map[dept.parent_id]._children.push(dept);
      } else {
        roots.push(dept);
      }
    }
    return roots;
  }

  /**
   * 获取指定部门下的所有员工（仅直接下属）
   */
  function getUsersForDept(deptId) {
    var result = [];
    for (var i = 0; i < users.length; i++) {
      if (users[i].dept_id === deptId) {
        result.push(users[i]);
      }
    }
    return result;
  }

  /**
   * 计算部门下总人数（包含所有子部门的员工）
   */
  function countDeptTotal(dept) {
    var total = getUsersForDept(dept.id).length;
    for (var i = 0; i < dept._children.length; i++) {
      total += countDeptTotal(dept._children[i]);
    }
    return total;
  }

  function renderAvatar(name, isOnline) {
    var ch = (name || "?").charAt(0).toUpperCase();
    var statusClass = isOnline ? "contact-avatar online" : "contact-avatar";
    return '<span class="' + statusClass + '">' + escapeHtml(ch) + '</span>';
  }

  /**
   * 渲染部门节点（递归渲染子部门和员工）
   * 无论是否展开，都渲染全部内容到DOM中，通过CSS控制显示/隐藏
   */
  function renderDeptNode(dept, depth) {
    var isExpanded = !!expandedDepts[dept.id];
    var deptUsers = getUsersForDept(dept.id);
    var indent = depth * 16;
    var chevronClass = isExpanded ? "dept-chevron rotated" : "dept-chevron";
    var childHtml = "";

    for (var c = 0; c < dept._children.length; c++) {
      childHtml += renderDeptNode(dept._children[c], depth + 1);
    }
    for (var u = 0; u < deptUsers.length; u++) {
      childHtml += renderUserNode(deptUsers[u], depth + 1);
    }

    var totalCount = countDeptTotal(dept);
    var hasChildren = dept._children.length > 0 || deptUsers.length > 0;

    return (
      '<div class="dept-node" data-dept-id="' + escapeHtml(dept.id) + '">' +
        '<div class="dept-header" style="padding-left:' + indent + 'px">' +
          (hasChildren
            ? '<span class="' + chevronClass + '">▸</span>'
            : '<span class="dept-chevron-placeholder"></span>') +
          '<span class="dept-icon">📁</span>' +
          '<span class="dept-name">' + escapeHtml(dept.name) + '</span>' +
          '<span class="dept-count">' + totalCount + '</span>' +
        '</div>' +
        '<div class="dept-children' + (isExpanded ? '' : ' hidden') + '">' +
          childHtml +
        '</div>' +
      '</div>'
    );
  }

  /**
   * 渲染员工节点
   * 显示员工名称(name)、在线状态指示器、职位信息
   */
  function renderUserNode(user, depth) {
    var indent = depth * 16;
    var displayName = user.name || user.username || "—";
    var title = user.title || user.position || "";
    var isOnline = !!user.is_online;

    return (
      '<div class="contact-node" data-user-id="' + escapeHtml(user.id || "") + '" data-user-name="' + escapeHtml(displayName) + '">' +
        '<div class="contact-row" style="padding-left:' + indent + 'px">' +
          renderAvatar(displayName, isOnline) +
          '<div class="contact-info">' +
            '<span class="contact-name">' + escapeHtml(displayName) + '</span>' +
            (title ? '<span class="contact-title">' + escapeHtml(title) + '</span>' : '') +
          '</div>' +
          '<span class="contact-status-dot ' + (isOnline ? 'online' : 'offline') + '" title="' + (isOnline ? '在线' : '离线') + '"></span>' +
        '</div>' +
      '</div>'
    );
  }

  /**
   * 根据搜索关键词过滤部门树
   */
  function filterBySearch(tree, query) {
    if (!query) return tree;
    var q = query.toLowerCase();
    var result = [];
    for (var i = 0; i < tree.length; i++) {
      var dept = tree[i];
      var deptMatch = (dept.name || "").toLowerCase().indexOf(q) >= 0;
      var filteredChildren = filterBySearch(dept._children, query);
      var filteredUsers = [];
      var directUsers = getUsersForDept(dept.id);
      for (var u = 0; u < directUsers.length; u++) {
        var uname = (directUsers[u].name || directUsers[u].username || "").toLowerCase();
        var utitle = (directUsers[u].title || directUsers[u].position || "").toLowerCase();
        if (uname.indexOf(q) >= 0 || utitle.indexOf(q) >= 0) {
          filteredUsers.push(directUsers[u]);
        }
      }
      if (deptMatch || filteredChildren.length > 0 || filteredUsers.length > 0) {
        var clone = Object.assign({}, dept, {
          _children: filteredChildren,
          _filteredUsers: filteredUsers
        });
        result.push(clone);
      }
    }
    return result;
  }

  function renderTree() {
    if (!contactsTree) return;
    if (departments.length === 0 && users.length === 0) {
      contactsTree.innerHTML = '<div class="contacts-empty">暂无联系人数据</div>';
      return;
    }
    var tree = buildDeptTree(departments);
    if (searchQuery) {
      tree = filterBySearch(tree, searchQuery);
      for (var i = 0; i < departments.length; i++) {
        expandedDepts[departments[i].id] = true;
      }
    }
    var html = "";
    for (var j = 0; j < tree.length; j++) {
      html += renderDeptNode(tree[j], 0);
    }
    var orphanUsers = users.filter(function (u) { return !u.dept_id; });
    for (var k = 0; k < orphanUsers.length; k++) {
      html += renderUserNode(orphanUsers[k], 0);
    }
    if (!html) {
      contactsTree.innerHTML = '<div class="contacts-empty">未找到匹配的联系人</div>';
      return;
    }
    contactsTree.innerHTML = html;
    bindDeptToggles();
    bindContactContextMenus();
  }

  /**
   * 绑定部门展开/折叠点击事件
   */
  function bindDeptToggles() {
    if (!contactsTree) return;
    var headers = contactsTree.querySelectorAll(".dept-header");
    for (var i = 0; i < headers.length; i++) {
      headers[i].addEventListener("click", function () {
        var node = this.closest(".dept-node");
        if (!node) return;
        var deptId = node.getAttribute("data-dept-id");
        var children = node.querySelector(".dept-children");
        var chevron = this.querySelector(".dept-chevron");
        if (expandedDepts[deptId]) {
          delete expandedDepts[deptId];
          if (children) children.classList.add("hidden");
          if (chevron) chevron.classList.remove("rotated");
        } else {
          expandedDepts[deptId] = true;
          if (children) children.classList.remove("hidden");
          if (chevron) chevron.classList.add("rotated");
        }
      });
    }
  }

  /**
   * 创建右键菜单DOM（全局单例）
   */
  function ensureContextMenu() {
    if (contextMenu) return;
    contextMenu = document.createElement("div");
    contextMenu.className = "contact-context-menu";
    contextMenu.innerHTML =
      '<div class="context-menu-item" data-action="send-task">' +
        '<span class="context-menu-icon">📋</span>' +
        '<span class="context-menu-label">发送任务</span>' +
      '</div>' +
      '<div class="context-menu-item" data-action="share-knowledge">' +
        '<span class="context-menu-icon">📚</span>' +
        '<span class="context-menu-label">共享知识库</span>' +
      '</div>';
    document.body.appendChild(contextMenu);

    // 点击菜单项时触发对应回调
    var items = contextMenu.querySelectorAll(".context-menu-item");
    for (var i = 0; i < items.length; i++) {
      items[i].addEventListener("click", function () {
        var action = this.getAttribute("data-action");
        var userId = contextMenu.getAttribute("data-user-id");
        var userName = contextMenu.getAttribute("data-user-name");
        hideContextMenu();
        // 触发注册的回调
        if (_actionCallbacks[action]) {
          _actionCallbacks[action](userId, userName);
        }
      });
    }
  }

  /**
   * 显示右键菜单
   */
  function showContextMenu(x, y, userId, userName) {
    ensureContextMenu();
    contextMenu.setAttribute("data-user-id", userId);
    contextMenu.setAttribute("data-user-name", userName);
    contextMenu.style.left = x + "px";
    contextMenu.style.top = y + "px";
    contextMenu.classList.add("visible");

    // 边界检测：确保菜单不超出视口
    requestAnimationFrame(function () {
      var rect = contextMenu.getBoundingClientRect();
      if (rect.right > window.innerWidth) {
        contextMenu.style.left = (x - rect.width) + "px";
      }
      if (rect.bottom > window.innerHeight) {
        contextMenu.style.top = (y - rect.height) + "px";
      }
    });
  }

  function hideContextMenu() {
    if (contextMenu) {
      contextMenu.classList.remove("visible");
    }
  }

  /**
   * 绑定联系人节点的右键菜单事件
   */
  function bindContactContextMenus() {
    if (!contactsTree) return;
    var nodes = contactsTree.querySelectorAll(".contact-node");
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].addEventListener("contextmenu", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var userId = this.getAttribute("data-user-id");
        var userName = this.getAttribute("data-user-name");
        showContextMenu(e.clientX, e.clientY, userId, userName);
      });
    }
  }

  async function loadContacts() {
    if (!apiBase) return;
    var token = getToken();
    var headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = "Bearer " + token;

    try {
      var deptRes = await fetch(apiBase + "/api/desktop/contacts/departments", {
        method: "GET",
        headers: headers,
        cache: "no-store",
      });
      var deptData = await deptRes.json();
      if (deptData && deptData.ok && Array.isArray(deptData.departments)) {
        departments = deptData.departments;
      } else {
        departments = [];
      }
    } catch (e) {
      console.error("加载部门列表失败: " + (e.message || e));
      departments = [];
    }

    try {
      var userRes = await fetch(apiBase + "/api/desktop/contacts/users", {
        method: "GET",
        headers: headers,
        cache: "no-store",
      });
      var userData = await userRes.json();
      if (userData && userData.ok && Array.isArray(userData.users)) {
        users = userData.users;
      } else {
        users = [];
      }
    } catch (e) {
      console.error("加载用户列表失败: " + (e.message || e));
      users = [];
    }

    renderTree();
  }

  function bindEvents() {
    if (searchInput) {
      searchInput.addEventListener("input", function () {
        searchQuery = (searchInput.value || "").trim();
        if (searchClear) {
          searchClear.classList.toggle("hidden", !searchQuery);
        }
        renderTree();
      });
    }
    if (searchClear) {
      searchClear.addEventListener("click", function () {
        if (searchInput) searchInput.value = "";
        searchQuery = "";
        searchClear.classList.add("hidden");
        renderTree();
      });
    }
    if (toggleBtn && rightPanel) {
      toggleBtn.addEventListener("click", function () {
        rightPanel.classList.toggle("collapsed");
        var isCollapsed = rightPanel.classList.contains("collapsed");
        toggleBtn.textContent = isCollapsed ? "▸" : "◂";
        toggleBtn.title = isCollapsed ? "展开面板" : "折叠面板";
      });
    }

    // 点击页面其他区域时隐藏右键菜单
    document.addEventListener("click", function (e) {
      if (contextMenu && !contextMenu.contains(e.target)) {
        hideContextMenu();
      }
    });
    // ESC 键隐藏右键菜单
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        hideContextMenu();
      }
    });
  }

  bindEvents();

  return {
    loadContacts: loadContacts,
    refresh: loadContacts,
    /** 注册右键菜单动作回调，如 onAction("share-knowledge", function(userId, userName){...}) */
    onAction: function (action, callback) {
      _actionCallbacks[action] = callback;
    },
  };
}

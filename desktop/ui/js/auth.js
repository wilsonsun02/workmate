import { initial } from "./ids.js";
import { getSession, setSession, clearSession } from "./storage.js";

export function createAuthController(options) {
  var apiBase = options.apiBase;
  var adminApiBase = options.adminApiBase || apiBase;
  var loginScreen = options.loginScreen;
  var appShell = options.appShell;
  var loginForm = options.loginForm;
  var loginError = options.loginError;
  var loginSubmit = options.loginSubmit;
  var loginTerms = options.loginTerms;
  var loginClose = options.loginClose;
  var sidebarUsername = options.sidebarUsername;
  var sidebarAvatar = options.sidebarAvatar;
  var settingsAvatar = options.settingsAvatar;
  var settingsUsername = options.settingsUsername;
  var onLogoutDone = options.onLogoutDone || function () {};
  var onSessionChange = options.onSessionChange || function () {};
  var onAdminSkillsSync = options.onAdminSkillsSync || function () {};
  var onCollabNotification = options.onCollabNotification || function () {};
  var installSkillHandler =
    options.installSkillHandler ||
    function () {
      return Promise.resolve({ ok: true });
    };
  var onlineSocket = null;
  var onlineSocketToken = "";
  var onlineReconnectTimer = null;
  var onlinePingTimer = null;
  var onlineReconnectEnabled = false;
  var lastAdminSkillsConfigPayload = null;
  var lastAdminSkillMarketList = null;
  var lastAdminSkillsCatalog = null;
  var receivedAdminConfigSync = false;
  var receivedAdminSkillMarket = false;
  var installChain = Promise.resolve();

  function resetInstallChain() {
    installChain = Promise.resolve();
  }

  function resetAdminSkillsSyncState() {
    lastAdminSkillsConfigPayload = null;
    lastAdminSkillMarketList = null;
    lastAdminSkillsCatalog = null;
    receivedAdminConfigSync = false;
    receivedAdminSkillMarket = false;
  }

  function extractGlobalSkillsMap(skillsConfigRaw) {
    if (!skillsConfigRaw || typeof skillsConfigRaw !== "object") return {};
    var node = skillsConfigRaw.skills;
    if (node && typeof node === "object" && !Array.isArray(node)) return node;
    var out = {};
    Object.keys(skillsConfigRaw).forEach(function (k) {
      if (k === "skills") return;
      var v = skillsConfigRaw[k];
      if (v && typeof v === "object" && !Array.isArray(v)) out[k] = v;
    });
    return out;
  }

  function mergeEffectiveSkillsFromAdmin(skillsConfigRaw, skillMarketList) {
    var G = extractGlobalSkillsMap(skillsConfigRaw);
    var marketByName = Object.create(null);
    var marketByNameLower = Object.create(null);
    (Array.isArray(skillMarketList) ? skillMarketList : []).forEach(function (item) {
      if (item && item.name) {
        var raw = String(item.name);
        marketByName[raw] = item;
        marketByNameLower[raw.toLowerCase()] = item;
      }
    });
    function marketEntryFor(name) {
      var n = String(name || "");
      return marketByName[n] || marketByNameLower[n.toLowerCase()] || null;
    }
    var merged = {};
    Object.keys(G).forEach(function (name) {
      var g = G[name] || {};
      var m = marketEntryFor(name);
      var inMarket = !!m;
      merged[name] = {
        description:
          String(g.description || "").trim() ||
          String((m && m.description) || "").trim(),
        enabled: inMarket,
      };
    });
    Object.keys(marketByName).forEach(function (name) {
      if (merged[name]) return;
      var m = marketByName[name];
      merged[name] = {
        description: String((m && m.description) || "").trim(),
        enabled: true,
      };
    });
    return { skills: merged };
  }

  function buildAuthorizedSkillNameSet(skillMarketList) {
    var allowed = Object.create(null);
    (Array.isArray(skillMarketList) ? skillMarketList : []).forEach(function (item) {
      if (item && item.name) allowed[String(item.name)] = true;
    });
    return allowed;
  }

  function buildAdminSkillsCatalogView(skillsConfigRaw, skillsCatalogList, skillMarketList) {
    var G = extractGlobalSkillsMap(skillsConfigRaw);
    var allowed = buildAuthorizedSkillNameSet(skillMarketList);
    var catalog = Array.isArray(skillsCatalogList) ? skillsCatalogList : [];
    var view = {};
    if (catalog.length) {
      catalog.forEach(function (item) {
        if (!item || !item.name) return;
        var name = String(item.name);
        view[name] = {
          description: String(item.description || "").trim(),
          enabled: item.enabled !== false,
          authorized: !!allowed[name],
        };
      });
      return { skills: view, source: "catalog" };
    }
    Object.keys(G).forEach(function (name) {
      var g = G[name] || {};
      if (g.deleted) return;
      view[name] = {
        description: String(g.description || "").trim(),
        enabled: g.enabled !== false,
        authorized: !!allowed[name],
      };
    });
    if (!Object.keys(view).length) return null;
    return { skills: view, source: "global" };
  }

  function getAdminSkillsCatalogView() {
    if (!receivedAdminConfigSync) return null;
    return buildAdminSkillsCatalogView(
      lastAdminSkillsConfigPayload,
      lastAdminSkillsCatalog,
      lastAdminSkillMarketList
    );
  }

  function tryEmitAdminSkillsMerge() {
    if (!receivedAdminConfigSync || !receivedAdminSkillMarket) return;
    if (!getSession() || !getSession().token) return;
    var merged = mergeEffectiveSkillsFromAdmin(
      lastAdminSkillsConfigPayload,
      lastAdminSkillMarketList
    );
    var market = Array.isArray(lastAdminSkillMarketList) ? lastAdminSkillMarketList : [];
    onAdminSkillsSync(merged, market);
  }

  function sendOnlineMessage(obj) {
    if (!onlineSocket || onlineSocket.readyState !== WebSocket.OPEN) return;
    try {
      onlineSocket.send(JSON.stringify(obj || {}));
    } catch (e) {
      /* ignore */
    }
  }

  function enqueueSkillInstall(task) {
    if (!task || !task.skill_name || !task.version) return;
    installChain = installChain
      .then(function () {
        var p = Promise.resolve()
          .then(function () {
            return installSkillHandler(task);
          })
          .then(function (r) {
            var ok = !!(r && r.ok);
            var tid = task.task_id;
            if (tid && getSession() && getSession().token) {
              sendOnlineMessage({
                action: "install_status",
                task_id: tid,
                status: ok ? "success" : "failed",
                error_message: ok ? undefined : String((r && r.message) || "failed"),
              });
            }
            return r;
          });
        return p;
      })
      .catch(function (e) {
        var tid = task.task_id;
        if (tid && getSession() && getSession().token) {
          sendOnlineMessage({
            action: "install_status",
            task_id: tid,
            status: "failed",
            error_message: String((e && e.message) || e || "error"),
          });
        }
      });
  }

  function whenInstallsIdle() {
    return installChain;
  }

  function buildAdminUrl(path) {
    var base = String(adminApiBase || apiBase || "").replace(/\/$/, "");
    var suffix = String(path || "");
    if (base.endsWith("/api/admin") && suffix.indexOf("/api/admin/") === 0) {
      suffix = suffix.slice("/api/admin".length);
    }
    return base + suffix;
  }

  function buildAdminWsUrl() {
    var url = new URL(buildAdminUrl("/api/admin/client/ws"), window.location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
  }

  function clearOnlineTimers() {
    if (onlineReconnectTimer) {
      clearTimeout(onlineReconnectTimer);
      onlineReconnectTimer = null;
    }
    if (onlinePingTimer) {
      clearInterval(onlinePingTimer);
      onlinePingTimer = null;
    }
  }

  function closeOnlineSocket() {
    clearOnlineTimers();
    onlineReconnectEnabled = false;
    onlineSocketToken = "";
    resetAdminSkillsSyncState();
    resetInstallChain();
    if (onlineSocket) {
      try {
        onlineSocket.close();
      } catch (e) {
        /* ignore */
      }
      onlineSocket = null;
    }
  }

  function scheduleOnlineReconnect() {
    if (!onlineReconnectEnabled || !onlineSocketToken || onlineReconnectTimer) return;
    onlineReconnectTimer = setTimeout(function () {
      onlineReconnectTimer = null;
      connectOnlineSocket(onlineSocketToken);
    }, 5000);
  }

  function connectOnlineSocket(token) {
    if (!token) return;
    clearOnlineTimers();
    onlineSocketToken = token;
    onlineReconnectEnabled = true;
    try {
      onlineSocket = new WebSocket(buildAdminWsUrl());
    } catch (e) {
      scheduleOnlineReconnect();
      return;
    }
    onlineSocket.addEventListener("open", function () {
      resetAdminSkillsSyncState();
      resetInstallChain();
      onlineSocket.send(JSON.stringify({ action: "token_login", token: token }));
      onlineSocket.send(
        JSON.stringify({ action: "client_status_report", status: "idle", current_task: null })
      );
      onlinePingTimer = setInterval(function () {
        if (onlineSocket && onlineSocket.readyState === WebSocket.OPEN) {
          onlineSocket.send(JSON.stringify({ action: "ping" }));
        }
      }, 30000);
    });
    onlineSocket.addEventListener("message", function (event) {
      var msg = {};
      try {
        msg = JSON.parse(event.data || "{}");
      } catch (e) {
        msg = {};
      }
      if (msg.action === "error") {
        onlineReconnectEnabled = false;
        if (onlineSocket) onlineSocket.close();
        return;
      }
      if (msg.action === "config_sync") {
        lastAdminSkillsConfigPayload = msg.skills_config != null ? msg.skills_config : {};
        lastAdminSkillsCatalog = Array.isArray(msg.skills_catalog) ? msg.skills_catalog : [];
        receivedAdminConfigSync = true;
        var env = msg.env_config || {};
        var mode = String(env.SKILL_INSTALL_TRIGGER_MODE || "hybrid").toLowerCase();
        if (
          (mode === "passive" || mode === "hybrid") &&
          onlineSocket &&
          onlineSocket.readyState === WebSocket.OPEN
        ) {
          try {
            onlineSocket.send(JSON.stringify({ action: "pull_install_tasks" }));
          } catch (e) {
            /* ignore */
          }
        }
        tryEmitAdminSkillsMerge();

        // 同步安全规则到桌面端本地文件
        if (msg.content_security_rules && typeof msg.content_security_rules === "object") {
          try {
            fetch(apiBase + "/api/desktop/content_security_rules", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ rules: msg.content_security_rules })
            });
          } catch (e) {
            /* ignore */
          }
        }
        return;
      }
      if (msg.action === "skill_market") {
        lastAdminSkillMarketList = Array.isArray(msg.skills) ? msg.skills : [];
        receivedAdminSkillMarket = true;
        tryEmitAdminSkillsMerge();
        return;
      }
      if (msg.action === "install_skill") {
        enqueueSkillInstall(msg);
        return;
      }
      if (msg.action === "install_tasks") {
        (Array.isArray(msg.tasks) ? msg.tasks : []).forEach(function (t) {
          enqueueSkillInstall(t);
        });
        return;
      }
      if (
        msg.action === "collab_task_assigned" ||
        msg.action === "collab_chain_completed" ||
        msg.action === "collab_chain_progress" ||
        msg.action === "collab_step_rejected"
      ) {
        onCollabNotification(msg);
        return;
      }
    });
    onlineSocket.addEventListener("close", function () {
      onlineSocket = null;
      clearOnlineTimers();
      scheduleOnlineReconnect();
    });
    onlineSocket.addEventListener("error", function () {
      if (onlineSocket) onlineSocket.close();
    });
  }

  function syncOnlineSocket(session) {
    var token = session && session.token ? session.token : "";
    if (!token) {
      closeOnlineSocket();
      return;
    }
    if (
      onlineSocket &&
      onlineSocketToken === token &&
      (onlineSocket.readyState === WebSocket.OPEN ||
        onlineSocket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    closeOnlineSocket();
    connectOnlineSocket(token);
  }

  function showLogin() {
    loginScreen.classList.remove("hidden");
    loginScreen.setAttribute("aria-hidden", "false");
    appShell.classList.add("dimmed");
  }

  function hideLogin() {
    loginScreen.classList.add("hidden");
    loginScreen.setAttribute("aria-hidden", "true");
    appShell.classList.remove("dimmed");
  }

  function setLoginError(message) {
    loginError.textContent = message || "";
  }

  async function syncCollabTokenToAgent(token) {
    try {
      await fetch(apiBase + "/api/desktop/set_collab_token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token || "" }),
      });
    } catch (e) {
      /* ignore */
    }
  }

  function resolveUserDisplayName(sessionUser) {
    if (!sessionUser || typeof sessionUser !== "object") return "";
    var name = String(sessionUser.name || "").trim();
    if (name) return name;
    return String(sessionUser.username || "").trim();
  }

  function resolveMateDisplayName(sessionUser) {
    return resolveUserDisplayName(sessionUser);
  }

  async function refreshSessionUserProfile(session) {
    if (!session || !session.token) return session;
    if (session.user && String(session.user.name || "").trim()) return session;
    try {
      var res = await fetch(adminApiBase + "/api/admin/auth/me", {
        headers: { Authorization: "Bearer " + session.token },
      });
      var data = await res.json().catch(function () {
        return {};
      });
      if (!res.ok || !data.success || !data.user) return session;
      var mergedUser = Object.assign({}, session.user || {}, data.user);
      if (session.user && session.user.username) {
        mergedUser.username = session.user.username;
      }
      var next = { token: session.token, user: mergedUser };
      setSession(next);
      return next;
    } catch (e) {
      return session;
    }
  }

  async function syncActiveUsernameToBackend(sessionUser) {
    var username = sessionUser && sessionUser.username ? String(sessionUser.username).trim() : "";
    if (!username) return;
    var mateName = resolveMateDisplayName(sessionUser) || username;
    await fetch(apiBase + "/api/desktop/set_active_username", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username, mate_name: mateName }),
    });
  }

  async function applySessionToUI(session) {
    var displayName = "未登录";
    if (session && session.user) {
      displayName = resolveUserDisplayName(session.user) || "未登录";
    }
    sidebarUsername.textContent = displayName;
    sidebarAvatar.textContent = displayName === "未登录" ? "?" : initial(displayName);
    settingsUsername.textContent = displayName === "未登录" ? "—" : displayName;
    settingsAvatar.textContent = displayName === "未登录" ? "?" : initial(displayName);
    if (loginClose) {
      loginClose.style.display = session ? "" : "none";
    }
    syncOnlineSocket(session || null);
    if (session && session.token) {
      syncCollabTokenToAgent(session.token);
      var activeSession = session;
      var needsProfile =
        session.user && !String(session.user.name || "").trim();
      var profilePromise = needsProfile
        ? refreshSessionUserProfile(session).then(function (next) {
            activeSession = next || session;
            if (activeSession !== session) {
              applySessionToUI(activeSession);
            }
            return activeSession;
          })
        : Promise.resolve(session);
      profilePromise
        .then(function (s) {
          return syncActiveUsernameToBackend((s || activeSession).user);
        })
        .catch(function () {
          /* ignore: backend may be unavailable during boot */
        });
    } else {
      syncCollabTokenToAgent("");
    }
    await onSessionChange(session || null);
  }

  function bindLoginForm() {
    loginForm.addEventListener("submit", async function (e) {
      e.preventDefault();
      setLoginError("");
      if (!loginTerms.checked) {
        setLoginError("请先阅读并勾选服务协议与隐私协议。");
        return;
      }
      var username = document.getElementById("login-user").value.trim();
      var password = document.getElementById("login-pass").value;
      loginSubmit.disabled = true;
      try {
        var res = await fetch(adminApiBase + "/api/admin/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: username, password: password }),
        });
        var data = await res.json().catch(function () {
          return {};
        });
        if (!res.ok) {
          var detail = data.detail;
          if (Array.isArray(detail)) {
            detail = detail
              .map(function (x) {
                return x.msg || JSON.stringify(x);
              })
              .join("；");
          }
          setLoginError(
            detail ||
              data.message ||
              "登录失败（" + res.status + "）。请确认后端已启动且账号密码正确。"
          );
          return;
        }
        if (!data.success || !data.token) {
          setLoginError("登录响应异常，请稍后重试。");
          return;
        }
        // 以"登录框输入账号"作为前端会话隔离主键，避免后端返回用户名不稳定导致串号
        var loginIdentity = username;
        var mergedUser = Object.assign({}, data.user || {}, { username: loginIdentity });
        setSession({ token: data.token, user: mergedUser });
        loginSubmit.disabled = true;
        loginSubmit.textContent = "加载中…";
        try {
          await applySessionToUI(getSession());
        } catch (_e) {
          /* 数据加载失败不阻塞登录流程 */
        }
        hideLogin();
        appShell.classList.remove("dimmed");
        loginForm.reset();
        loginTerms.checked = false;
      } catch (err) {
        setLoginError("无法连接管理服务（" + adminApiBase + "）。请启动 admin_serve.py 或检查 admin_api_base 参数。");
      } finally {
        loginSubmit.disabled = false;
        loginSubmit.textContent = "登录";
      }
    });
  }

  function bindLoginClose() {
    if (!loginClose) return;
    loginClose.addEventListener("click", function () {
      if (getSession()) hideLogin();
    });
  }

  function isAdminOnlineConnected() {
    return !!(
      onlineSocket &&
      onlineSocket.readyState === WebSocket.OPEN &&
      getSession() &&
      getSession().token
    );
  }

  function bindLogout(btnLogout, closeSettings) {
    btnLogout.addEventListener("click", async function () {
      var s = getSession();
      if (s && s.token) {
        try {
          await fetch(adminApiBase + "/api/admin/auth/logout?token=" + encodeURIComponent(s.token), {
            method: "POST",
          });
        } catch (e) {
          /* ignore */
        }
      }
      await syncCollabTokenToAgent("");
      clearSession();
      if (typeof closeSettings === "function") closeSettings();
      applySessionToUI(null);
      appShell.classList.add("dimmed");
      showLogin();
      onLogoutDone();
    });
  }

  return {
    showLogin: showLogin,
    hideLogin: hideLogin,
    setLoginError: setLoginError,
    applySessionToUI: applySessionToUI,
    bindLoginForm: bindLoginForm,
    bindLoginClose: bindLoginClose,
    bindLogout: bindLogout,
    sendOnlineMessage: sendOnlineMessage,
    enqueueSkillInstall: enqueueSkillInstall,
    whenInstallsIdle: whenInstallsIdle,
    isAdminOnlineConnected: isAdminOnlineConnected,
    getAdminSkillsCatalogView: getAdminSkillsCatalogView,
    getAuthorizedSkillNames: function () {
      return buildAuthorizedSkillNameSet(lastAdminSkillMarketList);
    },
  };
}

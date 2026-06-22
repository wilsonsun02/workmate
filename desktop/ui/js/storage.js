import { genId } from "./ids.js";

export var SESSION_KEY = "workmate_desktop_session";
export var PREFS_KEY = "workmate_desktop_prefs";
export var CHATS_KEY = "workmate_desktop_chats";
export var DESKTOP_CFG_OVERRIDE_KEY = "workmate_desktop_cfg_override";

var WELCOME_MESSAGES = [
  {
    role: "assistant",
    text: "你好，我是 Workmate 助手。登录后可与后端服务联动；对话流式能力可在后续版本接入。",
  },
  { role: "user", text: "你好" },
];

export function getSession() {
  try {
    var raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

export function setSession(data) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(data));
}

export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}

export function getPrefs() {
  try {
    var raw = localStorage.getItem(PREFS_KEY);
    if (!raw) return { security: true, sleep: false, tools: false };
    return Object.assign({ security: true, sleep: false, tools: false }, JSON.parse(raw));
  } catch (e) {
    return { security: true, sleep: false, tools: false };
  }
}

export function savePrefs(p) {
  localStorage.setItem(PREFS_KEY, JSON.stringify(p));
}

export function getDesktopConfigOverride() {
  try {
    var raw = localStorage.getItem(DESKTOP_CFG_OVERRIDE_KEY);
    if (!raw) return {};
    var parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (e) {
    return {};
  }
}

export function saveDesktopConfigOverride(data) {
  localStorage.setItem(DESKTOP_CFG_OVERRIDE_KEY, JSON.stringify(data || {}));
}

export function clearDesktopConfigOverride() {
  localStorage.removeItem(DESKTOP_CFG_OVERRIDE_KEY);
}

function defaultChatState() {
  return {
    version: 1,
    activeId: null,
    conversations: [],
  };
}

export function createDefaultChatState() {
  return defaultChatState();
}

function normalizeUsername(username) {
  return String(username || "").trim();
}

function getChatStorageKey(username) {
  var u = normalizeUsername(username);
  return u ? CHATS_KEY + ":" + u : CHATS_KEY;
}

export function loadChatStateForUser(username) {
  var u = normalizeUsername(username);
  // 关键规则：已登录用户只读自己的隔离 key，避免串到历史全局会话
  var storageKey = u ? getChatStorageKey(u) : CHATS_KEY;
  try {
    var raw = localStorage.getItem(storageKey);
    if (!raw) {
      var seed = createDefaultChatState();
      saveChatStateForUser(username, seed);
      return seed;
    }
    var data = JSON.parse(raw);
    if (!data.conversations || !Array.isArray(data.conversations)) {
      var s = createDefaultChatState();
      saveChatStateForUser(username, s);
      return s;
    }
    data.conversations.forEach(function (c) {
      if (!Array.isArray(c.messages)) c.messages = [];
      if (typeof c.title !== "string") c.title = "对话";
      c.messages.forEach(function (m) {
        if (m.streaming) {
          m.text = m.text && m.text !== "正在思考…" ? m.text : "（上次回复未完成）";
          delete m.streaming;
        }
      });
    });
    if (!data.activeId && data.conversations.length) {
      data.activeId = data.conversations[0].id;
    }
    var found = data.conversations.some(function (c) {
      return c.id === data.activeId;
    });
    if (!found && data.conversations.length) {
      data.activeId = data.conversations[0].id;
      saveChatStateForUser(username, data);
    }
    return data;
  } catch (e) {
    var fallback = createDefaultChatState();
    saveChatStateForUser(username, fallback);
    return fallback;
  }
}

export function resetChatStateForUser(username) {
  var fresh = createDefaultChatState();
  saveChatStateForUser(username, fresh);
  return fresh;
}

export function saveChatStateForUser(username, state) {
  var storageKey = getChatStorageKey(username);
  localStorage.setItem(storageKey, JSON.stringify(state));
}

// 兼容旧调用
export function loadChatState() {
  return loadChatStateForUser("");
}

export function saveChatState(state) {
  saveChatStateForUser("", state);
}

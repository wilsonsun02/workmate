function trimMsgText(t) {
  return String(t != null ? t : "").trim();
}

/** 与 workflow/workflow_core.py 中 _SOURCE_PREFIX_PATTERNS 保持一致 */
const SOURCE_PREFIX_PATTERNS = [
  "【workmate桌面端】",
  "【定时任务】",
  "【协同任务】",
  "【企业微信】",
];

/* ── 旧格式正则（兼容历史对话） ── */
const SKILLS_INJECTED_PREFIX_PATTERN =
  /^\s*¥¥\[User has selected the following skills for this message\. You MUST load and use them by reading their SKILL\.md files:\s*([\s\S]*?)\]¥¥(?:\r?\n\s*\r?\n|\r?\n)?/;
const SKILLS_INJECTED_PREFIX_HEAD_PATTERN = /^\s*¥¥\[User has selected[\s\S]*$/i;

const MCP_INJECTED_PREFIX_PATTERN =
  /^\s*¥¥\[User has selected the following MCP tools for this message\. You MUST call these MCP tools:\s*([\s\S]*?)\]¥¥(?:\r?\n\s*\r?\n|\r?\n)?/;
const MCP_INJECTED_PREFIX_HEAD_PATTERN = /^\s*¥¥\[User has selected the following MCP tools[\s\S]*$/i;

const USER_NOTE_MARKER = "【用户说明】";

/* ── 新格式 XML 标签正则 ── */
const XML_SKILLS_PATTERN = /<skills>([\s\S]*?)<\/skills>/g;
const XML_MCP_TOOLS_PATTERN = /<mcp-tools>([\s\S]*?)<\/mcp-tools>/g;
const XML_KNOWLEDGE_PATTERN = /<knowledge>([\s\S]*?)<\/knowledge>/g;
const XML_ATTACHMENT_PATTERN = /<attachment>([\s\S]*?)<\/attachment>/g;

/* ── 旧格式知识库/附件正则（兼容历史对话） ── */
const LEGACY_KNOWLEDGE_PATTERN = /【知识库文件（以下为摘要内容）】\n\n([\s\S]*?)(?=\n\n【用户说明】|\n*$)/;
const LEGACY_ATTACHMENT_PATTERN = /【桌面端上传的附件（已自动解析）】\n\n([\s\S]*?)\n\n【用户说明】/;

export function stripSourcePrefix(text) {
  var t = String(text != null ? text : "");
  for (var i = 0; i < SOURCE_PREFIX_PATTERNS.length; i++) {
    var prefix = SOURCE_PREFIX_PATTERNS[i];
    if (t.startsWith(prefix)) {
      return t.slice(prefix.length);
    }
  }
  return t;
}

/**
 * 从文本中提取 skills 列表并剥离注入块
 * 同时支持新格式 <skills>...</skills> 和旧格式 ¥¥[...]¥¥
 */
export function parseSkillsInjectedPayload(text) {
  var src = stripSourcePrefix(String(text != null ? text : ""));
  var next = src;
  var skills = [];

  // 新格式：<skills>skill1, skill2</skills>
  var xmlMatches = next.match(XML_SKILLS_PATTERN);
  if (xmlMatches) {
    xmlMatches.forEach(function (block) {
      var inner = block.replace(/<skills>/, "").replace(/<\/skills>/, "");
      inner.split(",").map(trimMsgText).filter(Boolean).forEach(function (name) {
        if (skills.indexOf(name) < 0) skills.push(name);
      });
    });
    next = next.replace(XML_SKILLS_PATTERN, "");
  }

  // 旧格式：¥¥[User has selected the following skills...]¥¥
  while (true) {
    var m = next.match(SKILLS_INJECTED_PREFIX_PATTERN);
    if (!m) break;
    var rawSkills = String(m[1] || "");
    rawSkills
      .split(",")
      .map(function (n) { return trimMsgText(n); })
      .filter(Boolean)
      .forEach(function (name) {
        if (skills.indexOf(name) < 0) skills.push(name);
      });
    next = next.replace(SKILLS_INJECTED_PREFIX_PATTERN, "");
  }

  return { text: next.trim(), skills: skills };
}

/**
 * 从文本中提取 MCP 工具列表并剥离注入块
 * 同时支持新格式 <mcp-tools>...</mcp-tools> 和旧格式 ¥¥[...]¥¥
 */
export function parseMcpInjectedPayload(text) {
  var next = String(text != null ? text : "");
  var mcpTools = [];

  // 新格式：<mcp-tools>tool1, tool2</mcp-tools>
  var xmlMatches = next.match(XML_MCP_TOOLS_PATTERN);
  if (xmlMatches) {
    xmlMatches.forEach(function (block) {
      var inner = block.replace(/<mcp-tools>/, "").replace(/<\/mcp-tools>/, "");
      inner.split(",").map(trimMsgText).filter(Boolean).forEach(function (name) {
        if (mcpTools.indexOf(name) < 0) mcpTools.push(name);
      });
    });
    next = next.replace(XML_MCP_TOOLS_PATTERN, "");
  }

  // 旧格式：¥¥[User has selected the following MCP tools...]¥¥
  while (true) {
    var m = next.match(MCP_INJECTED_PREFIX_PATTERN);
    if (!m) break;
    var rawTools = String(m[1] || "");
    rawTools
      .split(",")
      .map(function (n) { return trimMsgText(n); })
      .filter(Boolean)
      .forEach(function (name) {
        if (mcpTools.indexOf(name) < 0) mcpTools.push(name);
      });
    next = next.replace(MCP_INJECTED_PREFIX_PATTERN, "");
  }

  return { text: next.trim(), mcpTools: mcpTools };
}

/**
 * 从文本中提取知识库内容并剥离注入块
 * 同时支持新格式 <knowledge>...</knowledge> 和旧格式【知识库文件（以下为摘要内容）】
 */
export function parseKnowledgePayload(text) {
  var next = String(text != null ? text : "");
  var knowledgeContent = null;

  // 新格式：<knowledge>...</knowledge>
  var xmlMatches = next.match(XML_KNOWLEDGE_PATTERN);
  if (xmlMatches) {
    knowledgeContent = xmlMatches.map(function (block) {
      return block.replace(/<knowledge>/, "").replace(/<\/knowledge>/, "").trim();
    }).join("\n\n");
    next = next.replace(XML_KNOWLEDGE_PATTERN, "");
  }

  // 旧格式：【知识库文件（以下为摘要内容）】
  if (!knowledgeContent) {
    var legacyMatch = next.match(LEGACY_KNOWLEDGE_PATTERN);
    if (legacyMatch) {
      knowledgeContent = legacyMatch[1].trim();
      next = next.replace(LEGACY_KNOWLEDGE_PATTERN, "");
    }
  }

  return { text: next.trim(), knowledgeContent: knowledgeContent };
}

/**
 * 从文本中提取附件解析内容并剥离注入块
 * 同时支持新格式 <attachment>...</attachment> 和旧格式【桌面端上传的附件（已自动解析）】
 */
export function parseAttachmentPayload(text) {
  var next = String(text != null ? text : "");
  var attachmentContent = null;

  // 新格式：<attachment>...</attachment>
  var xmlMatches = next.match(XML_ATTACHMENT_PATTERN);
  if (xmlMatches) {
    attachmentContent = xmlMatches.map(function (block) {
      return block.replace(/<attachment>/, "").replace(/<\/attachment>/, "").trim();
    }).join("\n\n---\n\n");
    next = next.replace(XML_ATTACHMENT_PATTERN, "");
  }

  // 旧格式：【桌面端上传的附件（已自动解析）】
  if (!attachmentContent) {
    var legacyMatch = next.match(LEGACY_ATTACHMENT_PATTERN);
    if (legacyMatch) {
      attachmentContent = legacyMatch[1].trim();
      next = next.replace(LEGACY_ATTACHMENT_PATTERN, "");
    }
  }

  return { text: next.trim(), attachmentContent: attachmentContent };
}

/**
 * 按【用户说明】分割用户消息文本，提取额外上下文与核心任务
 * 【用户说明】之前的附件解析/MCP/协同规则等内容为 extraContext
 * 【用户说明】之后的内容为用户的真正任务（main）
 * 如果没有【用户说明】标记，则返回 extra=null, main=原文
 */
export function splitUserExtraContext(text) {
  var t = trimMsgText(text);
  if (!t) return { extra: null, main: "" };
  var idx = t.indexOf(USER_NOTE_MARKER);
  if (idx < 0) return { extra: null, main: t };
  var before = t.slice(0, idx).trim();
  var after = t.slice(idx + USER_NOTE_MARKER.length);
  if (after.startsWith("\n")) after = after.slice(1);
  after = trimMsgText(after);
  var fromIdx = after.indexOf("【用户说明】");
  if (fromIdx >= 0) {
    after = trimMsgText(after.slice(0, fromIdx));
  }
  if (!before && !after) return { extra: null, main: "" };
  if (!before) return { extra: null, main: after };
  return { extra: before, main: after || "" };
}

export function normalizeDisplayMessageText(text) {
  var cleaned = parseSkillsInjectedPayload(text).text;
  if (SKILLS_INJECTED_PREFIX_HEAD_PATTERN.test(cleaned)) return "";
  return cleaned;
}

export function normalizeConversationTitle(rawTitle) {
  var cleaned = trimMsgText(normalizeDisplayMessageText(rawTitle));
  return cleaned || "新对话";
}

export function getConversationDisplayTitle(conv) {
  return normalizeConversationTitle(conv && conv.title);
}

/** 将后端/本地存储的 user 消息规范为 UI 展示结构 */
export function normalizeStoredUserMessage(msg) {
  if (!msg || msg.role !== "user") return msg;
  var parsed = parseSkillsInjectedPayload(msg.text);
  var mcpParsed = parseMcpInjectedPayload(parsed.text);
  var out = { role: "user", text: trimMsgText(mcpParsed.text) };
  var skills =
    Array.isArray(msg.skills) && msg.skills.length
      ? msg.skills
      : parsed.skills;
  if (skills && skills.length) out.skills = skills;
  var mcpTools =
    Array.isArray(msg.mcpTools) && msg.mcpTools.length
      ? msg.mcpTools
      : mcpParsed.mcpTools;
  if (mcpTools && mcpTools.length) out.mcpTools = mcpTools;
  if (Array.isArray(msg.attachmentNames) && msg.attachmentNames.length) {
    out.attachmentNames = msg.attachmentNames;
  }
  if (Array.isArray(msg.knowledgeNames) && msg.knowledgeNames.length) {
    out.knowledgeNames = msg.knowledgeNames;
  }
  if (msg.timestamp != null) out.timestamp = msg.timestamp;
  return out;
}

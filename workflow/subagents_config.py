import os
import json
import re
from datetime import datetime
from workflow.config import (
    SKILLS_BASE_DIR,
    MCP_READ_ALLOWED_DIRS,
    MCP_WRITE_ALLOWED_DIRS,
    OUTPUT_BASE_DIR,
    SUBAGENTS_CONFIG_PATH,
    USE_SANDBOX,
    MEMORY_SHORT_TERM_TASKS,
    MEMORY_MID_TERM_TASKS,
)

from loguru import logger


def _load_subagents_config():
    """从 JSON 配置文件加载 subagent 配置"""
    with open(SUBAGENTS_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_subsystem_template() -> str:
    """从 SUBSYSTEM.md 加载公共子系统提示词"""
    root_dir = os.path.dirname(os.path.dirname(__file__))
    template_path = os.path.join(root_dir, "prompt", "SUBSYSTEM.md")

    if not os.path.exists(template_path):
        return ""

    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


def _substitute_system_prompt(prompt: str, username: str = "") -> str:
    """替换系统提示词中的占位符"""
    if not username:
        username = "default"

    date_str = datetime.now().strftime("%Y%m%d")
    output_dir = f"{OUTPUT_BASE_DIR}/{username}/{date_str}/"

    read_dirs_str = (
        ", ".join(MCP_READ_ALLOWED_DIRS) if MCP_READ_ALLOWED_DIRS else "未配置"
    )
    write_dirs_str = (
        ", ".join(MCP_WRITE_ALLOWED_DIRS) if MCP_WRITE_ALLOWED_DIRS else "未配置"
    )

    # 构建 Available Skills 列表（与主 Agent 的 _build_system_prompt 对齐：停用 + 显式 allow）
    skills_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")
    discovered_skills = []
    if os.path.exists(skills_dir):
        for item in os.listdir(skills_dir):
            skill_path = os.path.join(skills_dir, item)
            if os.path.isdir(skill_path):
                skill_md_path = os.path.join(skill_path, "SKILL.md")
                description = ""
                if os.path.exists(skill_md_path):
                    try:
                        with open(skill_md_path, "r", encoding="utf-8-sig") as mf:
                            content = mf.read()
                            if content.startswith("---"):
                                end_idx = content.find("---", 3)
                                if end_idx > 0:
                                    yaml_section = content[3:end_idx].strip()
                                    name_match = re.search(
                                        r"name:\s*(.+)", yaml_section
                                    )
                                    desc_match = re.search(
                                        r"description:\s*(.+)", yaml_section
                                    )
                                    if name_match:
                                        name = name_match.group(1).strip()
                                        if desc_match:
                                            description = desc_match.group(1).strip()
                                        discovered_skills.append((name, description))
                    except Exception:
                        pass

    from workflow.report_tools import (
        get_disabled_skills_with_fallback,
        build_skills_policy_notice_for_prompt,
    )
    from workflow.permission_engine import PermissionEngine

    disabled_skills = get_disabled_skills_with_fallback()
    working_skills = [s for s in discovered_skills if s[0] not in disabled_skills]
    allowed_names = PermissionEngine.filter_skills_by_explicit_allow(
        username, [s[0] for s in working_skills]
    )
    allowed_set = set(allowed_names)
    available_skills = [s for s in working_skills if s[0] in allowed_set]

    skills_policy_notice = build_skills_policy_notice_for_prompt(
        discovered_skills, available_skills
    )

    skills_base_path = "/home/user/skills" if USE_SANDBOX else SKILLS_BASE_DIR
    skills_text = "\n".join(
        [
            f"- {name} (`{skills_base_path}/{name}/`) - {desc}"
            for name, desc in available_skills
        ]
    )

    # 获取 MCP 工具技能说明
    from workflow.mcpClient import get_mcp_tools_skills

    mcp_tools_skills = get_mcp_tools_skills()
    if mcp_tools_skills:
        mcp_tools_section = f"""
{mcp_tools_skills}

请根据上述工具的技能说明来正确调用这些外部 MCP 工具。"""
    else:
        mcp_tools_section = "无外部 MCP 工具"

    substitutions = {
        "{{MCP_READ_ALLOWED_DIRS}}": read_dirs_str,
        "{{MCP_WRITE_ALLOWED_DIRS}}": write_dirs_str,
        "{{OUTPUT_DIR}}": output_dir,
        "{{SKILLS_POLICY_NOTICE}}": skills_policy_notice,
        "{{AVAILABLE_SKILLS}}": skills_text,
        "{{MCP_TOOLS_SKILLS}}": mcp_tools_section,
        "{{MEMORY_SHORT_TERM_TASKS}}": str(MEMORY_SHORT_TERM_TASKS),
        "{{MEMORY_MID_TERM_TASKS}}": str(MEMORY_MID_TERM_TASKS),
    }

    for placeholder, value in substitutions.items():
        prompt = prompt.replace(placeholder, value)

    return prompt


def _find_tools_by_mcp_list(all_mcp_tools: list, mcp_list: list) -> list:
    """根据 mcp_list 直接查找匹配的 MCP 工具

    Args:
        all_mcp_tools: 所有可用的 MCP 工具列表
        mcp_list: 工具名称列表，格式为 "server_tool" 或 "server/tool"

    Returns:
        匹配的工具列表
    """
    matched_tools = []

    for tool in all_mcp_tools:
        tool_name = tool.name
        server_name = None
        if tool.metadata:
            server_name = tool.metadata.get("server_name")

        safe_server_name = (server_name or "mcp").replace("-", "_").replace(" ", "_")
        prefixed_name = f"{safe_server_name}_{tool.name}"

        for mcp_item in mcp_list:
            normalized_item = mcp_item.replace("/", "_")
            if (
                normalized_item == tool_name
                or normalized_item == prefixed_name
                or normalized_item == f"{safe_server_name}/{tool.name}"
            ):
                if tool not in matched_tools:
                    matched_tools.append(tool)
                break

    return matched_tools


def get_subsystem_prompt(agent_name: str, username: str = "") -> str:
    """获取指定 subagent 的完整系统提示词"""
    config = _load_subagents_config()
    subagents_config = config.get("subagents", [])

    common_prompt = _load_subsystem_template()

    specific_prompt = ""
    for subagent_cfg in subagents_config:
        if subagent_cfg.get("name") == agent_name:
            specific_prompt = subagent_cfg.get("system_prompt", "")
            break

    combined_prompt = common_prompt + "\n\n" + specific_prompt

    return _substitute_system_prompt(combined_prompt, username)


def build_subagents(all_mcp_tools, username: str = ""):
    """根据所有可用的 MCP 工具构建子代理

    系统提示词说明：
    - SUBSYSTEM.md 中的公共提示词 + subagents.json 中每个 subagent 的专门提示词
    - 系统提示词在 build_subagents() 被调用时加载并替换占位符

    工具匹配说明：
    - 通过 subagents.json 中的 mcp_list 直接指定需要的工具
    - mcp_list 格式为 "server_tool"，如 "MCPFilesystem_read_file"
    """
    config = _load_subagents_config()
    subagents_config = config.get("subagents", [])

    common_prompt = _load_subsystem_template()

    subagents = []
    for subagent_cfg in subagents_config:
        agent_name = subagent_cfg["name"]
        mcp_list = subagent_cfg.get("mcp_list", [])
        skills_names = subagent_cfg.get("skills", [])
        specific_prompt = subagent_cfg.get("system_prompt", "")

        tools = _find_tools_by_mcp_list(all_mcp_tools, mcp_list)

        skills = []
        if skills_names:
            skills = [os.path.join(SKILLS_BASE_DIR, name) for name in skills_names]

        combined_prompt = common_prompt + "\n\n" + specific_prompt
        combined_prompt = _substitute_system_prompt(combined_prompt, username)

        subagent = {
            "name": agent_name,
            "description": subagent_cfg["description"],
            "system_prompt": combined_prompt,
            "tools": tools,
        }

        if skills:
            subagent["skills"] = skills

        subagents.append(subagent)

        logger.info("[Subagent] {}: 加载 {} 个 MCP 工具", agent_name, len(tools))

    logger.info("[Subagent] 已构建 {} 个子代理", len(subagents))
    return subagents

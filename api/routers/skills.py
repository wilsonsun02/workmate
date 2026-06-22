import json
import os

from fastapi import APIRouter, HTTPException

from admin_api.services.config_service import ConfigService
from workflow.report_tools import (
    merge_skills_config_db_and_file,
    _normalize_skills_config_map,
)

router = APIRouter(tags=["skills"])


def _normalize_skills_dict(config_data: object) -> dict:
    if not isinstance(config_data, dict):
        return {}
    skills_node = config_data.get("skills")
    if isinstance(skills_node, dict):
        return skills_node
    out = {}
    for k, v in config_data.items():
        if k == "skills":
            continue
        if isinstance(v, dict):
            out[str(k)] = v
    return out


def load_skills_config():
    """DB + local skills_config.json merged (AND per-skill enabled), same as workflow runtime."""
    merged = merge_skills_config_db_and_file()
    return _normalize_skills_config_map(merged)


def reload_skills_enabled_cache() -> None:
    global _skills_enabled_cache
    _skills_enabled_cache = load_skills_config()


def save_skills_config(config_data):
    ConfigService.set_config(
        "skills_config", "skills", {"skills": config_data}, "技能启用状态配置"
    )


_skills_enabled_cache = load_skills_config()


def get_skills_dir():
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "skills"
    )


@router.post("/skills/reload-config-cache")
async def reload_skills_config_cache():
    """Reload in-process skills enable map (e.g. after desktop sync writes skills_config.json)."""
    reload_skills_enabled_cache()
    return {"success": True, "message": "skills cache reloaded"}


@router.get("/skills/list")
async def list_skills():
    skills_dir = get_skills_dir()
    skills_list = []
    if not os.path.exists(skills_dir):
        return {"success": True, "skills": []}

    for item in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, item)
        if os.path.isdir(skill_path):
            skill_md_path = os.path.join(skill_path, "SKILL.md")
            has_skill_md = os.path.exists(skill_md_path)
            scripts = []
            scripts_dir = os.path.join(skill_path, "scripts")
            if os.path.exists(scripts_dir):
                for script in os.listdir(scripts_dir):
                    if script.endswith((".py", ".js", ".sh")):
                        scripts.append(script)
            skills_list.append(
                {
                    "name": item,
                    "has_skill_md": has_skill_md,
                    "scripts": scripts,
                    "enabled": bool(
                        _skills_enabled_cache.get(item, {}).get("enabled", True)
                    ),
                }
            )
    return {"success": True, "skills": skills_list}


@router.get("/skills/{skill_name}")
async def get_skill_detail(skill_name: str):
    if skill_name == "list":
        raise HTTPException(
            status_code=404, detail="Use /skills/list to get all skills"
        )
    skills_dir = get_skills_dir()
    skill_path = os.path.join(skills_dir, skill_name)
    if not os.path.exists(skill_path) or not os.path.isdir(skill_path):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    result = {
        "name": skill_name,
        "enabled": bool(_skills_enabled_cache.get(skill_name, {}).get("enabled", True)),
        "files": [],
        "skill_md_content": "",
    }
    for root, _, files in os.walk(skill_path):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(file_path, skill_path)
            result["files"].append(rel_path)
            if file_name == "SKILL.md":
                try:
                    with open(file_path, "r", encoding="utf-8") as md_file:
                        result["skill_md_content"] = md_file.read()
                except Exception:
                    pass
    return {"success": True, "skill": result}


@router.post("/skills/{skill_name}/enable")
async def enable_skill(skill_name: str):
    skills_dir = get_skills_dir()
    skill_path = os.path.join(skills_dir, skill_name)
    if not os.path.exists(skill_path) or not os.path.isdir(skill_path):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    current = _skills_enabled_cache.get(skill_name, {})
    _skills_enabled_cache[skill_name] = {
        "description": current.get("description", ""),
        "enabled": True,
    }
    save_skills_config(_skills_enabled_cache)
    return {
        "success": True,
        "message": f"Skill '{skill_name}' enabled",
        "enabled": True,
    }


@router.post("/skills/{skill_name}/disable")
async def disable_skill(skill_name: str):
    skills_dir = get_skills_dir()
    skill_path = os.path.join(skills_dir, skill_name)
    if not os.path.exists(skill_path) or not os.path.isdir(skill_path):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    current = _skills_enabled_cache.get(skill_name, {})
    _skills_enabled_cache[skill_name] = {
        "description": current.get("description", ""),
        "enabled": False,
    }
    save_skills_config(_skills_enabled_cache)
    return {
        "success": True,
        "message": f"Skill '{skill_name}' disabled",
        "enabled": False,
    }

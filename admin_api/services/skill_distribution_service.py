import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from functools import cmp_to_key
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import yaml
import requests

from admin_api.models.init_db import get_db_connection
from admin_api.services.config_service import ConfigService
from admin_api.services.env_file_service import EnvFileService
from admin_api.services.oss_service import OssService
from workflow.config import SKILLS_DIR


class SkillDistributionService:
    _download_tokens: Dict[str, Dict] = {}
    _catalog_cache: Dict[str, Any] = {"expires_at": 0.0, "value": None}
    _package_summary_cache: Dict[str, Any] = {"expires_at": 0.0, "value": None}
    _cache_ttl_seconds = 30
    _exclude_names = {"_packages", "__pycache__", ".DS_Store"}
    _text_file_exts = {
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".css",
        ".scss",
        ".html",
        ".xml",
        ".sql",
        ".toml",
        ".ini",
        ".cfg",
        ".csv",
        ".sh",
    }
    _semver_pattern = re.compile(
        r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>[0-9A-Za-z.-]+))?$"
    )

    @staticmethod
    def normalize_skills_map(raw_config: Dict) -> Dict[str, Dict]:
        if not isinstance(raw_config, dict):
            return {}
        skills_node = raw_config.get("skills")
        if isinstance(skills_node, dict):
            normalized = {}
            for skill_name, value in skills_node.items():
                if isinstance(value, dict):
                    normalized[skill_name] = {
                        "description": value.get("description", ""),
                        "enabled": bool(value.get("enabled", True)),
                        "deleted": bool(value.get("deleted", False)),
                    }
                else:
                    normalized[skill_name] = {
                        "description": "",
                        "enabled": bool(value),
                        "deleted": False,
                    }
            return normalized
        normalized = {}
        for skill_name, value in raw_config.items():
            if isinstance(value, dict):
                normalized[skill_name] = {
                    "description": value.get("description", ""),
                    "enabled": bool(value.get("enabled", True)),
                    "deleted": bool(value.get("deleted", False)),
                }
            else:
                normalized[skill_name] = {
                    "description": "",
                    "enabled": bool(value),
                    "deleted": False,
                }
        return normalized

    @staticmethod
    def get_skills_map() -> Dict[str, Dict]:
        raw = ConfigService.get_config("skills_config", {"skills": {}})
        return SkillDistributionService.normalize_skills_map(raw)

    @staticmethod
    def save_skills_map(skills_map: Dict[str, Dict]) -> bool:
        ok = ConfigService.set_config(
            "skills_config", "skills", {"skills": skills_map}, "技能启用状态配置"
        )
        if ok:
            SkillDistributionService.invalidate_catalog_cache()
        return ok

    @staticmethod
    def invalidate_catalog_cache() -> None:
        SkillDistributionService._catalog_cache = {"expires_at": 0.0, "value": None}
        SkillDistributionService._package_summary_cache = {
            "expires_at": 0.0,
            "value": None,
        }

    @staticmethod
    def _get_cached_value(cache: Dict[str, Any]):
        expires_at = float(cache.get("expires_at") or 0.0)
        value = cache.get("value")
        if value is None or time.monotonic() >= expires_at:
            return None
        return value

    @staticmethod
    def _set_cached_value(cache_name: str, value: Any) -> Any:
        setattr(
            SkillDistributionService,
            cache_name,
            {
                "expires_at": time.monotonic()
                + float(SkillDistributionService._cache_ttl_seconds),
                "value": value,
            },
        )
        return value

    @staticmethod
    def _load_package_summary_map() -> Dict[str, Dict]:
        conn = get_db_connection()
        if not conn:
            return {}
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, skill_name, version, description, sha256, file_path, file_size, is_active,
                       created_at, updated_at
                FROM sys_skill_packages
                ORDER BY skill_name ASC, created_at DESC, updated_at DESC
                """
            )
            rows = cursor.fetchall() or []
            summary_map: Dict[str, Dict] = {}
            for row in rows:
                skill_name = str(row.get("skill_name") or "").strip()
                version = str(row.get("version") or "").strip()
                if not skill_name or not version:
                    continue
                summary = summary_map.setdefault(
                    skill_name,
                    {
                        "package_count": 0,
                        "latest_version": version,
                        "package_id": row.get("id"),
                        "description": row.get("description"),
                        "sha256": row.get("sha256"),
                        "file_path": row.get("file_path"),
                        "file_size": row.get("file_size"),
                        "is_active": row.get("is_active"),
                    },
                )
                summary["package_count"] += 1
                if (
                    SkillDistributionService.compare_semver(
                        version, str(summary.get("latest_version") or "0.0.1")
                    )
                    >= 0
                ):
                    summary.update(
                        {
                            "latest_version": version,
                            "package_id": row.get("id"),
                            "description": row.get("description"),
                            "sha256": row.get("sha256"),
                            "file_path": row.get("file_path"),
                            "file_size": row.get("file_size"),
                            "is_active": row.get("is_active"),
                        }
                    )
            return summary_map
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_package_summary_map(
        skill_names: Optional[List[str]] = None,
    ) -> Dict[str, Dict]:
        cached = SkillDistributionService._get_cached_value(
            SkillDistributionService._package_summary_cache
        )
        if cached is None:
            cached = SkillDistributionService._set_cached_value(
                "_package_summary_cache",
                SkillDistributionService._load_package_summary_map(),
            )
        if not skill_names:
            return dict(cached)
        return {
            skill_name: dict(cached[skill_name])
            for skill_name in skill_names
            if skill_name in cached
        }

    @staticmethod
    def _load_catalog() -> List[Dict]:
        skills_map = SkillDistributionService.get_skills_map()
        package_summary_map = SkillDistributionService.get_package_summary_map()
        catalog = []
        local_skill_dirs = SkillDistributionService._get_skill_dirs()
        local_skill_map = {}
        for skill_path in local_skill_dirs:
            parsed_name, parsed_desc, parsed_version = (
                SkillDistributionService.parse_skill_md(skill_path)
            )
            local_skill_map[parsed_name] = {
                "description": parsed_desc,
                "version": parsed_version,
            }

        skill_names = sorted(
            set(local_skill_map.keys())
            | set(skills_map.keys())
            | set(package_summary_map.keys())
        )

        for skill_name in skill_names:
            local_meta = local_skill_map.get(skill_name, {})
            summary = package_summary_map.get(skill_name, {})
            cfg = skills_map.get(skill_name, {})
            if bool(cfg.get("deleted", False)):
                continue
            latest_version = str(
                summary.get("latest_version") or local_meta.get("version") or "0.0.1"
            )
            enabled = bool(cfg.get("enabled", True))
            description = (
                cfg.get("description")
                or summary.get("description")
                or local_meta.get("description")
                or ""
            )
            catalog.append(
                {
                    "name": skill_name,
                    "description": description,
                    "enabled": enabled,
                    "latest_version": latest_version,
                    "package_count": int(summary.get("package_count") or 0),
                }
            )
        return sorted(catalog, key=lambda x: x["name"])

    @staticmethod
    def parse_skill_md(skill_root: str) -> Tuple[str, str, str]:
        skill_md_path = os.path.join(skill_root, "SKILL.md")
        skill_name = os.path.basename(skill_root)
        skill_desc = ""
        version = "0.0.1"
        if not os.path.exists(skill_md_path):
            return skill_name, skill_desc, version
        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.startswith("---"):
            return skill_name, skill_desc, version
        end_idx = content.find("---", 3)
        if end_idx == -1:
            return skill_name, skill_desc, version
        yaml_content = content[3:end_idx]
        metadata = yaml.safe_load(yaml_content) or {}
        skill_name = metadata.get("name") or skill_name
        skill_desc = metadata.get("description", "")
        version = str(metadata.get("version") or version)
        return skill_name, skill_desc, version

    @staticmethod
    def is_valid_semver(version: str) -> bool:
        return bool(SkillDistributionService._semver_pattern.match(str(version)))

    @staticmethod
    def _parse_semver(version: str) -> Tuple[int, int, int, Tuple]:
        match = SkillDistributionService._semver_pattern.match(str(version))
        if not match:
            raise ValueError(f"Invalid SemVer version: {version}")
        prerelease = match.group("prerelease")
        pre_tokens = []
        if prerelease:
            for token in prerelease.split("."):
                if token.isdigit():
                    pre_tokens.append((0, int(token)))
                else:
                    pre_tokens.append((1, token))
        return (
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
            tuple(pre_tokens),
        )

    @staticmethod
    def compare_semver(left: str, right: str) -> int:
        l_major, l_minor, l_patch, l_pre = SkillDistributionService._parse_semver(left)
        r_major, r_minor, r_patch, r_pre = SkillDistributionService._parse_semver(right)

        for lv, rv in ((l_major, r_major), (l_minor, r_minor), (l_patch, r_patch)):
            if lv != rv:
                return 1 if lv > rv else -1

        # 无 prerelease > 有 prerelease
        if not l_pre and r_pre:
            return 1
        if l_pre and not r_pre:
            return -1
        if not l_pre and not r_pre:
            return 0

        for l_item, r_item in zip(l_pre, r_pre):
            if l_item == r_item:
                continue
            if l_item[0] != r_item[0]:
                return -1 if l_item[0] < r_item[0] else 1
            return 1 if l_item[1] > r_item[1] else -1

        if len(l_pre) == len(r_pre):
            return 0
        return 1 if len(l_pre) > len(r_pre) else -1

    @staticmethod
    def file_sha256(file_path: str) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def should_exclude_relpath(rel_path: str) -> bool:
        parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
        for part in parts:
            if part in SkillDistributionService._exclude_names:
                return True
            if part.startswith("."):
                return True
            if part.startswith("_temp_"):
                return True
        return False

    @staticmethod
    def _get_skill_dirs() -> List[str]:
        if not os.path.exists(SKILLS_DIR):
            return []
        dirs = []
        for name in os.listdir(SKILLS_DIR):
            path = os.path.join(SKILLS_DIR, name)
            if not os.path.isdir(path):
                continue
            if SkillDistributionService.should_exclude_relpath(name):
                continue
            if not os.path.exists(os.path.join(path, "SKILL.md")):
                continue
            dirs.append(path)
        return sorted(dirs)

    @staticmethod
    def build_skill_zip(skill_root: str, output_zip_path: str):
        with zipfile.ZipFile(
            output_zip_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as zipf:
            for root, _, files in os.walk(skill_root):
                rel_dir = os.path.relpath(root, skill_root)
                if rel_dir == ".":
                    rel_dir = ""
                if SkillDistributionService.should_exclude_relpath(rel_dir):
                    continue
                for name in files:
                    rel_path = os.path.join(rel_dir, name) if rel_dir else name
                    rel_path = rel_path.replace("\\", "/")
                    if SkillDistributionService.should_exclude_relpath(rel_path):
                        continue
                    full_path = os.path.join(root, name)
                    zipf.write(full_path, arcname=rel_path)

    @staticmethod
    def package_all_skills_to_oss() -> Dict:
        detail = []
        total = 0
        success = 0
        for skill_dir in SkillDistributionService._get_skill_dirs():
            total += 1
            try:
                skill_name, skill_desc, version = (
                    SkillDistributionService.parse_skill_md(skill_dir)
                )
                if not SkillDistributionService.is_valid_semver(version):
                    raise ValueError(
                        f"Skill {skill_name} version must be SemVer, got: {version}"
                    )
                with tempfile.TemporaryDirectory() as td:
                    zip_name = f"{skill_name}-{version}.zip"
                    zip_path = os.path.join(td, zip_name)
                    SkillDistributionService.build_skill_zip(skill_dir, zip_path)
                    sha256 = SkillDistributionService.file_sha256(zip_path)
                    file_size = os.path.getsize(zip_path)
                    object_key = OssService.normalize_object_key(skill_name, version)
                    OssService.upload_file(zip_path, object_key)
                    SkillDistributionService.record_skill_package(
                        skill_name=skill_name,
                        version=version,
                        description=skill_desc,
                        file_name=zip_name,
                        file_path=object_key,
                        sha256=sha256,
                        file_size=file_size,
                    )
                    skills_map = SkillDistributionService.get_skills_map()
                    if skill_name not in skills_map:
                        skills_map[skill_name] = {
                            "description": skill_desc,
                            "enabled": False,
                        }
                        SkillDistributionService.save_skills_map(skills_map)
                detail.append(
                    {
                        "skill_name": skill_name,
                        "version": version,
                        "status": "success",
                        "object_key": object_key,
                    }
                )
                success += 1
            except Exception as e:
                detail.append(
                    {
                        "skill_name": os.path.basename(skill_dir),
                        "status": "failed",
                        "error": str(e),
                    }
                )
        return {
            "total": total,
            "success": success,
            "failed": total - success,
            "details": detail,
        }

    @staticmethod
    def _version_tuple(version: str):
        # 保持旧代码调用兼容，内部统一走 SemVer 比较
        return SkillDistributionService._parse_semver(version)

    @staticmethod
    def _latest_version(versions: List[str]) -> str:
        if not versions:
            return "0.0.1"
        return sorted(
            versions, key=cmp_to_key(SkillDistributionService.compare_semver)
        )[-1]

    @staticmethod
    def next_patch_version(skill_name: str) -> str:
        versions = SkillDistributionService.get_skill_versions(skill_name)
        if not versions:
            return "0.0.1"
        latest = SkillDistributionService._latest_version(
            [str(v["version"]) for v in versions]
        )
        major, minor, patch, _ = SkillDistributionService._parse_semver(latest)
        return f"{major}.{minor}.{patch + 1}"

    @staticmethod
    def upsert_skill_md_frontmatter(
        skill_root: str, name: str, description: str, version: str
    ) -> None:
        skill_md_path = os.path.join(skill_root, "SKILL.md")
        body = ""
        if os.path.exists(skill_md_path):
            with open(skill_md_path, "r", encoding="utf-8") as f:
                content = f.read()
            if content.startswith("---"):
                end_idx = content.find("---", 3)
                if end_idx != -1:
                    body = content[end_idx + 3 :].lstrip("\r\n")
                else:
                    body = content
            else:
                body = content
        metadata = {"name": name, "description": description, "version": version}
        frontmatter = yaml.safe_dump(
            metadata, allow_unicode=True, sort_keys=False
        ).strip()
        output = f"---\n{frontmatter}\n---\n\n{body}"
        with open(skill_md_path, "w", encoding="utf-8") as f:
            f.write(output)

    @staticmethod
    def safe_skill_root(skill_name: str) -> str:
        cleaned = str(skill_name or "").strip()
        if (
            not cleaned
            or "/" in cleaned
            or "\\" in cleaned
            or cleaned in {".", ".."}
            or ".." in cleaned
        ):
            raise ValueError("Invalid skill name")

        skills_root = os.path.abspath(SKILLS_DIR)
        skill_root = os.path.abspath(os.path.join(skills_root, cleaned))
        try:
            if os.path.commonpath([skills_root, skill_root]) != skills_root:
                raise ValueError("Invalid skill name")
        except ValueError:
            raise ValueError("Invalid skill name") from None
        return skill_root

    @staticmethod
    def safe_skill_relpath(skill_name: str, rel_path: str) -> str:
        skill_root = SkillDistributionService.safe_skill_root(skill_name)
        return SkillDistributionService.safe_relpath_under_root(skill_root, rel_path)

    @staticmethod
    def safe_relpath_under_root(base_root: str, rel_path: str) -> str:
        cleaned = (rel_path or "").replace("\\", "/").strip()
        if not cleaned or cleaned.startswith("/") or ".." in cleaned.split("/"):
            raise ValueError("Invalid file path")
        abs_path = os.path.abspath(os.path.join(base_root, cleaned))
        try:
            if os.path.commonpath([base_root, abs_path]) != base_root:
                raise ValueError("Invalid file path")
        except ValueError:
            raise ValueError("Invalid file path")
        return abs_path

    @staticmethod
    def is_text_file(rel_path: str) -> bool:
        lower_name = os.path.basename(rel_path).lower()
        if lower_name in ("skill.md", "readme.md", "license", "license.txt"):
            return True
        ext = os.path.splitext(lower_name)[1]
        if ext in SkillDistributionService._text_file_exts:
            return True
        return False

    @staticmethod
    def record_skill_package(
        skill_name: str,
        version: str,
        description: str,
        file_name: str,
        file_path: str,
        sha256: str,
        file_size: int,
    ):
        conn = get_db_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            package_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO sys_skill_packages (id, skill_name, version, description, file_name, file_path, sha256, file_size, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE
                description = VALUES(description),
                file_name = VALUES(file_name),
                file_path = VALUES(file_path),
                sha256 = VALUES(sha256),
                file_size = VALUES(file_size),
                is_active = 1
                """,
                (
                    package_id,
                    skill_name,
                    version,
                    description,
                    file_name,
                    file_path,
                    sha256,
                    file_size,
                ),
            )
            conn.commit()
            SkillDistributionService.invalidate_catalog_cache()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_skill_versions(skill_name: str) -> List[Dict]:
        conn = get_db_connection()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, skill_name, version, description, file_name, sha256, file_size, is_active,file_path, created_at, updated_at
                FROM sys_skill_packages
                WHERE skill_name = %s
                ORDER BY created_at DESC
                """,
                (skill_name,),
            )
            return cursor.fetchall()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_catalog() -> List[Dict]:
        cached = SkillDistributionService._get_cached_value(
            SkillDistributionService._catalog_cache
        )
        if cached is not None:
            return list(cached)
        return SkillDistributionService._set_cached_value(
            "_catalog_cache",
            SkillDistributionService._load_catalog(),
        )

    @staticmethod
    def _expand_target_users(owner_type: str, owner_id: str) -> List[str]:
        conn = get_db_connection()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            if owner_type == "user":
                return [owner_id]
            if owner_type == "role":
                cursor.execute(
                    "SELECT id FROM sys_users WHERE role_id = %s AND status = 1",
                    (owner_id,),
                )
                return [r["id"] for r in cursor.fetchall()]
            if owner_type == "dept":
                cursor.execute(
                    "SELECT id FROM sys_users WHERE dept_id = %s AND status = 1",
                    (owner_id,),
                )
                return [r["id"] for r in cursor.fetchall()]
            return []
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def _get_env_config_value(key: str, default_value: str) -> str:
        return EnvFileService.get_value(key, default_value)

    @staticmethod
    def default_retry_policy() -> Dict:
        return {
            "retry_times": int(
                SkillDistributionService._get_env_config_value(
                    "SKILL_AUTO_UPGRADE_RETRY_TIMES", "2"
                )
            ),
            "retry_backoff_sec": int(
                SkillDistributionService._get_env_config_value(
                    "SKILL_AUTO_UPGRADE_RETRY_BACKOFF_SEC", "5"
                )
            ),
        }

    @staticmethod
    def create_release(
        skill_name: str,
        version: str,
        rollout_type: str,
        rollout_id: str,
        strategy: str = "hybrid",
        batch_size: Optional[int] = None,
        failure_threshold: Optional[float] = None,
        created_by: Optional[str] = None,
    ) -> Dict:
        if rollout_type not in ("user", "role", "dept"):
            raise ValueError("rollout_type must be user/role/dept")
        if strategy not in ("active", "passive", "hybrid"):
            strategy = "hybrid"
        if not SkillDistributionService.is_valid_semver(version):
            raise ValueError(f"version must be SemVer, got: {version}")

        target_users = SkillDistributionService._expand_target_users(
            rollout_type, rollout_id
        )
        if not target_users:
            raise ValueError("No target users found for rollout scope")

        if batch_size is None:
            batch_size = int(
                SkillDistributionService._get_env_config_value(
                    "SKILL_ROLLOUT_DEFAULT_BATCH_SIZE", "100"
                )
            )
        if failure_threshold is None:
            failure_threshold = float(
                SkillDistributionService._get_env_config_value(
                    "SKILL_ROLLOUT_FAILURE_THRESHOLD", "0.3"
                )
            )
        batch_size = max(1, int(batch_size))

        conn = get_db_connection()
        if not conn:
            raise RuntimeError("Database connection failed")
        release_id = str(uuid.uuid4())
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sys_skill_releases
                (id, skill_name, version, strategy, rollout_type, rollout_id, status, total_targets, batch_size, failure_threshold, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, 'draft', %s, %s, %s, %s)
                """,
                (
                    release_id,
                    skill_name,
                    version,
                    strategy,
                    rollout_type,
                    rollout_id,
                    len(target_users),
                    batch_size,
                    failure_threshold,
                    created_by,
                ),
            )

            for idx, user_id in enumerate(target_users):
                target_id = str(uuid.uuid4())
                rollout_batch = (idx // batch_size) + 1
                cursor.execute(
                    """
                    INSERT INTO sys_skill_release_targets
                    (id, release_id, target_user_id, rollout_batch, status)
                    VALUES (%s, %s, %s, %s, 'pending')
                    ON DUPLICATE KEY UPDATE rollout_batch = VALUES(rollout_batch)
                    """,
                    (target_id, release_id, user_id, rollout_batch),
                )
            conn.commit()
            return {
                "id": release_id,
                "skill_name": skill_name,
                "version": version,
                "strategy": strategy,
                "rollout_type": rollout_type,
                "rollout_id": rollout_id,
                "total_targets": len(target_users),
                "batch_size": batch_size,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_release(release_id: str) -> Optional[Dict]:
        conn = get_db_connection()
        if not conn:
            return None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, skill_name, version, strategy, rollout_type, rollout_id, status,
                       total_targets, batch_size, failure_threshold, created_by, created_at, updated_at
                FROM sys_skill_releases
                WHERE id = %s
                """,
                (release_id,),
            )
            return cursor.fetchone()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def list_releases(
        skill_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict]:
        conn = get_db_connection()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            sql = """
                SELECT id, skill_name, version, strategy, rollout_type, rollout_id, status,
                       total_targets, batch_size, failure_threshold, created_by, created_at, updated_at
                FROM sys_skill_releases
                WHERE 1 = 1
            """
            params: List = []
            if skill_name:
                sql += " AND skill_name = %s"
                params.append(skill_name)
            if status:
                sql += " AND status = %s"
                params.append(status)
            sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            cursor.execute(sql, tuple(params))
            return cursor.fetchall()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def list_release_targets(release_id: str) -> List[Dict]:
        conn = get_db_connection()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT rt.id, rt.release_id, rt.target_user_id, u.username, rt.rollout_batch, rt.status,
                       rt.latest_task_id, rt.last_error_message, rt.created_at, rt.updated_at
                FROM sys_skill_release_targets rt
                LEFT JOIN sys_users u ON u.id = rt.target_user_id
                WHERE rt.release_id = %s
                ORDER BY rt.rollout_batch ASC, rt.created_at ASC
                """,
                (release_id,),
            )
            return cursor.fetchall()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def update_release_status(release_id: str, status: str):
        conn = get_db_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sys_skill_releases SET status = %s WHERE id = %s",
                (status, release_id),
            )
            conn.commit()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def dispatch_release_batch(
        release_id: str, rollout_batch: Optional[int] = None
    ) -> Dict:
        release = SkillDistributionService.get_release(release_id)
        if not release:
            raise ValueError("Release not found")
        if release["status"] in ("paused",):
            raise ValueError("Release is paused")

        targets = SkillDistributionService.list_release_targets(release_id)
        pending_targets = [t for t in targets if t["status"] == "pending"]
        if not pending_targets:
            SkillDistributionService.update_release_status(release_id, "completed")
            return {"created": 0, "rollout_batch": rollout_batch or 0, "tasks": []}

        if rollout_batch is None:
            rollout_batch = min(t["rollout_batch"] for t in pending_targets)
        batch_targets = [
            t for t in pending_targets if int(t["rollout_batch"]) == int(rollout_batch)
        ]
        if not batch_targets:
            return {"created": 0, "rollout_batch": rollout_batch, "tasks": []}

        created_tasks = SkillDistributionService.create_install_tasks(
            owner_type=release["rollout_type"],
            owner_id=release["rollout_id"],
            skill_name=release["skill_name"],
            version=release["version"],
            release_id=release_id,
            rollout_batch=int(rollout_batch),
            retry_policy=SkillDistributionService.default_retry_policy(),
            target_user_ids=[t["target_user_id"] for t in batch_targets],
        )

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                for target, task in zip(batch_targets, created_tasks):
                    cursor.execute(
                        """
                        UPDATE sys_skill_release_targets
                        SET status = 'dispatched', latest_task_id = %s
                        WHERE id = %s
                        """,
                        (task["task_id"], target["id"]),
                    )
                cursor.execute(
                    "UPDATE sys_skill_releases SET status = 'running' WHERE id = %s",
                    (release_id,),
                )
                conn.commit()
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        return {
            "created": len(created_tasks),
            "rollout_batch": int(rollout_batch),
            "tasks": created_tasks,
        }

    @staticmethod
    def rollback_release(release_id: str, rollback_version: str) -> Dict:
        if not SkillDistributionService.is_valid_semver(rollback_version):
            raise ValueError(
                f"rollback_version must be SemVer, got: {rollback_version}"
            )
        release = SkillDistributionService.get_release(release_id)
        if not release:
            raise ValueError("Release not found")
        targets = SkillDistributionService.list_release_targets(release_id)
        user_ids = [t["target_user_id"] for t in targets]
        created = SkillDistributionService.create_install_tasks(
            owner_type=release["rollout_type"],
            owner_id=release["rollout_id"],
            skill_name=release["skill_name"],
            version=rollback_version,
            release_id=release_id,
            rollout_batch=0,
            retry_policy=SkillDistributionService.default_retry_policy(),
            target_user_ids=user_ids,
        )
        SkillDistributionService.update_release_status(release_id, "rollback")
        return {
            "created": len(created),
            "tasks": created,
            "rollback_version": rollback_version,
        }

    @staticmethod
    def create_install_tasks(
        owner_type: str,
        owner_id: str,
        skill_name: str,
        version: str,
        release_id: Optional[str] = None,
        rollout_batch: int = 0,
        retry_policy: Optional[Dict] = None,
        target_user_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        user_ids = target_user_ids or SkillDistributionService._expand_target_users(
            owner_type, owner_id
        )
        if not user_ids:
            return []
        conn = get_db_connection()
        if not conn:
            return []
        created = []
        try:
            cursor = conn.cursor()
            for user_id in user_ids:
                task_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO sys_skill_install_tasks
                    (id, release_id, target_owner_type, target_owner_id, target_user_id, skill_name, target_version, rollout_batch, retry_policy, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                    """,
                    (
                        task_id,
                        release_id,
                        owner_type,
                        owner_id,
                        user_id,
                        skill_name,
                        version,
                        int(rollout_batch or 0),
                        json.dumps(retry_policy or {}, ensure_ascii=False),
                    ),
                )
                created.append({"task_id": task_id, "target_user_id": user_id})
            conn.commit()
            return created
        except Exception:
            conn.rollback()
            raise
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def list_install_tasks(
        status: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> List[Dict]:
        conn = get_db_connection()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            base_sql = """
                SELECT t.id, t.release_id, t.target_owner_type, t.target_owner_id, t.target_user_id, u.username, t.client_id,
                       t.skill_name, t.target_version, t.rollout_batch, t.retry_policy, t.status, t.error_message, t.started_at, t.finished_at, t.created_at, t.updated_at
                FROM sys_skill_install_tasks t
                LEFT JOIN sys_users u ON t.target_user_id = u.id
            """
            params = []
            if status:
                base_sql += " WHERE t.status = %s"
                params.append(status)
            base_sql += " ORDER BY t.created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            cursor.execute(base_sql, tuple(params))
            return cursor.fetchall()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def update_install_task_status(
        task_id: str,
        status: str,
        client_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        conn = get_db_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor(dictionary=True)
            now_fields = []
            if status in ("downloading", "installing") and client_id:
                now_fields.append(("started_at", "CURRENT_TIMESTAMP"))
            if status in ("success", "failed"):
                now_fields.append(("finished_at", "CURRENT_TIMESTAMP"))
            set_sql = (
                "status = %s, client_id = COALESCE(%s, client_id), error_message = %s"
            )
            params = [status, client_id, error_message, task_id]
            if now_fields:
                for field_name, expr in now_fields:
                    set_sql += f", {field_name} = {expr}"
            cursor.execute(
                f"UPDATE sys_skill_install_tasks SET {set_sql} WHERE id = %s",
                tuple(params),
            )

            cursor.execute(
                """
                SELECT id, release_id, target_user_id
                FROM sys_skill_install_tasks
                WHERE id = %s
                """,
                (task_id,),
            )
            task = cursor.fetchone()
            if task and task.get("release_id"):
                target_status = "dispatched"
                if status == "success":
                    target_status = "success"
                elif status == "failed":
                    target_status = "failed"
                cursor.execute(
                    """
                    UPDATE sys_skill_release_targets
                    SET status = %s, latest_task_id = %s, last_error_message = %s
                    WHERE release_id = %s AND target_user_id = %s
                    """,
                    (
                        target_status,
                        task_id,
                        error_message,
                        task["release_id"],
                        task["target_user_id"],
                    ),
                )
                if status in ("success", "failed"):
                    cursor.execute(
                        """
                        SELECT COUNT(*) AS pending_cnt
                        FROM sys_skill_release_targets
                        WHERE release_id = %s AND status IN ('pending', 'dispatched')
                        """,
                        (task["release_id"],),
                    )
                    pending_row = cursor.fetchone()
                    if pending_row and int(pending_row["pending_cnt"]) == 0:
                        cursor.execute(
                            "UPDATE sys_skill_releases SET status = 'completed' WHERE id = %s",
                            (task["release_id"],),
                        )
            conn.commit()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def upsert_inventory(
        client_id: str,
        user_id: Optional[str],
        skill_name: str,
        version: str,
        installed_at: Optional[str] = None,
    ):
        conn = get_db_connection()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            inventory_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO sys_skill_inventories (id, client_id, user_id, skill_name, version, installed_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                user_id = VALUES(user_id),
                version = VALUES(version),
                installed_at = VALUES(installed_at)
                """,
                (inventory_id, client_id, user_id, skill_name, version, installed_at),
            )
            conn.commit()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_enabled_allowed_skills_for_user(user_id: str) -> List[Dict]:
        conn = get_db_connection()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, role_id, dept_id FROM sys_users WHERE id = %s", (user_id,)
            )
            user = cursor.fetchone()
            if not user:
                return []
            # 默认拒绝 + 优先级覆盖：dept < role < user，deny 覆盖 allow
            owner_pairs = []
            if user.get("dept_id"):
                owner_pairs.append(("dept", user["dept_id"]))
            if user.get("role_id"):
                owner_pairs.append(("role", user["role_id"]))
            owner_pairs.append(("user", user_id))
            permission_map: Dict[str, str] = {}
            owner_priority = {
                (owner_type, owner_id): index
                for index, (owner_type, owner_id) in enumerate(owner_pairs)
            }
            where_parts = []
            params: List[str] = []
            for owner_type, owner_id in owner_pairs:
                where_parts.append("(owner_type = %s AND owner_id = %s)")
                params.extend([owner_type, owner_id])
            cursor.execute(
                f"""
                SELECT owner_type, owner_id, skill_name, action
                FROM sys_skill_permissions
                WHERE {" OR ".join(where_parts)}
                """,
                tuple(params),
            )
            permission_rows = cursor.fetchall() or []
            permission_rows.sort(
                key=lambda row: owner_priority.get(
                    (row.get("owner_type"), row.get("owner_id")), -1
                )
            )
            for row in permission_rows:
                action = str(row.get("action", "")).lower()
                if action not in ("allow", "deny"):
                    continue
                permission_map[str(row.get("skill_name") or "")] = action

            effective = [
                skill_name
                for skill_name, action in permission_map.items()
                if action == "allow"
            ]
            if not effective:
                return []
            skills_map = SkillDistributionService.get_skills_map()
            catalog = SkillDistributionService.get_catalog()
            catalog_map = {c["name"]: c for c in catalog}
            package_summary_map = SkillDistributionService.get_package_summary_map(
                effective
            )
            result = []
            for skill_name in effective:
                cfg = skills_map.get(skill_name, {})
                if not cfg.get("enabled", True):
                    continue
                item = catalog_map.get(skill_name)
                if not item:
                    continue
                summary = package_summary_map.get(skill_name, {})
                latest_version = item.get("latest_version", "0.0.1")
                if summary.get("latest_version"):
                    latest_version = str(summary.get("latest_version"))
                result.append(
                    {
                        "name": skill_name,
                        "description": item.get("description", ""),
                        "latest_version": latest_version,
                        "package_id": summary.get("package_id"),
                        "sha256": summary.get("sha256"),
                    }
                )
            return sorted(result, key=lambda x: x["name"])
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_inventory_for_client(client_id: str) -> Dict[str, Dict]:
        conn = get_db_connection()
        if not conn:
            return {}
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT skill_name, version, installed_at
                FROM sys_skill_inventories
                WHERE client_id = %s
                """,
                (client_id,),
            )
            rows = cursor.fetchall()
            return {
                r["skill_name"]: {
                    "version": r["version"],
                    "installed_at": r["installed_at"],
                }
                for r in rows
            }
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def list_pending_tasks_for_user(user_id: str) -> List[Dict]:
        conn = get_db_connection()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, release_id, skill_name, target_version, rollout_batch, retry_policy
                FROM sys_skill_install_tasks
                WHERE target_user_id = %s AND status IN ('pending', 'downloading', 'installing')
                ORDER BY created_at ASC
                """,
                (user_id,),
            )
            return cursor.fetchall()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_package(skill_name: str, version: str) -> Optional[Dict]:
        conn = get_db_connection()
        if not conn:
            return None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, skill_name, version, file_name, file_path, sha256, file_size
                FROM sys_skill_packages
                WHERE skill_name = %s AND version = %s AND is_active = 1
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (skill_name, version),
            )
            return cursor.fetchone()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

    @staticmethod
    def get_latest_active_package(skill_name: str) -> Optional[Dict]:
        versions = SkillDistributionService.get_skill_versions(skill_name)
        active_versions = [
            item
            for item in versions
            if int(item.get("is_active", 0) or 0) == 1 and item.get("file_path")
        ]
        if not active_versions:
            return None
        latest_version = SkillDistributionService._latest_version(
            [str(item["version"]) for item in active_versions]
        )
        selected_rows = [
            item
            for item in active_versions
            if str(item.get("version") or "") == str(latest_version)
        ]
        if not selected_rows:
            return None
        return selected_rows[0]

    @staticmethod
    def fetch_package_archive(package: Dict, target_zip_path: str) -> None:
        file_path = str(package.get("file_path") or "").strip()
        if not file_path:
            raise ValueError("Skill package file path is empty")
        if os.path.exists(file_path):
            shutil.copyfile(file_path, target_zip_path)
            return

        signed_url = OssService.generate_presigned_get_url(file_path, 600)
        try:
            response = requests.get(signed_url, stream=True, timeout=120)
        except Exception as exc:
            raise ValueError(
                f"Failed to download package from OSS: {str(exc)}"
            ) from exc

        try:
            if response.status_code >= 400:
                raise ValueError("OSS package download URL is unavailable or expired")
            with open(target_zip_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        finally:
            response.close()

    @staticmethod
    def extract_package_to_dir(package: Dict, target_dir: str) -> str:
        os.makedirs(target_dir, exist_ok=True)
        zip_file_name = package.get("file_name") or f"{package['skill_name']}.zip"
        zip_path = os.path.join(target_dir, os.path.basename(zip_file_name))
        SkillDistributionService.fetch_package_archive(package, zip_path)

        extract_dir = os.path.join(target_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            abs_target = os.path.abspath(extract_dir)
            for member in zip_ref.infolist():
                member_name = member.filename.replace("\\", "/")
                if member_name.startswith("/") or ".." in member_name.split("/"):
                    raise ValueError("Invalid ZIP path")
                member_target = os.path.abspath(os.path.join(extract_dir, member_name))
                if not member_target.startswith(abs_target):
                    raise ValueError("Invalid ZIP path")
            zip_ref.extractall(extract_dir)
        return extract_dir

    @staticmethod
    def stage_latest_skill_package(
        skill_name: str, target_dir: str
    ) -> Tuple[Dict, str]:
        package = SkillDistributionService.get_latest_active_package(skill_name)
        if not package:
            raise ValueError("Skill package not found")
        extract_dir = SkillDistributionService.extract_package_to_dir(
            package, target_dir
        )
        return package, extract_dir

    @staticmethod
    def create_download_token(
        package_id: str, client_id: str, expires_seconds: int = 600
    ) -> str:
        token = str(uuid.uuid4())
        SkillDistributionService._download_tokens[token] = {
            "package_id": package_id,
            "client_id": client_id,
            "expire_at": datetime.now(timezone.utc)
            + timedelta(seconds=expires_seconds),
        }
        return token

    @staticmethod
    def resolve_download_token(token: str, client_id: str) -> Optional[Dict]:
        payload = SkillDistributionService._download_tokens.get(token)
        if not payload:
            return None
        if payload["client_id"] != client_id:
            return None
        if datetime.now(timezone.utc) > payload["expire_at"]:
            SkillDistributionService._download_tokens.pop(token, None)
            return None
        conn = get_db_connection()
        if not conn:
            return None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, skill_name, version, file_name, file_path, sha256, file_size FROM sys_skill_packages WHERE id = %s AND is_active = 1",
                (payload["package_id"],),
            )
            return cursor.fetchone()
        finally:
            if conn.is_connected():
                cursor.close()
                conn.close()

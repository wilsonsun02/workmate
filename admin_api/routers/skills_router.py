import json
import os
import tempfile
import uuid
import zipfile
import requests
from fastapi import APIRouter, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from typing import Dict, List, Optional
from admin_api.models.init_db import get_db_connection
from admin_api.services.config_service import ConfigService
from admin_api.services.oss_service import OssService
from admin_api.services.skill_distribution_service import SkillDistributionService
from admin_api.services.agent_runtime_service import notify_agent_reload

router = APIRouter()


class SkillConfig(BaseModel):
    name: str
    description: Optional[str] = None
    enabled: bool = True


class SkillCatalogItemResponse(BaseModel):
    name: str
    description: Optional[str] = None
    enabled: bool = True
    latest_version: Optional[str] = None
    package_count: int = 0
    oss_packaged: bool = False


class PaginatedSkillsResponse(BaseModel):
    success: bool = True
    data: List[SkillCatalogItemResponse]
    total: int
    page: int
    page_size: int


class InstallTaskCreateRequest(BaseModel):
    owner_type: str
    owner_id: str
    skill_name: str
    version: Optional[str] = None


class ReleaseCreateRequest(BaseModel):
    skill_name: str
    version: str
    rollout_type: str  # user | role | dept
    rollout_id: str
    strategy: str = "hybrid"  # active | passive | hybrid
    batch_size: Optional[int] = None
    failure_threshold: Optional[float] = None
    created_by: Optional[str] = None


class ReleaseDispatchRequest(BaseModel):
    rollout_batch: Optional[int] = None


class ReleaseRollbackRequest(BaseModel):
    rollback_version: str


class SkillFileSaveRequest(BaseModel):
    path: str
    content: str


def get_install_trigger_mode() -> str:
    env_cfg = ConfigService.get_config("env_config", {})
    mode = str(env_cfg.get("SKILL_INSTALL_TRIGGER_MODE", "hybrid")).lower()
    if mode not in ("active", "passive", "hybrid"):
        return "hybrid"
    return mode


def safe_extract_zip(zip_ref: zipfile.ZipFile, target_dir: str):
    abs_target = os.path.abspath(target_dir)
    for member in zip_ref.infolist():
        member_name = member.filename.replace("\\", "/")
        if member_name.startswith("/") or ".." in member_name.split("/"):
            raise HTTPException(status_code=400, detail="Invalid ZIP path")
        member_target = os.path.abspath(os.path.join(target_dir, member_name))
        if not member_target.startswith(abs_target):
            raise HTTPException(status_code=400, detail="Invalid ZIP path")
    zip_ref.extractall(target_dir)


async def _dispatch_tasks_to_online_clients(
    request: Request,
    skill_name: str,
    version: str,
    package: Dict,
    tasks: List[Dict],
    release_id: Optional[str] = None,
    rollout_batch: int = 0,
    retry_policy: Optional[Dict] = None,
) -> int:
    from admin_api.routers.client_router import manager

    dispatched = 0
    for task in tasks:
        conn_key = f"user_{task['target_user_id']}"
        ws = manager.active_connections.get(conn_key)
        if not ws:
            continue
        package_path = package.get("file_path", "")
        download_url = ""
        if package_path:
            if os.path.exists(package_path):
                token = SkillDistributionService.create_download_token(
                    package["id"], conn_key
                )
                download_url = f"{request.base_url}api/admin/skills/packages/{package['id']}/download?token={token}&client_id={conn_key}"
            else:
                download_url = OssService.generate_presigned_get_url(package_path, 600)
        try:
            await ws.send_text(
                json.dumps(
                    {
                        "action": "install_skill",
                        "task_id": task["task_id"],
                        "release_id": release_id,
                        "rollout_batch": int(rollout_batch or 0),
                        "retry_policy": retry_policy
                        or SkillDistributionService.default_retry_policy(),
                        "skill_name": skill_name,
                        "version": version,
                        "download_url": download_url,
                        "sha256": package["sha256"],
                    }
                )
            )
            dispatched += 1
        except Exception:
            pass
    return dispatched


@router.get("/", response_model=List[SkillConfig])
async def get_skills():
    try:
        data = SkillDistributionService.get_skills_map()
        skills = []
        for name, config in data.items():
            if bool(config.get("deleted", False)):
                continue
            skills.append(
                SkillConfig(
                    name=name,
                    description=config.get("description"),
                    enabled=config.get("enabled", True),
                )
            )
        return skills
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to read Skills config: {str(e)}"
        )


@router.put("/", response_model=List[SkillConfig])
async def save_skills(skills: List[SkillConfig]):
    merged_map = SkillDistributionService.get_skills_map()
    for item in skills:
        existing = merged_map.get(item.name, {})
        merged_map[item.name] = {
            "description": item.description or existing.get("description", ""),
            "enabled": bool(item.enabled),
            "deleted": bool(existing.get("deleted", False)),
        }
    ok = SkillDistributionService.save_skills_map(merged_map)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save skills config")
    await notify_agent_reload("skills_config_updated")
    return [
        SkillConfig(
            name=k,
            description=v.get("description"),
            enabled=bool(v.get("enabled", True)),
        )
        for k, v in merged_map.items()
    ]


@router.get("/catalog")
async def get_skill_catalog():
    return {"success": True, "data": SkillDistributionService.get_catalog()}


@router.get("/paginated", response_model=PaginatedSkillsResponse)
async def get_skills_paginated(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str = Query("", description="Search by skill name or description"),
):
    catalog = SkillDistributionService.get_catalog()
    keyword = (keyword or "").strip().lower()
    if keyword:
        catalog = [
            item
            for item in catalog
            if keyword in str(item.get("name") or "").lower()
            or keyword in str(item.get("description") or "").lower()
        ]
    total = len(catalog)
    start = (page - 1) * page_size
    end = start + page_size
    page_data = catalog[start:end]
    items = [
        SkillCatalogItemResponse(
            name=item["name"],
            description=item.get("description"),
            enabled=item.get("enabled", True),
            latest_version=item.get("latest_version"),
            package_count=int(item.get("package_count") or 0),
            oss_packaged=int(item.get("package_count") or 0) > 0,
        )
        for item in page_data
    ]
    return PaginatedSkillsResponse(
        data=items, total=total, page=page, page_size=page_size
    )


@router.get("/install-tasks")
async def get_install_tasks(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return {
        "success": True,
        "data": SkillDistributionService.list_install_tasks(
            status=status, limit=limit, offset=offset
        ),
    }


@router.post("/package-all")
async def package_all_skills():
    result = SkillDistributionService.package_all_skills_to_oss()
    await notify_agent_reload("skills_packaged")
    return {"success": True, "data": result}


@router.post("/install-tasks")
async def create_install_tasks(payload: InstallTaskCreateRequest, request: Request):
    if payload.owner_type not in ("user", "role", "dept"):
        raise HTTPException(status_code=400, detail="Invalid owner_type")
    versions = SkillDistributionService.get_skill_versions(payload.skill_name)
    if not versions:
        raise HTTPException(status_code=404, detail="Skill package not found")
    target_version = payload.version
    if not target_version:
        target_version = SkillDistributionService._latest_version(
            [v["version"] for v in versions]
        )
    selected_rows = [v for v in versions if v["version"] == target_version]
    if not selected_rows:
        raise HTTPException(status_code=404, detail="Target version not found")
    package = selected_rows[0]
    created_tasks = SkillDistributionService.create_install_tasks(
        payload.owner_type, payload.owner_id, payload.skill_name, target_version
    )
    dispatched = 0
    trigger_mode = get_install_trigger_mode()
    if trigger_mode in ("active", "hybrid"):
        dispatched = await _dispatch_tasks_to_online_clients(
            request=request,
            skill_name=payload.skill_name,
            version=target_version,
            package=package,
            tasks=created_tasks,
            retry_policy=SkillDistributionService.default_retry_policy(),
        )
    return {
        "success": True,
        "data": {
            "trigger_mode": trigger_mode,
            "created": len(created_tasks),
            "dispatched": dispatched,
            "tasks": created_tasks,
        },
    }


@router.get("/releases")
async def get_releases(
    skill_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    data = SkillDistributionService.list_releases(
        skill_name=skill_name, status=status, limit=limit, offset=offset
    )
    return {"success": True, "data": data}


@router.post("/releases")
async def create_release(payload: ReleaseCreateRequest):
    versions = SkillDistributionService.get_skill_versions(payload.skill_name)
    if not versions:
        raise HTTPException(status_code=404, detail="Skill package not found")
    selected_rows = [v for v in versions if v["version"] == payload.version]
    if not selected_rows:
        raise HTTPException(status_code=404, detail="Target version not found")
    try:
        release = SkillDistributionService.create_release(
            skill_name=payload.skill_name,
            version=payload.version,
            rollout_type=payload.rollout_type,
            rollout_id=payload.rollout_id,
            strategy=payload.strategy,
            batch_size=payload.batch_size,
            failure_threshold=payload.failure_threshold,
            created_by=payload.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "data": release}


@router.get("/releases/{release_id}")
async def get_release_detail(release_id: str):
    release = SkillDistributionService.get_release(release_id)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    return {"success": True, "data": release}


@router.get("/releases/{release_id}/targets")
async def get_release_targets(release_id: str):
    return {
        "success": True,
        "data": SkillDistributionService.list_release_targets(release_id),
    }


@router.post("/releases/{release_id}/dispatch")
async def dispatch_release(
    release_id: str, payload: ReleaseDispatchRequest, request: Request
):
    release = SkillDistributionService.get_release(release_id)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    package = SkillDistributionService.get_package(
        release["skill_name"], release["version"]
    )
    if not package:
        raise HTTPException(status_code=404, detail="Release package not found")
    try:
        result = SkillDistributionService.dispatch_release_batch(
            release_id, payload.rollout_batch
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    dispatched = 0
    trigger_mode = get_install_trigger_mode()
    if trigger_mode in ("active", "hybrid") and result["tasks"]:
        dispatched = await _dispatch_tasks_to_online_clients(
            request=request,
            skill_name=release["skill_name"],
            version=release["version"],
            package=package,
            tasks=result["tasks"],
            release_id=release_id,
            rollout_batch=result.get("rollout_batch", 0),
            retry_policy=SkillDistributionService.default_retry_policy(),
        )
    return {
        "success": True,
        "data": {
            "trigger_mode": trigger_mode,
            "release_id": release_id,
            "rollout_batch": result.get("rollout_batch", 0),
            "created": result.get("created", 0),
            "dispatched": dispatched,
            "tasks": result.get("tasks", []),
        },
    }


@router.post("/releases/{release_id}/pause")
async def pause_release(release_id: str):
    release = SkillDistributionService.get_release(release_id)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    SkillDistributionService.update_release_status(release_id, "paused")
    return {"success": True, "message": "Release paused"}


@router.post("/releases/{release_id}/resume")
async def resume_release(release_id: str):
    release = SkillDistributionService.get_release(release_id)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    SkillDistributionService.update_release_status(release_id, "running")
    return {"success": True, "message": "Release resumed"}


@router.post("/releases/{release_id}/rollback")
async def rollback_release(
    release_id: str, payload: ReleaseRollbackRequest, request: Request
):
    release = SkillDistributionService.get_release(release_id)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    package = SkillDistributionService.get_package(
        release["skill_name"], payload.rollback_version
    )
    if not package:
        raise HTTPException(status_code=404, detail="Rollback package not found")
    try:
        result = SkillDistributionService.rollback_release(
            release_id=release_id, rollback_version=payload.rollback_version
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    dispatched = 0
    trigger_mode = get_install_trigger_mode()
    if trigger_mode in ("active", "hybrid") and result["tasks"]:
        dispatched = await _dispatch_tasks_to_online_clients(
            request=request,
            skill_name=release["skill_name"],
            version=payload.rollback_version,
            package=package,
            tasks=result["tasks"],
            release_id=release_id,
            rollout_batch=0,
            retry_policy=SkillDistributionService.default_retry_policy(),
        )
    return {
        "success": True,
        "data": {
            "trigger_mode": trigger_mode,
            "release_id": release_id,
            "rollback_version": payload.rollback_version,
            "created": result["created"],
            "dispatched": dispatched,
            "tasks": result["tasks"],
        },
    }


@router.get("/{skill_name}/versions")
async def get_skill_versions(skill_name: str):
    return {
        "success": True,
        "data": SkillDistributionService.get_skill_versions(skill_name),
    }


@router.get("/packages/{package_id}/download")
async def download_skill_package(package_id: str, token: str, client_id: str):
    package = SkillDistributionService.resolve_download_token(token, client_id)
    if not package:
        raise HTTPException(status_code=403, detail="Invalid or expired token")
    if package["id"] != package_id:
        raise HTTPException(status_code=403, detail="Token mismatch")
    file_path = package["file_path"]
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path, filename=package["file_name"], media_type="application/zip"
        )
    signed_url = OssService.generate_presigned_get_url(file_path, 600)
    return RedirectResponse(url=signed_url)


@router.get("/{skill_name}/download-latest")
async def download_latest_skill_package(skill_name: str):
    versions = SkillDistributionService.get_skill_versions(skill_name)
    if not versions:
        raise HTTPException(status_code=404, detail="该技能未打包到 OSS")

    active_versions = [
        v
        for v in versions
        if int(v.get("is_active", 0) or 0) == 1 and v.get("file_path")
    ]
    if not active_versions:
        raise HTTPException(status_code=404, detail="该技能未打包到 OSS")

    latest_version = SkillDistributionService._latest_version(
        [str(v["version"]) for v in active_versions]
    )
    selected_rows = [
        v for v in active_versions if str(v["version"]) == str(latest_version)
    ]
    if not selected_rows:
        raise HTTPException(status_code=404, detail="未找到最新可下载技能包")

    package = selected_rows[0]
    file_path = package.get("file_path", "")
    file_name = package.get("file_name") or f"{skill_name}-{latest_version}.zip"

    if file_path and os.path.exists(file_path):
        return FileResponse(
            path=file_path, filename=file_name, media_type="application/zip"
        )

    signed_url = OssService.generate_presigned_get_url(file_path, 600)
    try:
        remote_resp = requests.get(signed_url, stream=True, timeout=120)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"拉取 OSS 文件失败: {str(e)}")

    if remote_resp.status_code >= 400:
        remote_resp.close()
        raise HTTPException(status_code=502, detail="OSS 下载地址不可用或已过期")

    def iter_remote_content():
        try:
            for chunk in remote_resp.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            remote_resp.close()

    media_type = remote_resp.headers.get("Content-Type") or "application/zip"
    headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
    content_length = remote_resp.headers.get("Content-Length")
    if content_length:
        headers["Content-Length"] = content_length

    return StreamingResponse(
        iter_remote_content(),
        media_type=media_type,
        headers=headers,
    )


@router.get("/{skill_name}/files")
async def get_skill_files(skill_name: str):
    try:
        with tempfile.TemporaryDirectory() as td:
            package, skill_root = SkillDistributionService.stage_latest_skill_package(
                skill_name, td
            )
            updated_at = int(
                package.get("updated_at").timestamp()
                if package.get("updated_at")
                else package.get("created_at").timestamp()
                if package.get("created_at")
                else 0
            )
            nodes = []
            for root, dirs, files in os.walk(skill_root):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                rel_dir = os.path.relpath(root, skill_root)
                rel_dir = "" if rel_dir == "." else rel_dir.replace("\\", "/")
                for d in sorted(dirs):
                    rel_path = f"{rel_dir}/{d}".strip("/") if rel_dir else d
                    nodes.append(
                        {
                            "path": rel_path,
                            "is_dir": True,
                            "is_text": False,
                            "size": 0,
                            "updated_at": updated_at,
                        }
                    )
                for f in sorted(files):
                    rel_path = f"{rel_dir}/{f}".strip("/") if rel_dir else f
                    full_path = os.path.join(root, f)
                    nodes.append(
                        {
                            "path": rel_path,
                            "is_dir": False,
                            "is_text": SkillDistributionService.is_text_file(rel_path),
                            "size": os.path.getsize(full_path),
                            "updated_at": updated_at,
                        }
                    )
        return {"success": True, "data": nodes}
    except ValueError as e:
        if str(e) == "Skill package not found":
            raise HTTPException(
                status_code=404, detail="该技能暂无可编辑的已上传技能包"
            )
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{skill_name}/files/content")
async def get_skill_file_content(skill_name: str, path: str):
    try:
        with tempfile.TemporaryDirectory() as td:
            _, skill_root = SkillDistributionService.stage_latest_skill_package(
                skill_name, td
            )
            abs_path = SkillDistributionService.safe_relpath_under_root(
                skill_root, path
            )
            if not os.path.exists(abs_path) or os.path.isdir(abs_path):
                raise HTTPException(status_code=404, detail="File not found")
            if not SkillDistributionService.is_text_file(path):
                raise HTTPException(
                    status_code=400, detail="Binary file is not editable online"
                )
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=400, detail="Binary file is not editable online"
                )
            return {"success": True, "data": {"path": path, "content": content}}
    except ValueError as e:
        if str(e) == "Skill package not found":
            raise HTTPException(
                status_code=404, detail="该技能暂无可编辑的已上传技能包"
            )
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{skill_name}/files/content")
async def save_skill_file_content(skill_name: str, payload: SkillFileSaveRequest):
    try:
        with tempfile.TemporaryDirectory() as td:
            package, skill_root = SkillDistributionService.stage_latest_skill_package(
                skill_name, td
            )
            abs_path = SkillDistributionService.safe_relpath_under_root(
                skill_root, payload.path
            )
            if not os.path.exists(abs_path) or os.path.isdir(abs_path):
                raise HTTPException(status_code=404, detail="File not found")
            if not SkillDistributionService.is_text_file(payload.path):
                raise HTTPException(
                    status_code=400, detail="Binary file is not editable online"
                )
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(payload.content)

            current_version = str(package.get("version") or "0.0.1")
            package_desc = str(package.get("description") or "")
            if os.path.exists(os.path.join(skill_root, "SKILL.md")):
                parsed_name, parsed_desc, _ = SkillDistributionService.parse_skill_md(
                    skill_root
                )
                if parsed_name and parsed_name != skill_name:
                    raise HTTPException(
                        status_code=400, detail="SKILL.md 中的技能名称不可修改"
                    )
                SkillDistributionService.upsert_skill_md_frontmatter(
                    skill_root=skill_root,
                    name=skill_name,
                    description=parsed_desc or package_desc,
                    version=current_version,
                )
                package_desc = parsed_desc or package_desc

            zip_file_name = (
                package.get("file_name") or f"{skill_name}-{current_version}.zip"
            )
            zip_path = os.path.join(td, os.path.basename(zip_file_name))
            SkillDistributionService.build_skill_zip(skill_root, zip_path)
            package_sha256 = SkillDistributionService.file_sha256(zip_path)
            package_size = os.path.getsize(zip_path)
            object_key = OssService.normalize_object_key(skill_name, current_version)
            OssService.upload_file(zip_path, object_key)
            SkillDistributionService.record_skill_package(
                skill_name=skill_name,
                version=current_version,
                description=package_desc,
                file_name=os.path.basename(zip_file_name),
                file_path=object_key,
                sha256=package_sha256,
                file_size=package_size,
            )

            data = SkillDistributionService.get_skills_map()
            current_enabled = data.get(skill_name, {}).get("enabled", False)
            data[skill_name] = {
                "description": package_desc,
                "enabled": current_enabled,
                "deleted": False,
            }
            SkillDistributionService.save_skills_map(data)
            SkillDistributionService.invalidate_catalog_cache()
            return {
                "success": True,
                "message": "File saved",
                "data": {"version": current_version},
            }
    except ValueError as e:
        if str(e) == "Skill package not found":
            raise HTTPException(
                status_code=404, detail="该技能暂无可编辑的已上传技能包"
            )
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{skill_name}/publish")
async def publish_skill(skill_name: str):
    try:
        with tempfile.TemporaryDirectory() as td:
            package, skill_root = SkillDistributionService.stage_latest_skill_package(
                skill_name, td
            )
            _, parsed_desc, _ = SkillDistributionService.parse_skill_md(skill_root)
            final_skill_name = skill_name
            new_version = SkillDistributionService.next_patch_version(final_skill_name)
            SkillDistributionService.upsert_skill_md_frontmatter(
                skill_root=skill_root,
                name=final_skill_name,
                description=parsed_desc or str(package.get("description") or ""),
                version=new_version,
            )

            zip_file_name = f"{final_skill_name}-{new_version}-{uuid.uuid4().hex}.zip"
            zip_path = os.path.join(td, zip_file_name)
            SkillDistributionService.build_skill_zip(skill_root, zip_path)
            package_sha256 = SkillDistributionService.file_sha256(zip_path)
            package_size = os.path.getsize(zip_path)
            object_key = OssService.normalize_object_key(final_skill_name, new_version)
            OssService.upload_file(zip_path, object_key)
            SkillDistributionService.record_skill_package(
                skill_name=final_skill_name,
                version=new_version,
                description=parsed_desc or str(package.get("description") or ""),
                file_name=zip_file_name,
                file_path=object_key,
                sha256=package_sha256,
                file_size=package_size,
            )

            data = SkillDistributionService.get_skills_map()
            current_enabled = data.get(final_skill_name, {}).get("enabled", False)
            data[final_skill_name] = {
                "description": parsed_desc or str(package.get("description") or ""),
                "enabled": current_enabled,
                "deleted": False,
            }
            SkillDistributionService.save_skills_map(data)
    except ValueError as e:
        if str(e) == "Skill package not found":
            raise HTTPException(status_code=404, detail="Skill package not found")
        raise HTTPException(status_code=400, detail=str(e))
    await notify_agent_reload("skill_published")

    return {
        "success": True,
        "data": {
            "name": final_skill_name,
            "version": new_version,
            "file_path": object_key,
        },
    }


@router.post("/upload")
async def upload_skill(file: UploadFile = File(...)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_zip_path = os.path.join(temp_dir, file.filename)
            with open(temp_zip_path, "wb") as buffer:
                buffer.write(await file.read())

            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                safe_extract_zip(zip_ref, extract_dir)

            skill_root = extract_dir
            items = os.listdir(extract_dir)
            if len(items) == 1 and os.path.isdir(os.path.join(extract_dir, items[0])):
                skill_root = os.path.join(extract_dir, items[0])

            skill_md_path = os.path.join(skill_root, "SKILL.md")
            if not os.path.exists(skill_md_path):
                raise HTTPException(
                    status_code=400, detail="SKILL.md not found in the ZIP package"
                )

            skill_name, skill_desc, _ = SkillDistributionService.parse_skill_md(
                skill_root
            )
            if not skill_name:
                raise HTTPException(
                    status_code=400,
                    detail="Could not parse 'name' from SKILL.md YAML frontmatter",
                )
            new_version = SkillDistributionService.next_patch_version(skill_name)
            SkillDistributionService.upsert_skill_md_frontmatter(
                skill_root=skill_root,
                name=skill_name,
                description=skill_desc or "",
                version=new_version,
            )

            data = SkillDistributionService.get_skills_map()
            current_enabled = data.get(skill_name, {}).get("enabled", False)
            data[skill_name] = {
                "description": skill_desc,
                "enabled": current_enabled,
                "deleted": False,
            }
            SkillDistributionService.save_skills_map(data)

            package_file_name = f"{skill_name}-{new_version}-{uuid.uuid4().hex}.zip"
            rebuilt_zip_path = os.path.join(temp_dir, package_file_name)
            SkillDistributionService.build_skill_zip(skill_root, rebuilt_zip_path)
            package_sha256 = SkillDistributionService.file_sha256(rebuilt_zip_path)
            package_size = os.path.getsize(rebuilt_zip_path)
            object_key = OssService.normalize_object_key(skill_name, new_version)
            OssService.upload_file(rebuilt_zip_path, object_key)
            SkillDistributionService.record_skill_package(
                skill_name=skill_name,
                version=new_version,
                description=skill_desc,
                file_name=package_file_name,
                file_path=object_key,
                sha256=package_sha256,
                file_size=package_size,
            )
            SkillDistributionService.invalidate_catalog_cache()

            return {
                "success": True,
                "message": f"Skill '{skill_name}' uploaded successfully",
                "name": skill_name,
                "version": new_version,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{skill_name}")
async def delete_skill(skill_name: str):
    try:
        data = SkillDistributionService.get_skills_map()
        existing = data.get(skill_name, {})
        data[skill_name] = {
            "description": existing.get("description", ""),
            "enabled": False,
            "deleted": True,
        }
        SkillDistributionService.save_skills_map(data)

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE sys_skill_packages SET is_active = 0 WHERE skill_name = %s",
                    (skill_name,),
                )
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                if conn.is_connected():
                    cursor.close()
                    conn.close()

        SkillDistributionService.invalidate_catalog_cache()

        await notify_agent_reload("skill_deleted")

        return {
            "success": True,
            "message": f"Skill '{skill_name}' deleted successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{skill_name}/allocations")
async def get_skill_allocations(skill_name: str):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT p.owner_id, p.action, u.username 
            FROM sys_skill_permissions p
            JOIN sys_users u ON p.owner_id = u.id
            WHERE p.skill_name = %s AND p.owner_type = 'user'
        """,
            (skill_name,),
        )
        users = cursor.fetchall()
        cursor.execute(
            """
            SELECT p.owner_id, p.action, r.name as role_name 
            FROM sys_skill_permissions p
            JOIN sys_roles r ON p.owner_id = r.id
            WHERE p.skill_name = %s AND p.owner_type = 'role'
        """,
            (skill_name,),
        )
        roles = cursor.fetchall()
        cursor.execute(
            """
            SELECT p.owner_id, p.action, d.name as dept_name 
            FROM sys_skill_permissions p
            JOIN sys_departments d ON p.owner_id = d.id
            WHERE p.skill_name = %s AND p.owner_type = 'dept'
        """,
            (skill_name,),
        )
        depts = cursor.fetchall()

        return {
            "success": True,
            "data": {"users": users, "roles": roles, "depts": depts},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

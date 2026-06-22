"""任务完成后的后评估器模块。

不依赖 LLM 在任务执行中主动调用 MCP 工具，而是在任务结束后独立发起评估。
直接调用底层 Python 函数执行偏好保存、技能创建和改进，绕过 MCP 协议。
"""

import os
import re
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List

from loguru import logger
from langchain_core.messages import HumanMessage

from workflow.config import (
    BASE_DIR,
    SKILLS_DIR,
    SKILLS_BASE_DIR,
    POST_TASK_EVALUATION_ENABLED,
    POST_TASK_EVALUATION_PREFERENCE,
    POST_TASK_EVALUATION_SKILL_CREATE,
    POST_TASK_EVALUATION_SKILL_IMPROVE,
    POST_TASK_EVALUATION_LLM_TIMEOUT,
)


class PostTaskEvaluator:
    """任务完成后的确定性评估器，不依赖 LLM 自主判断"""

    def __init__(self):
        self.llm = None
        self._prompts_cache: Dict[str, str] = {}

    def _get_llm(self):
        if self.llm is None:
            from workflow.model import mcp_llm

            self.llm = mcp_llm
        return self.llm

    def _load_prompt(self, template_name: str) -> str:
        """加载评估提示词模板"""
        if template_name in self._prompts_cache:
            return self._prompts_cache[template_name]
        template_path = os.path.join(BASE_DIR, "prompt", template_name)
        if not os.path.exists(template_path):
            logger.warning(f"[后评估] 提示词模板不存在: {template_path}")
            return ""
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        self._prompts_cache[template_name] = content
        return content

    # ============================================================
    # 偏好提取评估
    # ============================================================

    async def evaluate_preferences(
        self,
        user_input: str,
        full_final_content: str,
        contact_name: str,
        session_id: str,
        full_conversation: str,
    ) -> None:
        """评估是否需要保存用户偏好（统一走 LLM 提取，保存前去重）"""
        if not POST_TASK_EVALUATION_PREFERENCE:
            return
        if not contact_name:
            logger.info("[后评估-偏好] 无联系人名称，跳过")
            return

        llm_preferences = await self._llm_extract_preferences(
            user_input, full_final_content, full_conversation
        )
        if not llm_preferences:
            logger.info("[后评估-偏好] 未发现可保存的偏好")
            return

        # 加载已有偏好，LLM 去重后再保存
        existing = self._load_existing_preferences(contact_name)
        new_preferences = await self._deduplicate_preferences(llm_preferences, existing)
        if new_preferences:
            self._save_preferences(contact_name, new_preferences)
        else:
            logger.info("[后评估-偏好] 新偏好与已有偏好重复，跳过保存")

    def _load_existing_preferences(self, contact_name: str) -> List[Dict[str, str]]:
        """从 MySQL 加载已有偏好（直接查表，不走格式化函数）"""
        try:
            from workflow.report_tools import get_db_connection, _get_agent_username

            agent = _get_agent_username()
            conn = get_db_connection()
            if not conn:
                return []
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT pref_key, pref_value FROM user_preferences "
                    "WHERE agent_username = %s AND contact_name = %s",
                    (agent, contact_name),
                )
                rows = cur.fetchall()
                return [{"pref_key": k, "pref_value": v} for k, v in rows if k and v]
            finally:
                if conn.is_connected():
                    cur.close()
                    conn.close()
        except Exception as e:
            logger.warning(f"[后评估-偏好] 加载已有偏好失败: {e}")
            return []

    async def _deduplicate_preferences(
        self,
        new_prefs: List[Dict[str, str]],
        existing_prefs: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        """用 LLM 比较新旧偏好，过滤掉语义重复的条目"""
        if not existing_prefs:
            logger.info(
                f"[后评估-偏好去重] 无已有偏好，全部视为新偏好 ({len(new_prefs)} 条)"
            )
            return new_prefs

        existing_json = json.dumps(existing_prefs, ensure_ascii=False, indent=2)
        new_json = json.dumps(new_prefs, ensure_ascii=False, indent=2)

        prompt = (
            "你是偏好去重判断器。以下是用户已有的偏好和本次新解析出的偏好。\n\n"
            "## 已有偏好\n"
            f"{existing_json}\n\n"
            "## 新解析出的偏好\n"
            f"{new_json}\n\n"
            "## 任务\n"
            "逐条检查新解析出的偏好，判断每条是否与已有偏好**语义重复**（表述不同但含义相同）。\n"
            "例如：'图片文本要求：中文字' 与 '图片文字语言：中文' 语义重复。\n"
            "'极简商务风格' 与 '简约风' 语义重复。\n\n"
            "返回 JSON 数组，列出**不重复**的新偏好索引（从0开始）：\n"
            '{"unique_indices": [0, 2, 4]}\n\n'
            "如果全部重复，返回：\n"
            '{"unique_indices": []}\n\n'
            "只返回 JSON，不要其他内容。"
        )

        try:
            llm = self._get_llm()
            response = await asyncio.wait_for(
                llm.ainvoke([HumanMessage(content=prompt)]),
                timeout=POST_TASK_EVALUATION_LLM_TIMEOUT,
            )
            result_text = response.content.strip()
            json_match = re.search(r"\{.*?\}", result_text, re.DOTALL)
            if not json_match:
                logger.warning(
                    f"[后评估-偏好去重] LLM 返回无法解析: {result_text[:200]}"
                )
                return []  # 安全起见，不保存

            result = json.loads(json_match.group())
            unique_indices = result.get("unique_indices", [])

            deduped = [new_prefs[i] for i in unique_indices if 0 <= i < len(new_prefs)]
            skipped = len(new_prefs) - len(deduped)
            if skipped > 0:
                logger.info(
                    f"[后评估-偏好去重] 过滤 {skipped} 条重复偏好，保留 {len(deduped)} 条新偏好"
                )
            return deduped
        except asyncio.TimeoutError:
            logger.warning("[后评估-偏好去重] LLM 调用超时，跳过保存")
            return []
        except Exception as e:
            logger.warning(f"[后评估-偏好去重] LLM 调用失败: {e}，跳过保存")
            return []

    async def _llm_extract_preferences(
        self, user_input: str, full_final_content: str, full_conversation: str
    ) -> List[Dict[str, str]]:
        """LLM 语义分析提取偏好"""
        prompt_template = self._load_prompt("POST_TASK_EVAL_PREFERENCE.md")
        if not prompt_template:
            return []

        prompt = prompt_template.replace("{user_input}", user_input[:500])
        prompt = prompt.replace("{ai_reply}", full_final_content[:1000])
        if full_conversation:
            prompt = prompt.replace("{full_conversation}", full_conversation[:3000])

        try:
            llm = self._get_llm()
            response = await asyncio.wait_for(
                llm.ainvoke([HumanMessage(content=prompt)]),
                timeout=POST_TASK_EVALUATION_LLM_TIMEOUT,
            )
            result_text = response.content.strip()

            # 解析 LLM 返回的 JSON
            if result_text.startswith("[") or result_text.startswith("```"):
                json_str = re.search(r"\[.*?\]", result_text, re.DOTALL)
                if json_str:
                    preferences = json.loads(json_str.group())
                    return [
                        p
                        for p in preferences
                        if p.get("pref_key") and p.get("pref_value")
                    ]
            return []
        except asyncio.TimeoutError:
            logger.warning("[后评估-偏好] LLM 调用超时")
            return []
        except Exception as e:
            logger.warning(f"[后评估-偏好] LLM 语义分析失败: {e}")
            return []

    def _save_preferences(
        self, contact_name: str, preferences: List[Dict[str, str]]
    ) -> None:
        """直接调用底层 Python 函数保存偏好"""
        try:
            from workflow.report_tools import save_user_preference

            logger.info(
                f"[后评估-偏好] ★ 开始保存偏好 | 联系人: {contact_name} | 偏好数量: {len(preferences)}"
            )
            for pref in preferences:
                save_user_preference(
                    contact_name,
                    pref["pref_key"],
                    pref["pref_value"],
                )
                logger.info(
                    f"[后评估-偏好] ★ 已保存 | contact_name={contact_name} | pref_key={pref['pref_key']} | pref_value={pref['pref_value']}"
                )
        except Exception as e:
            logger.error(
                f"[后评估-偏好] ★ 保存偏好失败 | contact_name={contact_name} | 错误: {e}"
            )

    # ============================================================
    # 技能创建评估
    # ============================================================

    async def evaluate_skill_creation(
        self,
        user_input: str,
        full_final_content: str,
        full_conversation: str,
        username: str,
        thread_id: str,
        session_id: str,
    ) -> None:
        """评估是否需要创建新技能"""
        if not POST_TASK_EVALUATION_SKILL_CREATE:
            return

        # 1. 加载最近5个任务的压缩对话（只保留步骤和决策，用于提炼执行模式）
        recent_tasks_text = await self._load_recent_compressed_conversations(limit=5)
        if not recent_tasks_text:
            logger.info("[后评估-技能创建] 无法加载最近任务对话，跳过")
            return

        # 2. 查找历史相似任务的压缩对话（排除最近5个）
        similar_tasks_text = await self._find_similar_compressed_conversations(
            user_input, username
        )

        # 3. 全量检查技能使用（仅记录，不做硬阻断——无关任务使用技能不能作为跳过依据）
        has_skill_usage = self._check_skills_usage_in_all(
            current_conv=full_conversation,
            recent_tasks=recent_tasks_text,
            similar_tasks=similar_tasks_text,
        )
        if has_skill_usage:
            logger.info(
                "[后评估-技能创建] 检测到全局技能使用记录（将交由 LLM 判断是否与当前任务相关）"
            )

        # 4. LLM 综合评估：从压缩对话中提取执行模式
        eval_result = await self._llm_evaluate_skill_creation(
            user_input=user_input,
            full_final_content=full_final_content,
            similar_tasks=similar_tasks_text or "",
            recent_tasks=recent_tasks_text,
        )
        if not eval_result or not eval_result.get("should_create"):
            reason = (
                eval_result.get("reason", "未提供原因")
                if eval_result
                else "LLM 返回为空"
            )
            logger.info(f"[后评估-技能创建] LLM 判断无需创建技能，原因: {reason}")
            return

        # 5. 直接调用底层函数创建技能
        self._create_skill_directly(eval_result, full_conversation)

    async def _load_recent_compressed_conversations(self, limit: int = 5) -> str:
        """从 MySQL 直接加载最近 N 个任务的 compressed_conversation，只保留步骤和决策信息"""
        try:
            from workflow.report_tools import _get_agent_username, get_db_connection

            agent_username = _get_agent_username()
            connection = get_db_connection()
            if not connection:
                logger.warning("[后评估-技能创建] 数据库连接失败")
                return ""

            try:
                cursor = connection.cursor()
                sql = """
                    SELECT thread_id, compressed_conversation, full_conversation, summary, created_at
                    FROM conversation_summaries
                    WHERE username = %s
                      AND (compressed_conversation IS NOT NULL AND compressed_conversation != '')
                    ORDER BY created_at DESC
                    LIMIT %s
                """
                cursor.execute(sql, (agent_username, limit))
                rows = cursor.fetchall()

                if not rows:
                    logger.info("[后评估-技能创建] 未找到压缩对话记录")
                    return ""

                rows.reverse()

                parts = []
                parts.append(
                    f"** 最近{len(rows)}个任务的压缩对话（保留关键步骤和决策） **"
                )
                for idx, row in enumerate(rows, 1):
                    thread_id_val = row[0]
                    compressed_conv = row[1] or ""
                    summary = row[3] or ""
                    created_at = row[4]
                    time_str = (
                        created_at.strftime("%Y-%m-%d %H:%M:%S")
                        if hasattr(created_at, "strftime")
                        else str(created_at)
                    )
                    parts.append(f"[任务 {idx}] [{time_str}] [thread: {thread_id_val}]")
                    if summary:
                        parts.append(f"[摘要] {summary}")
                    parts.append(f"[压缩对话] {compressed_conv}")

                result_str = "\n".join(parts)
                logger.info(
                    f"[后评估-技能创建] 加载最近{len(rows)}个任务压缩对话，长度: {len(result_str)}"
                )
                return result_str
            finally:
                if connection.is_connected():
                    cursor.close()
                    connection.close()
        except Exception as e:
            logger.warning(f"[后评估-技能创建] 加载最近任务压缩对话失败: {e}")
            return ""

    async def _find_similar_compressed_conversations(
        self, user_input: str, username: str
    ) -> str:
        """
        查找历史相似任务的压缩对话。
        exclude_latest=5 跳过最近5个任务，避免与 recent_tasks 中的完整对话重复。
        返回压缩版对话（compressed_conversation），保留关键决策和步骤。
        """
        try:
            from workflow.report_tools import search_relevant_summaries_by_topic

            relevant = await search_relevant_summaries_by_topic(
                topic=user_input[:200],
                limit=3,
                exclude_latest=5,
            )
            if relevant:
                logger.info(
                    f"[后评估-技能创建] 找到历史相似任务压缩对话，长度: {len(relevant)}"
                )
                return relevant
            return ""
        except Exception as e:
            logger.warning(f"[后评估-技能创建] 搜索历史相似任务失败: {e}")
            return ""

    def _check_skills_usage_in_all(
        self,
        current_conv: str,
        recent_tasks: str,
        similar_tasks: str,
    ) -> bool:
        """全量检查所有收集的对话中是否使用了技能（包括当前、最近5、历史相似）"""
        all_text = "\n".join(filter(None, [current_conv, recent_tasks, similar_tasks]))
        skill_patterns = [
            r"skills/([\w-]+)/SKILL\.md",
            r"MCPFilesystem_read_file.*?skills/([\w-]+)",
            r"read_file.*?skills/([\w-]+)",
        ]
        for pattern in skill_patterns:
            matches = re.findall(pattern, all_text, re.IGNORECASE)
            if matches:
                logger.info(f"[后评估-技能创建] 检测到技能使用: {list(set(matches))}")
                return True
        return False

    def _check_skills_usage_in_conversation(self, full_conversation: str) -> List[str]:
        """检查单个对话中是否使用了技能，返回技能名列表（供技能改进评估使用）"""
        skill_patterns = [
            r"skills/([\w-]+)/SKILL\.md",
            r"MCPFilesystem_read_file.*?skills/([\w-]+)",
            r"read_file.*?skills/([\w-]+)",
        ]
        used_skills = []
        for pattern in skill_patterns:
            matches = re.findall(pattern, full_conversation, re.IGNORECASE)
            used_skills.extend(matches)
        return used_skills

    async def _llm_evaluate_skill_creation(
        self,
        user_input: str,
        full_final_content: str,
        similar_tasks: str,
        recent_tasks: str,
    ) -> Optional[Dict[str, Any]]:
        """LLM 综合评估：结合历史相似任务压缩对话 + 最近5个任务完整对话，判断是否创建技能"""
        prompt_template = self._load_prompt("POST_TASK_EVAL_SKILL_CREATE.md")
        if not prompt_template:
            return None

        # 截断控制 Token：每个来源限制长度
        prompt = prompt_template.replace("{user_input}", user_input[:500])
        prompt = prompt.replace("{ai_reply}", full_final_content[:1000])
        prompt = prompt.replace("{similar_tasks}", similar_tasks[:3000])
        prompt = prompt.replace("{recent_tasks}", recent_tasks[:5000])

        try:
            llm = self._get_llm()
            response = await asyncio.wait_for(
                llm.ainvoke([HumanMessage(content=prompt)]),
                timeout=POST_TASK_EVALUATION_LLM_TIMEOUT,
            )
            result_text = response.content.strip()

            json_match = re.search(r"\{.*?\}", result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result  # 始终返回完整解析结果（含 should_create 和 reason）
            logger.warning(
                f"[后评估-技能创建] LLM 返回内容无法解析为JSON: {result_text[:200]}"
            )
            return None
        except asyncio.TimeoutError:
            logger.warning("[后评估-技能创建] LLM 调用超时")
            return None
        except Exception as e:
            logger.warning(f"[后评估-技能创建] LLM 评估失败: {e}")
            return None

    def _create_skill_directly(
        self, eval_result: Dict[str, Any], full_conversation: str
    ) -> None:
        """直接调用底层 Python 函数创建技能"""
        try:
            skill_name = eval_result.get("skill_name", "")
            description = eval_result.get("description", "")

            if not skill_name:
                logger.warning("[后评估-技能创建] 技能名为空，跳过")
                return

            logger.info(
                f"[后评估-技能创建] ★ 开始创建技能 | skill_name={skill_name} | description={description[:100]}"
            )

            # 检查技能是否已存在
            skills_dir = Path(SKILLS_DIR)
            skill_path = skills_dir / skill_name
            if skill_path.exists():
                logger.info(f"[后评估-技能创建] 技能 '{skill_name}' 已存在，跳过")
                return

            # 构造对话数据
            conversations = [
                {"role": "conversation", "content": full_conversation[:5000]}
            ]
            task_conversations_json = json.dumps(conversations, ensure_ascii=False)

            # 调用 write_skill 的核心逻辑
            from mcp_filesystem.tools.advanced import (
                _validate_name,
                _find_skill,
                _generate_skill_content_with_llm,
                _validate_frontmatter,
                _atomic_write_text,
                _security_scan_skill,
                _get_skills_dir,
                MAX_SKILL_CONTENT_LENGTH,
            )

            name_error = _validate_name(skill_name)
            if name_error:
                logger.warning(f"[后评估-技能创建] 技能名称验证失败: {name_error}")
                return

            existing = _find_skill(skill_name)
            if existing:
                logger.info(f"[后评估-技能创建] 技能 '{skill_name}' 已存在，跳过")
                return

            skill_content = asyncio.get_event_loop().run_until_complete(
                _generate_skill_content_with_llm(skill_name, description, conversations)
            )

            if len(skill_content) > MAX_SKILL_CONTENT_LENGTH:
                logger.warning("[后评估-技能创建] 技能内容过大，跳过")
                return

            frontmatter_error = _validate_frontmatter(skill_content)
            if frontmatter_error:
                logger.warning(
                    f"[后评估-技能创建] frontmatter 验证失败: {frontmatter_error}"
                )
                return

            skills_dir_path = _get_skills_dir()
            skill_dir = skills_dir_path / skill_name
            skill_dir.mkdir(parents=True, exist_ok=False)

            skill_md_path = skill_dir / "SKILL.md"
            _atomic_write_text(skill_md_path, skill_content)

            scan_error = _security_scan_skill(skill_dir)
            if scan_error:
                import shutil

                shutil.rmtree(skill_dir, ignore_errors=True)
                logger.warning(f"[后评估-技能创建] 安全扫描失败: {scan_error}")
                return

            logger.info(
                f"[后评估-技能创建] ★ 成功创建技能 | skill_name={skill_name} | 路径={skill_dir}"
            )
        except Exception as e:
            logger.error(
                f"[后评估-技能创建] ★ 创建技能失败 | skill_name={eval_result.get('skill_name', '')} | 错误: {e}"
            )

    # ============================================================
    # 技能改进评估
    # ============================================================

    async def evaluate_skill_improvement(
        self,
        user_input: str,
        full_final_content: str,
        full_conversation: str,
        username: str,
        thread_id: str,
        session_id: str,
    ) -> None:
        """评估是否需要改进现有技能"""
        if not POST_TASK_EVALUATION_SKILL_IMPROVE:
            return

        # 1. 加载最近5个任务的压缩对话（用于发现跨轮次修正模式）
        recent_tasks_text = await self._load_recent_compressed_conversations(limit=5)
        if not recent_tasks_text:
            logger.info(
                "[后评估-技能改进] 无法加载最近任务压缩对话，回退到仅检查当前对话"
            )
            recent_tasks_text = ""

        # 2. 全量扫描技能使用：当前对话 + 最近5个压缩对话
        used_skills = self._scan_all_skills_usage(
            current_conv=full_conversation,
            recent_tasks=recent_tasks_text,
        )
        if not used_skills:
            logger.info("[后评估-技能改进] 当前任务及最近任务均未使用技能，跳过")
            return

        logger.info(f"[后评估-技能改进] 检测到技能使用: {used_skills}，开始逐个评估")

        # 3. 对每个检测到的技能，传入最近5个任务上下文进行评估
        for skill_name in used_skills:
            await self._evaluate_single_skill_improvement(
                skill_name=skill_name,
                user_input=user_input,
                full_final_content=full_final_content,
                full_conversation=full_conversation,
                recent_tasks=recent_tasks_text,
            )

    async def _evaluate_single_skill_improvement(
        self,
        skill_name: str,
        user_input: str,
        full_final_content: str,
        full_conversation: str,
        recent_tasks: str,
    ) -> None:
        """评估单个技能是否需要改进"""
        skill_md_content = self._read_skill_md(skill_name)
        if not skill_md_content:
            logger.info(f"[后评估-技能改进] 无法读取 '{skill_name}' 的 SKILL.md")
            return

        deviation = await self._llm_detect_deviation(
            skill_name=skill_name,
            skill_md_content=skill_md_content,
            full_conversation=full_conversation,
            recent_tasks=recent_tasks,
        )
        if not deviation or not deviation.get("should_improve"):
            reason = deviation.get("reason", "") if deviation else "LLM 返回为空"
            logger.info(f"[后评估-技能改进] '{skill_name}' 无需改进，原因: {reason}")
            return

        self._improve_skill_directly(skill_name, deviation, full_conversation)

    def _scan_all_skills_usage(self, current_conv: str, recent_tasks: str) -> List[str]:
        """全量扫描当前对话和最近5个压缩对话中的所有技能使用"""
        all_text = "\n".join(filter(None, [current_conv, recent_tasks]))
        skill_patterns = [
            r"skills/([\w-]+)/SKILL\.md",
            r"MCPFilesystem_read_file.*?skills/([\w-]+)",
            r"read_file.*?skills/([\w-]+)",
        ]
        used_skills = set()
        for pattern in skill_patterns:
            matches = re.findall(pattern, all_text, re.IGNORECASE)
            used_skills.update(matches)
        return list(used_skills)

    def _read_skill_md(self, skill_name: str) -> str:
        """读取技能的 SKILL.md 内容"""
        try:
            skill_md_path = Path(SKILLS_DIR) / skill_name / "SKILL.md"
            if not skill_md_path.exists():
                return ""
            return skill_md_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"[后评估-技能改进] 读取 SKILL.md 失败: {e}")
            return ""

    async def _llm_detect_deviation(
        self,
        skill_name: str,
        skill_md_content: str,
        full_conversation: str,
        recent_tasks: str,
    ) -> Optional[Dict[str, Any]]:
        """LLM 检测执行偏差，结合最近5个任务压缩对话发现跨轮次修正模式"""
        prompt_template = self._load_prompt("POST_TASK_EVAL_SKILL_IMPROVE.md")
        if not prompt_template:
            return None

        # 截断控制 Token：每个来源限制长度
        skill_summary = skill_md_content[:3000]
        prompt = prompt_template.replace("{skill_name}", skill_name)
        prompt = prompt.replace("{skill_guidance}", skill_summary)
        prompt = prompt.replace("{execution_summary}", full_conversation[:3000])
        prompt = prompt.replace("{recent_tasks}", recent_tasks[:5000])

        try:
            llm = self._get_llm()
            response = await asyncio.wait_for(
                llm.ainvoke([HumanMessage(content=prompt)]),
                timeout=POST_TASK_EVALUATION_LLM_TIMEOUT,
            )
            result_text = response.content.strip()

            json_match = re.search(r"\{.*?\}", result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result  # 始终返回完整解析结果（含 should_improve 和 reason）
            logger.warning(
                f"[后评估-技能改进] LLM 返回内容无法解析为JSON: {result_text[:200]}"
            )
            return None
        except asyncio.TimeoutError:
            logger.warning("[后评估-技能改进] LLM 调用超时")
            return None
        except Exception as e:
            logger.warning(f"[后评估-技能改进] LLM 检测偏差失败: {e}")
            return None

    def _improve_skill_directly(
        self,
        skill_name: str,
        deviation: Dict[str, Any],
        full_conversation: str,
    ) -> None:
        """直接调用底层 Python 函数改进技能"""
        try:
            from mcp_filesystem.tools.advanced import (
                _find_skill,
                _atomic_write_text,
                _security_scan_skill,
            )

            improvement_reason = deviation.get("improvement_reason", "")
            update_type = deviation.get("update_type", "patch")
            logger.info(
                f"[后评估-技能改进] ★ 开始改进技能 | skill_name={skill_name} | update_type={update_type} | reason={improvement_reason[:100]}"
            )

            existing = _find_skill(skill_name)
            if not existing:
                logger.warning(f"[后评估-技能改进] 技能 '{skill_name}' 不存在")
                return

            skill_dir = existing["path"]
            skill_md_path = existing["skill_md_path"]
            original_content = skill_md_path.read_text(encoding="utf-8")

            improvement_reason = deviation.get("improvement_reason", "")
            update_type = deviation.get("update_type", "patch")

            if update_type == "patch":
                old_string = deviation.get("old_string", "")
                new_string = deviation.get("new_string", "")
                if not old_string or not new_string:
                    logger.warning(
                        "[后评估-技能改进] patch 模式缺少 old_string/new_string"
                    )
                    return

                from mcp_filesystem.tools.advanced import _fuzzy_find_and_replace

                new_content, match_count, strategy, match_error = (
                    _fuzzy_find_and_replace(original_content, old_string, new_string)
                )
                if match_error:
                    logger.warning(f"[后评估-技能改进] 模糊替换失败: {match_error}")
                    return

                changes = [f"Patch applied ({match_count} replacement(s))"]

            elif update_type == "full":
                full_content = deviation.get("full_content", "")
                if not full_content:
                    logger.warning("[后评估-技能改进] full 模式缺少 full_content")
                    return
                new_content = full_content
                changes = ["Full skill content rewritten"]
            else:
                logger.warning(f"[后评估-技能改进] 无效的 update_type: {update_type}")
                return

            # 版本号更新
            import re as _re

            version_match = _re.search(r"version:\s*([\d.]+)", original_content)
            old_version = version_match.group(1) if version_match else "1.0.0"
            version_parts = old_version.split(".")
            if len(version_parts) >= 3:
                version_parts[2] = str(int(version_parts[2]) + 1)
            else:
                version_parts = ["1", "0", "1"]
            new_version = ".".join(version_parts)

            new_content = _re.sub(
                r"version:\s*[\d.]+",
                f"version: {new_version}",
                new_content,
            )
            changes.append(f"Version: {old_version} → {new_version}")

            # 改进记录
            from datetime import datetime

            now = datetime.now().isoformat()
            improvement_note = (
                f"\n\n---\n## Improvement Note ({now}):\n{improvement_reason}\n"
            )
            if "## Improvement Note" not in new_content:
                new_content = new_content.rstrip() + improvement_note

            # 备份 + 写入
            import shutil

            backup_path = skill_md_path.with_suffix(
                f".md.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
            shutil.copy2(skill_md_path, backup_path)
            _atomic_write_text(skill_md_path, new_content)

            scan_error = _security_scan_skill(skill_dir)
            if scan_error:
                shutil.copy2(backup_path, skill_md_path)
                backup_path.unlink(missing_ok=True)
                logger.warning(f"[后评估-技能改进] 安全扫描失败: {scan_error}")
                return

            backup_path.unlink(missing_ok=True)
            logger.info(
                f"[后评估-技能改进] ★ 成功改进技能 | skill_name={skill_name} | 版本: {old_version} → {new_version} | 变更: {changes}"
            )
        except Exception as e:
            logger.error(
                f"[后评估-技能改进] ★ 改进技能失败 | skill_name={skill_name} | 错误: {e}"
            )


# ============================================================
# 全局入口函数
# ============================================================

_evaluator_instance: Optional[PostTaskEvaluator] = None


def _get_evaluator() -> PostTaskEvaluator:
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = PostTaskEvaluator()
    return _evaluator_instance


async def run_post_task_evaluation(
    user_input: str,
    full_final_content: str,
    username: str = "",
    contact_name: str = "",
    thread_id: str = "",
    session_id: str = "",
    full_conversation: str = "",
) -> None:
    """任务完成后的全局入口，由 workflow_core.py 通过 asyncio.create_task 调用"""
    if not POST_TASK_EVALUATION_ENABLED:
        logger.info("[后评估] 全局开关关闭，跳过")
        return

    logger.info(
        f"[后评估] ★ 开始执行后评估 | username={username} | contact_name={contact_name} | "
        f"thread_id={thread_id} | session_id={session_id} | "
        f"偏好={POST_TASK_EVALUATION_PREFERENCE} | 技能创建={POST_TASK_EVALUATION_SKILL_CREATE} | 技能改进={POST_TASK_EVALUATION_SKILL_IMPROVE}"
    )
    evaluator = _get_evaluator()

    try:
        # 1. 偏好提取评估
        await evaluator.evaluate_preferences(
            user_input=user_input,
            full_final_content=full_final_content,
            contact_name=contact_name,
            session_id=session_id,
            full_conversation=full_conversation or "",
        )
    except Exception as e:
        logger.warning(f"[后评估-偏好] 执行异常: {e}")

    try:
        # 2. 技能创建评估
        await evaluator.evaluate_skill_creation(
            user_input=user_input,
            full_final_content=full_final_content,
            full_conversation=full_conversation or "",
            username=username,
            thread_id=thread_id,
            session_id=session_id,
        )
    except Exception as e:
        logger.warning(f"[后评估-技能创建] 执行异常: {e}")

    try:
        # 3. 技能改进评估
        await evaluator.evaluate_skill_improvement(
            user_input=user_input,
            full_final_content=full_final_content,
            full_conversation=full_conversation or "",
            username=username,
            thread_id=thread_id,
            session_id=session_id,
        )
    except Exception as e:
        logger.warning(f"[后评估-技能改进] 执行异常: {e}")

    logger.info("[后评估] ★ 全部后评估完成")

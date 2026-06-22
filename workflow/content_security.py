import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from workflow.config import BASE_DIR


class ContentSecurityBlockedError(Exception):
    """内容安全检查拦截异常：用于硬中断 DeepAgent 执行流，阻止 LLM 生成误导性回复"""

    def __init__(self, block_message: str, violations: list[str]):
        super().__init__(block_message)
        self.block_message = block_message
        self.violations = violations


@dataclass
class CheckResult:
    """安全检查结果"""

    passed: bool
    violations: list[str] = field(default_factory=list)
    safe_content: str = ""
    raw_content: str = ""
    intercept_type: str = ""  # 拦截类型: keyword / llm_review，用于日志记录


class ContentSecurityEngine:
    """内容安全检查引擎：配置驱动、LLM 二次审查、热加载"""

    _CONFIG_PATH = os.path.join(BASE_DIR, "config", "content_security_rules.json")
    _DEFAULT_SAFE_MESSAGE = "该回复经安全审查未通过，暂无法发送，请联系相关人员确认。"

    def __init__(self):
        self._rules_cache: Optional[dict] = None
        self._cache_timestamp: float = 0
        self._rules_text_cache: str = ""

    def load_rules(self) -> dict:
        """从 JSON 配置加载规则，支持热加载（检查文件修改时间）"""
        config_mtime = 0
        if os.path.exists(self._CONFIG_PATH):
            config_mtime = os.path.getmtime(self._CONFIG_PATH)

        # 检查 rule_sources 指向的文件修改时间
        if self._rules_cache and self._rules_cache.get("rule_sources"):
            for _, fpath in self._rules_cache["rule_sources"].items():
                full_path = os.path.join(BASE_DIR, fpath)
                if os.path.exists(full_path):
                    config_mtime = max(config_mtime, os.path.getmtime(full_path))

        if self._rules_cache and config_mtime <= self._cache_timestamp:
            return self._rules_cache

        if not os.path.exists(self._CONFIG_PATH):
            logger.info("[安全引擎] 配置文件不存在，安全检查已禁用")
            return {"enabled": False}

        with open(self._CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        self._rules_cache = config
        self._cache_timestamp = config_mtime
        self._rules_text_cache = ""  # 清空规则文本缓存，下次使用时重新生成
        logger.info("[安全引擎] 规则配置已加载（热加载）")
        return config

    def _load_rules_text(self) -> str:
        """合并所有规则文本（三层规则组合），供 LLM 审查使用"""
        if self._rules_text_cache:
            return self._rules_text_cache

        config = self.load_rules()
        rules_parts = []

        # 1. 加载 rule_sources 指定的文件内容
        rule_sources = config.get("rule_sources", {})
        for rule_name, file_path in rule_sources.items():
            full_path = os.path.join(BASE_DIR, file_path)
            if os.path.exists(full_path):
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    rules_parts.append(f"### {rule_name}\n{content}")

        # 2. 将 keywords_blacklist 注入为硬性禁止项
        keywords = config.get("keywords_blacklist", [])
        if keywords:
            rules_parts.append(
                f"### 禁止关键词\n"
                f"以下关键词严禁出现在面向客户的消息中（无论语境）：{', '.join(keywords)}"
            )

        # 3. 追加 custom_rules 作为补充规则
        custom = config.get("custom_rules", [])
        if custom:
            custom_text = "\n".join(f"- {rule}" for rule in custom)
            rules_parts.append(f"### 补充保密规则\n{custom_text}")

        self._rules_text_cache = "\n\n".join(rules_parts)
        return self._rules_text_cache

    def _keyword_scan(self, content: str) -> list[str]:
        """关键词黑名单扫描（第一步检查），确定性检查，零 LLM 开销"""
        config = self.load_rules()
        keywords = config.get("keywords_blacklist", [])
        violations = []
        for kw in keywords:
            if kw in content:
                violations.append(f"包含禁止关键词「{kw}」")
        return violations

    async def _llm_review(self, content: str) -> CheckResult:
        """LLM 二次审查（第二步检查），用独立 LLM 调用"""
        config = self.load_rules()
        if not config.get("llm_review_enabled", True):
            return CheckResult(passed=True)

        rules_text = self._load_rules_text()
        if not rules_text:
            return CheckResult(passed=True)

        prompt_template = config.get("llm_review_prompt_template", "")
        if not prompt_template:
            return CheckResult(passed=True)

        prompt = prompt_template.replace("{rules}", rules_text).replace(
            "{content}", content
        )

        try:
            from workflow.model import mcp_llm
            from langchain_core.messages import HumanMessage

            response = await mcp_llm.ainvoke([HumanMessage(content=prompt)])
            raw = response.content.strip()

            # 解析 LLM 返回的 JSON
            json_match = re.search(r'\{[^{}]*"passed"[^{}]*\}', raw, re.DOTALL)
            if not json_match:
                # 尝试从围栏中提取
                json_match = re.search(
                    r'```(?:json)?\s*(\{[^{}]*"passed"[^{}]*\})\s*```', raw, re.DOTALL
                )
                if json_match:
                    json_str = json_match.group(1)
                else:
                    logger.info(
                        "[安全引擎] LLM 审查返回格式异常，默认放行: {}", raw[:200]
                    )
                    return CheckResult(passed=True)
            else:
                json_str = json_match.group(0)

            result = json.loads(json_str)
            passed = result.get("passed", True)
            violations = result.get("violations", [])

            if not passed and violations:
                logger.info("[安全引擎] LLM 审查发现违规: {}", violations)
                return CheckResult(passed=False, violations=violations)

            return CheckResult(
                passed=bool(passed), violations=violations if not passed else []
            )

        except Exception as e:
            logger.error("[安全引擎] LLM 审查异常: {}", e)
            return CheckResult(passed=True)  # 审查异常时默认放行，避免阻断正常流程

    async def check_text(self, content: str, channel: str) -> CheckResult:
        """对文本内容做安全检查（关键词扫描 + LLM 审查）"""
        config = self.load_rules()

        if not config.get("enabled", False):
            return CheckResult(passed=True, raw_content=content)

        # 渠道不在 channels 列表中 → 直接放行
        channels = config.get("channels", [])
        if channel not in channels:
            return CheckResult(passed=True, raw_content=content)

        safe_message = config.get("client_safe_message", self._DEFAULT_SAFE_MESSAGE)

        if not content or not content.strip():
            return CheckResult(passed=True, raw_content=content)

        # 第一步：关键词黑名单扫描
        keyword_violations = self._keyword_scan(content)
        if keyword_violations:
            logger.info(
                "[安全拦截] 渠道={}, 关键词违规: {}", channel, keyword_violations
            )
            return CheckResult(
                passed=False,
                violations=keyword_violations,
                safe_content=safe_message,
                raw_content=content,
                intercept_type="keyword",
            )

        # 第二步：LLM 二次审查
        llm_result = await self._llm_review(content)
        if not llm_result.passed:
            logger.info(
                "[安全拦截] 渠道={}, LLM审查违规: {}", channel, llm_result.violations
            )
            return CheckResult(
                passed=False,
                violations=llm_result.violations,
                safe_content=safe_message,
                raw_content=content,
                intercept_type="llm_review",
            )

        logger.info("[安全检查] 渠道={}, 结果=通过, 内容长度={}", channel, len(content))
        return CheckResult(passed=True, raw_content=content)

    async def check_file(self, file_path: str, channel: str) -> CheckResult:
        """对文件名和文件内容做安全检查"""
        logger.debug(
            "[安全引擎] check_file 开始: file={}, channel={}", file_path, channel
        )
        config = self.load_rules()

        if not config.get("enabled", False):
            logger.debug("[安全引擎] 安全检查已禁用，放行文件: {}", file_path)
            return CheckResult(passed=True)

        channels = config.get("channels", [])
        if channel not in channels:
            logger.debug(
                "[安全引擎] 渠道 {} 不在检查列表 {}，放行文件", channel, channels
            )
            return CheckResult(passed=True)

        if not os.path.exists(file_path):
            logger.info("[安全引擎] 文件不存在，跳过检查: {}", file_path)
            return CheckResult(passed=True)

        # 第一步：对文件名做关键词扫描（文件名本身可能泄露敏感信息）
        file_name = os.path.basename(file_path)
        logger.debug("[安全引擎] 扫描文件名关键词: file_name={}", file_name)
        name_violations = self._keyword_scan(file_name)
        if name_violations:
            safe_message = config.get("client_safe_message", self._DEFAULT_SAFE_MESSAGE)
            logger.info(
                "[安全拦截] 渠道={}, 文件名关键词违规: file={}, violations={}",
                channel,
                file_name,
                name_violations,
            )
            return CheckResult(
                passed=False,
                violations=name_violations,
                safe_content=safe_message,
                raw_content=file_name,
                intercept_type="keyword",
            )
        logger.debug("[安全引擎] 文件名关键词扫描通过: {}", file_name)

        # 第二步：提取文件内容并检查
        file_text = self._extract_file_text(file_path)
        if not file_text:
            logger.info(
                "[安全引擎] 文件内容为空或无法提取，跳过内容检查: {}", file_path
            )
            return CheckResult(passed=True)

        logger.debug(
            "[安全引擎] 文件内容提取成功，长度={}，进入文本检查", len(file_text)
        )
        return await self.check_text(file_text, channel)

    def _extract_file_text(self, file_path: str) -> str:
        """提取文件文本内容，支持常见文本格式"""
        ext = os.path.splitext(file_path)[1].lower()

        # 纯文本类文件直接读取
        text_extensions = {
            ".txt",
            ".md",
            ".csv",
            ".json",
            ".xml",
            ".log",
            ".ini",
            ".yaml",
            ".yml",
        }
        if ext in text_extensions:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            except Exception as e:
                logger.info("[安全引擎] 读取文件失败: {}, {}", file_path, e)
                return ""

        # 其他格式文件暂不提取文本，返回空（后续可扩展 PDF/Word 等）
        logger.info("[安全引擎] 文件格式 {} 暂不支持文本提取: {}", ext, file_path)
        return ""

    def build_owner_notify_message(
        self, result: "CheckResult", context: str = ""
    ) -> str:
        """根据拦截结果构建工作伙伴通知消息"""
        config = self.load_rules()
        if not config.get("notify_owner", False):
            return ""

        template = config.get(
            "owner_notify_message",
            "【安全拦截通知】以下内容因违反保密要求已被拦截，请检查：{violations}",
        )
        violation_text = "；".join(result.violations)
        msg = template.replace("{violations}", violation_text)
        if context:
            msg += f"\n来源：{context}"
        return msg

    async def check(self, content: str, files: list[str], channel: str) -> CheckResult:
        """综合检查：文本 + 文件，任一项不通过即整体不通过"""
        logger.debug(
            "[安全引擎] check 综合检查开始: channel={}, content_len={}, files={}",
            channel,
            len(content),
            files,
        )
        config = self.load_rules()

        if not config.get("enabled", False):
            logger.debug("[安全引擎] 安全检查已禁用，全部放行")
            return CheckResult(passed=True, raw_content=content)

        # 先检查文本
        text_result = await self.check_text(content, channel)
        if not text_result.passed:
            logger.info("[安全引擎] 文本检查不通过，综合结果=拦截")
            return text_result

        logger.debug("[安全引擎] 文本检查通过，开始检查 {} 个文件", len(files))

        # 再逐个检查文件
        all_violations = []
        file_intercept_type = ""
        for fpath in files:
            file_result = await self.check_file(fpath, channel)
            if not file_result.passed:
                all_violations.extend(file_result.violations)
                # 保留第一个文件的拦截类型
                if not file_intercept_type:
                    file_intercept_type = file_result.intercept_type

        if all_violations:
            logger.info(
                "[安全引擎] 文件检查不通过，综合结果=拦截, violations={}",
                all_violations,
            )
            safe_message = config.get("client_safe_message", self._DEFAULT_SAFE_MESSAGE)
            return CheckResult(
                passed=False,
                violations=all_violations,
                safe_content=safe_message,
                raw_content=content,
                intercept_type=file_intercept_type or "keyword",
            )

        logger.info("[安全引擎] 综合检查通过: channel={}", channel)
        return CheckResult(passed=True, raw_content=content)

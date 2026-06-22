import os
import sys
import base64
import re
import json
from datetime import datetime
import posixpath
from typing import Any

from deepagents.backends import LocalShellBackend
from deepagents.backends.protocol import FileInfo

# Runloop 沙盒导入

from workflow.config import (
    VENV_PYTHON,
    VENV_PIP,
    IS_WINDOWS,
    USE_SANDBOX,
    OUTPUT_BASE_DIR,
    OWNER_NAME,
)

from loguru import logger

# 全局变量
_runloop_sandbox = None
_runloop_backend = None


class WindowsCompatibleLocalShellBackend(LocalShellBackend):
    def ls_info(self, path: str) -> list[FileInfo]:
        results = super().ls_info(path)
        for item in results:
            if "path" in item:
                item["path"] = item["path"].replace("\\", "/")
        return results


class DownloadResult:
    """deepagents 库期望的下载结果对象格式"""

    def __init__(self, error: str = None, results: dict = None, content: bytes = None):
        self.error = error
        self.results = results or {}
        self.content = content

    def __getitem__(self, key):
        if isinstance(key, int):
            key = list(self.results.keys())[key]
        return self.results[key]

    def get(self, key, default=None):
        return self.results.get(key, default)

    def __repr__(self):
        return f"DownloadResult(error={self.error}, results={self.results}, content={self.content})"

    def __iter__(self):
        return iter(self.results.values())


class UploadResult:
    """deepagents 库期望的上传结果对象格式"""

    def __init__(self, error: str = None, results: dict = None):
        self.error = error
        self.results = results or {}

    def __getitem__(self, key):
        if isinstance(key, int):
            key = list(self.results.keys())[key]
        return self.results[key]

    def get(self, key, default=None):
        return self.results.get(key, default)

    def __repr__(self):
        return f"UploadResult(error={self.error}, results={self.results})"

    def __iter__(self):
        return iter(self.results.values())


class VirtualEnvLocalShellBackend(LocalShellBackend):
    """继承 LocalShellBackend，在虚拟环境中执行命令

    功能：
    1. 自动检测脚本中的 import 语句，识别需要安装的依赖
    2. 在虚拟环境中安装缺失的依赖
    3. 使用虚拟环境中的 Python 执行命令
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._installed_packages = set()  # 已安装的包，避免重复安装

    def _get_venv_python(self) -> str:
        """获取虚拟环境中的 Python 路径"""
        if os.path.exists(VENV_PYTHON):
            return VENV_PYTHON
        # 回退到系统 Python
        return "python" if IS_WINDOWS else "python3"

    def _get_venv_pip(self) -> str:
        """获取虚拟环境中的 pip 路径"""
        if os.path.exists(VENV_PIP):
            return VENV_PIP
        # 回退到系统 pip
        return "pip" if os.name == "nt" else "pip3"

    def _parse_imports_from_code(self, code: str) -> list[str]:
        """从代码中解析 import 语句，提取依赖包名"""
        # 只匹配真正的 import 语句，避免把 shell 命令误识别为模块名
        imports = re.findall(
            r"^\s*(?:import\s+([a-zA-Z_][a-zA-Z0-9_]*)|from\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+import)",
            code,
            re.MULTILINE,
        )
        imports = [m[0] or m[1] for m in imports if m[0] or m[1]]

        # 过滤掉标准库和已安装的第三方包
        stdlib = {
            "os",
            "sys",
            "re",
            "json",
            "datetime",
            "time",
            "math",
            "random",
            "collections",
            "itertools",
            "functools",
            "operator",
            "string",
            "logging",
            "argparse",
            "subprocess",
            "threading",
            "multiprocessing",
            "asyncio",
            "pathlib",
            "urllib",
            "http",
            "email",
            "html",
            "xml",
            "csv",
            "io",
            "base64",
            "hashlib",
            "secrets",
            "ssl",
            "socket",
            "struct",
            "platform",
            "configparser",
            "ast",
            "dis",
            "gc",
            "warnings",
            "abc",
            "copy",
            "pickle",
            "shelve",
            "sqlite3",
            "decimal",
            "fractions",
            "numbers",
            "cmath",
            "array",
            "queue",
            "heapq",
            "bisect",
            "graphlib",
            "enum",
            "types",
            "contextlib",
            "dataclasses",
            "typing",
            "pprint",
            "textwrap",
            "unittest",
        }

        third_party = self._installed_packages.copy()

        # 常见的第三方包名映射（模块名 -> 包名）
        package_map = {
            "PIL": "pillow",
            "cv2": "opencv-python",
            "np": "numpy",
            "pd": "pandas",
            "plt": "matplotlib",
            "sns": "seaborn",
            "sklearn": "scikit-learn",
            "requests": "requests",
            "bs4": "beautifulsoup4",
            "yaml": "pyyaml",
            "dotenv": "python-dotenv",
            "jwt": "pyjwt",
            "cryptography": "cryptography",
            "sqlalchemy": "sqlalchemy",
            "flask": "flask",
            "django": "django",
            "fastapi": "fastapi",
            "uvicorn": "uvicorn",
            "aiohttp": "aiohttp",
            "httpx": "httpx",
            "openai": "openai",
            "anthropic": "anthropic",
            "langchain": "langchain",
            "langgraph": "langgraph",
        }

        deps = []
        for imp in imports:
            if imp in stdlib or imp in third_party:
                continue
            # 使用映射表转换模块名到包名
            pkg_name = package_map.get(imp, imp.lower())
            if pkg_name not in deps:
                deps.append(pkg_name)

        return deps

    def _install_dependencies(self, code: str) -> bool:
        """自动安装代码中需要的依赖"""
        deps = self._parse_imports_from_code(code)
        if not deps:
            return True

        # 检查哪些包还未安装
        new_deps = [d for d in deps if d not in self._installed_packages]
        if not new_deps:
            return True

        logger.info(f"[VirtualEnv] 检测到需要安装的依赖: {new_deps}")

        # 先检查已安装的包
        try:
            venv_pip = self._get_venv_pip()
            check_result = super().execute(f'"{venv_pip}" list --format=freeze')
            if check_result.exit_code == 0:
                installed = {
                    line.split("==")[0].lower()
                    for line in check_result.output.split("\n")
                    if line.strip()
                }
                new_deps = [d for d in new_deps if d.lower() not in installed]
                if not new_deps:
                    logger.info(f"[VirtualEnv] 所有依赖已安装")
                    self._installed_packages.update(deps)
                    return True
        except Exception as e:
            logger.info(f"[VirtualEnv] 检查已安装包失败: {e}")

        # 安装缺失的包
        venv_pip = self._get_venv_pip()
        for dep in new_deps:
            try:
                logger.info(f"[VirtualEnv] 正在安装依赖: {dep}")
                install_cmd = f'"{venv_pip}" install {dep}'
                result = super().execute(install_cmd)

                if result.exit_code == 0:
                    logger.info(f"[VirtualEnv] 成功安装: {dep}")
                    self._installed_packages.add(dep)
                else:
                    logger.info(f"[VirtualEnv] 安装失败 {dep}: {result.output}")
            except Exception as e:
                logger.info(f"[VirtualEnv] 安装异常 {dep}: {e}")

        return True

    def execute(self, command: str, timeout: int = 120) -> Any:
        """在虚拟环境中执行命令"""
        # 检测是否是 Python 脚本执行
        is_python_script = (
            "python" in command.lower() or ".py" in command or "pip install" in command
        )

        # 检测是否需要安装依赖
        if is_python_script and "pip install" not in command.lower():
            # 尝试从命令中提取代码并分析依赖
            # 这里简化处理：先执行依赖安装
            try:
                self._install_dependencies(command)
            except Exception as e:
                logger.info(f"[VirtualEnv] 依赖安装检查失败: {e}")

        # 如果使用虚拟环境的 Python，则替换命令
        if is_python_script and "pip install" not in command.lower():
            venv_python = self._get_venv_python()

            # 替换 python/python3 为虚拟环境的 Python
            if IS_WINDOWS:
                command = command.replace("python ", f'"{venv_python}" ')
                command = command.replace("python3 ", f'"{venv_python}" ')
            else:
                command = command.replace("python ", f"{venv_python} ")
                command = command.replace("python3 ", f"{venv_python} ")

        # 执行命令
        return super().execute(command, timeout=timeout)

    async def als_info(self, path: str) -> list[FileInfo]:
        """异步版本的 ls_info（deepagents 库 bug：调用了 als_info 而非 ls_info）"""
        return self.ls_info(path)

    async def adownload_files(self, paths: list[str]) -> Any:
        """异步下载文件（deepagents 库调用）

        返回格式：DownloadResult 对象列表
        """
        results = []
        for path in paths:
            try:
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        content = f.read()
                    results.append(
                        DownloadResult(
                            error=None, results={path: True}, content=content
                        )
                    )
                else:
                    results.append(
                        DownloadResult(
                            error=f"File not found: {path}", results={}, content=None
                        )
                    )
            except Exception as e:
                results.append(DownloadResult(error=str(e), results={}, content=None))
        return results

    async def aupload_files(self, files: dict[str, bytes]) -> Any:
        """异步上传文件（deepagents 库调用）

        返回格式：UploadResult 对象
        """
        try:
            result = {}
            for path, content in files.items():
                try:
                    dir_path = os.path.dirname(path)
                    if dir_path:
                        os.makedirs(dir_path, exist_ok=True)
                    with open(path, "wb") as f:
                        f.write(content)
                    result[path] = True
                except Exception:
                    result[path] = False
            return UploadResult(error=None, results=result)
        except Exception as e:
            return UploadResult(error=str(e), results={})

    async def adelete_file(self, path: str) -> bool:
        """异步删除文件（deepagents 库调用）"""
        try:
            if os.path.exists(path):
                os.remove(path)
            return True
        except Exception:
            return False

    async def aexecute(self, command: str, timeout: int = 120) -> Any:
        """异步执行命令"""
        return self.execute(command, timeout=timeout)


def _upload_single_file(file_path: str, data) -> bool:
    """上传单个文件到沙盒"""
    global _runloop_sandbox, _runloop_backend

    # 提取文件内容
    if isinstance(data, dict):
        content = data.get("content", "")
        if isinstance(content, list):
            # 在合并之前处理每一行，去除行号
            content = [re.sub(r"^\s*\d+\t", "", line) for line in content]
            content = "".join(content)
    else:
        content = getattr(data, "content", "")
        if isinstance(content, list):
            content = [re.sub(r"^\s*\d+\t", "", line) for line in content]
            content = "".join(content)

    try:
        # 创建父目录
        dir_path = posixpath.dirname(file_path)
        if dir_path:
            mkdir_cmd = f"mkdir -p {dir_path}"
            _runloop_backend.execute(mkdir_cmd)

        # 写入文件
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        write_cmd = f"echo '{encoded}' | base64 -d > {file_path}"
        result = _runloop_backend.execute(write_cmd)

        if result.exit_code == 0:
            return True
        else:
            logger.info(f"[DeepAgent] 写入文件失败 {file_path}: {result.output}")
            return False
    except Exception as e:
        logger.info(f"[DeepAgent] 写入文件异常 {file_path}: {e}")
        return False


def _parse_generated_files(content: str) -> list:
    """从 Agent 输出内容中解析生成的文列表"""
    generated_files = []
    try:
        # 尝试多种方式解析 JSON
        json_str = None

        # 1. 尝试匹配 ```json ... ```
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)

        # 2. 尝试匹配 ``` ... ``` (不带语言标记)
        if not json_str:
            code_blocks = re.findall(r"```\s*(\{.*?\})\s*```", content, re.DOTALL)
            for block in code_blocks:
                try:
                    # 尝试解析，看是否包含 generated_files
                    data = json.loads(block)
                    if "generated_files" in data:
                        json_str = block
                        break
                except:
                    continue

        # 3. 尝试直接查找 JSON 对象 {...}
        if not json_str:
            # 查找所有可能是 JSON 对象的字符串
            potential_jsons = re.findall(r"(\{.*?\})", content, re.DOTALL)
            for block in potential_jsons:
                try:
                    data = json.loads(block)
                    if "generated_files" in data and isinstance(
                        data["generated_files"], list
                    ):
                        generated_files = data["generated_files"]
                        logger.info(
                            f"[DeepAgent] 从文本块中解析到文件列表: {generated_files}"
                        )
                        break
                except:
                    continue

        if json_str:
            try:
                data = json.loads(json_str)
                if "generated_files" in data and isinstance(
                    data["generated_files"], list
                ):
                    generated_files = data["generated_files"]
                    logger.info(
                        f"[DeepAgent] 从代码块中解析到文件列表: {generated_files}"
                    )
            except json.JSONDecodeError as e:
                logger.info(f"[DeepAgent] JSON 解析错误: {e}")

    except Exception as e:
        logger.info(f"[DeepAgent] 解析生成文件列表失败: {e}")

    return generated_files


def _extract_wechat_contact(wechat_context: str) -> str:
    """从 wechat_context 中提取微信联系人名称

    wechat_context 格式：'你现在正在通过微信与联系人【张三】对话。...'
    提取 【】 中的联系人名称
    """
    if not wechat_context:
        return ""
    match = re.search(r"【(.+?)】", wechat_context)
    return match.group(1) if match else ""


async def _send_files_to_wechat(contact_name: str, local_files: list):
    """通过微信 MCP 工具将本地文件发送给指定联系人

    Args:
        contact_name: 微信联系人名称
        local_files: 本地文件路径列表
    """
    if not contact_name or not local_files:
        return

    from workflow.report_tools import load_mcp_config
    from workflow.robust_mcp_client import RobustMultiServerMCPClient

    mcp_servers, _ = load_mcp_config()
    if not mcp_servers:
        logger.info(f"[微信发送] MCP 配置加载失败，跳过发送")
        return

    client = RobustMultiServerMCPClient(mcp_servers)
    try:
        tools = await client.get_tools()
        send_tool = next(
            (t for t in tools if t.name.endswith("send_wechat_file")), None
        )
        if not send_tool:
            logger.info(f"[微信发送] 未找到 send_wechat_file 工具，跳过发送")
            return

        for file_path in local_files:
            if not os.path.exists(file_path):
                logger.info(f"[微信发送] 文件不存在，跳过: {file_path}")
                continue
            try:
                result = await send_tool.ainvoke(
                    {"chat_name": contact_name, "file_path": file_path}
                )
                logger.info(
                    f"[微信发送] 发送文件 '{file_path}' 给 '{contact_name}': {result}"
                )
            except Exception as e:
                logger.info(f"[微信发送] 发送文件失败 '{file_path}': {e}")
    finally:
        await client.shutdown()


async def _download_sandbox_files(
    username: str, final_content: str, wechat_contact: str = ""
):
    """从沙盒下载生成的文件到本地（支持沙盒和本地两种模式）

    Args:
        username: 用户名
        final_content: Agent 最终输出内容（含文件列表 JSON）
        wechat_contact: 微信联系人名称，非空时任务完成后将文件发送给该联系人
    """
    logger.info(f"[DeepAgent] ========== 开始下载流程 ==========")
    logger.info(f"[DeepAgent] 是否使用沙盒: {USE_SANDBOX}")

    if not username:
        username = OWNER_NAME

    if USE_SANDBOX:
        # 沙盒模式：需要从沙盒下载文件
        global _runloop_sandbox, _runloop_backend

        logger.info(
            f"[DeepAgent] sandbox ID: {_runloop_sandbox.id if _runloop_sandbox else 'None'}"
        )
        logger.info(f"[DeepAgent] backend: {_runloop_backend}")
        logger.info(f"[DeepAgent] username: {username}")
        sys.stdout.flush()

        if _runloop_sandbox is None or _runloop_backend is None:
            logger.info(f"[DeepAgent] 沙盒未初始化，跳过文件下载")
            sys.stdout.flush()
            return

        # 计算沙盒中的输出目录
        date_str = datetime.now().strftime("%Y%m%d")
        # 保存到 ${BASE_DIR}/output/charts/{username}/{date_str}/
        local_output_dir = os.path.join(OUTPUT_BASE_DIR, username, date_str).replace(
            "\\", "/"
        )

    def _download_from_sandbox() -> list:
        """从沙盒下载文件到本地，返回成功下载的本地文件路径列表"""
        downloaded = []
        try:
            logger.info(f"[DeepAgent] 正在从沙盒下载文件...")
            generated_files = _parse_generated_files(final_content)
            files_to_download = []

            if generated_files:
                files_to_download = generated_files
            else:
                logger.info(
                    f"[DeepAgent] 未解析到明确的文件列表，回退到目录扫描模式 (仅扫描 /charts)"
                )
                try:
                    find_result = _runloop_backend.execute(
                        "sudo find /charts -type f 2>/dev/null"
                    )
                    if find_result.exit_code == 0:
                        files_to_download = [
                            l.strip()
                            for l in find_result.output.strip().split("\n")
                            if l.strip()
                        ]
                    logger.info(
                        f"[DeepAgent] 扫描 /charts 目录找到 {len(files_to_download)} 个文件"
                    )
                except Exception as e:
                    logger.info(f"[DeepAgent] 扫描目录异常: {e}")

            if not files_to_download:
                logger.info(f"[DeepAgent] 没有文件需要下载")
                return downloaded

            os.makedirs(local_output_dir, exist_ok=True)

            for file_path in files_to_download:
                file_path = file_path.strip()
                if not file_path:
                    continue
                local_file_path = os.path.join(
                    local_output_dir, os.path.basename(file_path)
                )
                logger.info(f"[DeepAgent] 下载文件: {file_path} -> {local_file_path}")
                result = _runloop_backend.execute(f'sudo base64 "{file_path}"')
                if result.exit_code == 0:
                    with open(local_file_path, "wb") as f:
                        f.write(base64.b64decode(result.output.strip()))
                    logger.info(f"[DeepAgent] 文件下载成功: {local_file_path}")
                    downloaded.append(local_file_path)
                    try:
                        _runloop_backend.execute(f'sudo rm -f "{file_path}"')
                        logger.info(f"[DeepAgent] 已删除沙盒文件: {file_path}")
                    except Exception as e:
                        logger.info(f"[DeepAgent] 删除沙盒文件失败: {e}")
                else:
                    logger.info(
                        f"[DeepAgent] 读取文件失败 {file_path}: {result.output}"
                    )
        except Exception as e:
            logger.info(f"[DeepAgent] 下载流程异常: {e}")
        return downloaded

    def _process_local_files() -> list:
        """本地模式：文件已直接写入本地目录，返回文件路径列表"""
        import difflib

        local_files = []
        if not username:
            return local_files
        date_str = datetime.now().strftime("%Y%m%d")
        output_dir = os.path.join(OUTPUT_BASE_DIR, username, date_str)

        generated_files = _parse_generated_files(final_content)
        if generated_files:
            logger.info(f"[DeepAgent] 发现生成的文件列表: {generated_files}")
            for file_path in generated_files:
                if not os.path.isabs(file_path):
                    file_path = os.path.join(output_dir, os.path.basename(file_path))

                if os.path.exists(file_path):
                    local_files.append(file_path)
                else:
                    logger.info(f"[DeepAgent] 精确匹配失败，尝试模糊匹配: {file_path}")
                    # 方案一：模糊匹配
                    if os.path.exists(output_dir):
                        target_name = os.path.basename(file_path)
                        available_files = os.listdir(output_dir)

                        # 寻找最相似的文件名 (相似度阈值 0.6)
                        matches = difflib.get_close_matches(
                            target_name, available_files, n=1, cutoff=0.6
                        )
                        if matches:
                            matched_file = os.path.join(output_dir, matches[0])
                            logger.info(
                                f"[DeepAgent] 模糊匹配成功: {target_name} -> {matches[0]}"
                            )
                            if matched_file not in local_files:
                                local_files.append(matched_file)
                        else:
                            logger.info(f"[DeepAgent] 模糊匹配失败，跳过: {file_path}")
                    else:
                        logger.info(
                            f"[DeepAgent] 输出目录不存在，无法模糊匹配: {output_dir}"
                        )

            # 方案二：改进回退逻辑
            # 如果解析到了文件列表，但最终一个文件都没找到，则回退到获取最新修改的文件
            if not local_files and os.path.exists(output_dir):
                logger.info(
                    f"[DeepAgent] 解析到文件列表但均未找到，回退到获取最新生成的文件"
                )
                all_files = []
                for filename in os.listdir(output_dir):
                    fp = os.path.join(output_dir, filename)
                    if os.path.isfile(fp):
                        all_files.append((fp, os.path.getmtime(fp)))

                if all_files:
                    # 按修改时间降序排序
                    all_files.sort(key=lambda x: x[1], reverse=True)
                    # 取最近 5 分钟内修改的文件
                    current_time = datetime.now().timestamp()
                    recent_files = [
                        f[0] for f in all_files if current_time - f[1] < 300
                    ]

                    if recent_files:
                        local_files.extend(recent_files)
                        logger.info(
                            f"[DeepAgent] 找到 {len(recent_files)} 个最近生成的文件"
                        )
                    else:
                        # 如果没有最近 5 分钟的，至少取最新的一个
                        local_files.append(all_files[0][0])
                        logger.info(
                            f"[DeepAgent] 未找到最近 5 分钟内的文件，取最新修改的文件: {all_files[0][0]}"
                        )

        elif os.path.exists(output_dir):
            logger.info(f"[DeepAgent] 未解析到文件列表，回退到扫描目录: {output_dir}")
            for filename in os.listdir(output_dir):
                fp = os.path.join(output_dir, filename)
                if os.path.isfile(fp):
                    local_files.append(fp)
        else:
            logger.info(f"[DeepAgent] 输出目录不存在: {output_dir}")

        return local_files

    if USE_SANDBOX:
        local_files = _download_from_sandbox()
        if wechat_contact and local_files:
            logger.info(
                f"[DeepAgent] 沙盒模式，准备发送 {len(local_files)} 个文件给联系人: {wechat_contact}"
            )
            await _send_files_to_wechat(wechat_contact, local_files)
    else:
        logger.info(
            f"[DeepAgent] 本地模式：文件已直接写入本地目录，wechat_agent 负责发送，跳过重复发送"
        )
        if not username:
            username = OWNER_NAME
        _process_local_files()


async def _upload_skill_file_on_demand(file_path: str, skills_files: dict):
    """按需上传 skill 文件到沙盒（仅沙盒模式需要）

    当 agent 需要读取某个文件时，如果文件不存在于沙盒中，则上传整个 skills 文件夹
    本地模式下不需要此操作，skills 文件已在本地文件系统
    """

    # 非沙盒模式：不需要上传，skills 已在本地
    if not USE_SANDBOX:
        logger.info(f"[DeepAgent] 本地模式：skills 文件已在本地，无需上传")
        return True

    global _runloop_sandbox, _runloop_backend

    # 清理路径中的引号
    file_path = file_path.replace('"', "").replace("'", "")

    logger.info(f"[DeepAgent] 按需上传检查: {file_path}")
    logger.info(f"[DeepAgent] 沙盒状态: backend={_runloop_backend is not None}")

    if _runloop_sandbox is None or _runloop_backend is None:
        logger.info(f"[DeepAgent] 沙盒未创建，跳过上传")
        return False

    # 从文件路径中提取 skills 文件夹名称
    # 例如: /home/user/skills/docx/SKILL.md -> docx
    parts = file_path.split("/")
    logger.info(f"[DeepAgent] 解析文件路径: parts={parts}")

    # 路径格式: /home/user/skills/docx/SKILL.md
    # parts[0] = '', parts[1] = 'home', parts[2] = 'user', parts[3] = 'skills', parts[4] = 'docx'
    if len(parts) >= 5 and parts[3] == "skills":
        skill_name = parts[4]
    else:
        # 无法识别 skills 文件夹，返回 False
        logger.info(f"[DeepAgent] 无法识别 skills 文件夹，parts={parts}")
        return False

    # 检查 skills 目录是否存在
    skills_dir = f"/home/user/skills/{skill_name}"
    check_dir_cmd = f"test -d {skills_dir} && echo 'exists' || echo 'not_exists'"
    check_dir_result = _runloop_backend.execute(check_dir_cmd)

    if check_dir_result.output.strip() == "exists":
        # 文件夹已存在，检查具体文件
        check_file_cmd = f"test -f {file_path} && echo 'exists' || echo 'not_exists'"
        check_file_result = _runloop_backend.execute(check_file_cmd)

        if check_file_result.output.strip() == "exists":
            # 文件已存在，无需上传
            return True

        # 文件不存在但文件夹存在，只上传需要的文件
        if file_path in skills_files:
            return _upload_single_file(file_path, skills_files[file_path])
        return False

    # 文件夹不存在，需要上传整个 skills 文件夹
    logger.info(f"[DeepAgent] 按需上传整个 skills 文件夹: {skill_name}")

    # 创建 skills 目录
    _runloop_backend.execute("mkdir -p /home/user/skills")

    # 找出该 skill 的所有相关文件
    skill_files = {}
    for path, data in skills_files.items():
        if f"/skills/{skill_name}/" in path:
            skill_files[path] = data

    # 上传该 skill 的所有文件
    uploaded_count = 0
    for path, data in skill_files.items():
        if _upload_single_file(path, data):
            uploaded_count += 1

    logger.info(
        f"[DeepAgent] Skills 文件夹上传完成: {skill_name} ({uploaded_count} 个文件)"
    )
    return uploaded_count > 0

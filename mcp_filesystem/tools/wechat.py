"""WeChat automation tools.

This module contains tools for automating WeChat operations, such as sending files.
"""

import asyncio
import hashlib
import os
import json
import re
import time
from dotenv import load_dotenv

from ..paths import app_base_dir

from loguru import logger

PROJECT_ROOT = app_base_dir()
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# 从环境变量读取配置，如果未配置则使用默认值
_audio_cache_env = os.environ.get(
    "WECHAT_AUDIO_CACHE_FILE", "tools/config/wechat_audio_cache.json"
)


def _active_username() -> str:
    """
    当前“桌面端登录用户名”。
    由桌面端登录成功后调用后端接口写入环境变量。
    若未设置则使用 default，避免落盘到操作系统用户名目录。
    """
    u = os.environ.get("WORKMATE_DESKTOP_ACTIVE_USERNAME", "").strip()
    return u or "default"


def _resolve_template_path(template: str) -> str:
    """
    解析路径模板：
    - 支持 {username}/{active_username} 占位符
    - 若解析后为绝对路径，直接返回
    - 否则视为相对 PROJECT_ROOT 的路径段拼接
    """
    t = str(template or "").strip()
    if not t:
        return ""

    active_username = _active_username()
    t = t.replace("{username}", active_username).replace(
        "{active_username}", active_username
    )
    t = os.path.expandvars(os.path.expanduser(t))

    # Windows drive absolute path: C:\xxx or C:/xxx
    if re.match(r"^[A-Za-z]:[\\/]", t):
        return os.path.normpath(t)
    if t.startswith("/") or t.startswith("\\\\"):
        return os.path.normpath(t)

    parts = t.replace("\\", "/").split("/")
    parts = [p for p in parts if p]
    return os.path.join(PROJECT_ROOT, *parts)


def _get_audio_cache_file() -> str:
    return _resolve_template_path(_audio_cache_env)


WECHAT_WINDOW_TITLE = os.environ.get("WECHAT_WINDOW_TITLE", "微信")
WECHAT_PROCESS_NAME = os.environ.get("WECHAT_PROCESS_NAME", "WeChat")

# 微信进程名备选列表（不同PC上进程名可能为 WeChat 或 Weixin）
_FALLBACK_PROCESS_NAMES = ["WeChat", "Weixin"]


def _update_env_process_name(new_name: str) -> None:
    """更新 .env 文件中的 WECHAT_PROCESS_NAME 配置"""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        with open(env_path, "w", encoding="utf-8") as f:
            for line in lines:
                if line.startswith("WECHAT_PROCESS_NAME="):
                    f.write(f"WECHAT_PROCESS_NAME={new_name}\n")
                else:
                    f.write(line)
        os.environ["WECHAT_PROCESS_NAME"] = new_name
        logger.info("已更新 .env 中的微信进程名: {}", new_name)
    except Exception as e:
        logger.error("更新 .env 中微信进程名失败: {}", e)


def _find_wechat_window(window_ctrl) -> int | None:
    """查找微信主窗口，支持进程名 Weixin/WeChat 自动切换。

    先尝试 WECHAT_PROCESS_NAME 配置的进程名查找窗口；
    如果没有找到，依次尝试备选进程名。如果备选名称成功匹配，
    会自动更新 .env 文件和内存变量，后续调用直接使用正确名称。
    """
    global WECHAT_PROCESS_NAME

    # 先尝试当前配置的进程名
    hwnd = window_ctrl.find(title=WECHAT_WINDOW_TITLE, process_name=WECHAT_PROCESS_NAME)
    if hwnd:
        return hwnd

    # 依次尝试备选进程名
    for alt_name in _FALLBACK_PROCESS_NAMES:
        if alt_name == WECHAT_PROCESS_NAME:
            continue
        hwnd = window_ctrl.find(title=WECHAT_WINDOW_TITLE, process_name=alt_name)
        if hwnd:
            logger.info("微信进程名自动切换: {} -> {}", WECHAT_PROCESS_NAME, alt_name)
            WECHAT_PROCESS_NAME = alt_name
            _update_env_process_name(alt_name)
            return hwnd

    return None


# AI 回复消息的固定前缀，用于在"文件传输助手"中区分 AI 回复（sent）和用户自己发的消息（received）
_wechat_config_path = os.path.join(PROJECT_ROOT, "wechat.json")
_alias_name = "Workmate"
if os.path.isfile(_wechat_config_path):
    try:
        with open(_wechat_config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            _alias_name = cfg.get("alias_name", _alias_name)
    except Exception:
        pass
WECHAT_AI_REPLY_PREFIX = os.environ.get(
    "WECHAT_AI_REPLY_PREFIX", f"现在是{_alias_name}与您对话"
)


def _load_audio_cache():
    audio_cache_file = _get_audio_cache_file()
    if audio_cache_file and os.path.exists(audio_cache_file):
        try:
            with open(audio_cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


def _save_audio_cache(cache):
    audio_cache_file = _get_audio_cache_file()
    if not audio_cache_file:
        return
    try:
        os.makedirs(os.path.dirname(audio_cache_file), exist_ok=True)
        with open(audio_cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except:
        pass


# 匹配微信语音时长格式：3" / 3'' / 3' / 3s / 3秒 / 3″ 等
_VOICE_DURATION_RE = re.compile(r"""^\d+["''\u2019\u201d\u2033\u2032s秒]+$""")


def _collect_text_nodes(item, exclude_texts):
    """递归收集所有 Text 控件的文本，排除时间戳、时长和指定文本"""
    texts = []
    try:
        if item.element_info.control_type == "Text":
            text = item.window_text().strip()
            if (
                text
                and text not in exclude_texts
                and not text.startswith("[语音]")
                and not re.match(r"^\d{1,2}:\d{2}$", text)
                and not _VOICE_DURATION_RE.match(text)
            ):
                texts.append(text)
        for child in item.children():
            texts.extend(_collect_text_nodes(child, exclude_texts))
    except:
        pass
    return texts


def _get_voice_bubble_pane(item):
    """获取语音消息气泡的可点击 Pane，用于触发右键菜单。

    头像在左（普通联系人，对方发来）UI 树：
      ListItem
        Pane                               ← [0]
          Button (头像)                    ← [0][0]
          Pane (气泡外层)                  ← [0][1]
            Pane                          ← [0][1][0]
              Pane                        ← [0][1][0][0]
                Pane (右键目标)           ← [0][1][0][0][0]

    头像在右（文件传输助手，自己发给自己）UI 树：
      ListItem
        Pane                               ← [0]
          Pane (头像区)                    ← [0][0]
          Pane (气泡外层)                  ← [0][1]
            Pane                          ← [0][1][0]
              Pane (语音图标)              ← [0][1][0][0]
              Pane (右键目标)              ← [0][1][0][1]
          Button (头像按钮)
    """
    try:
        outer = item.children()[0]
        pane_children = outer.children()
        # 头像在左：第一个子元素是 Button
        if pane_children and pane_children[0].element_info.control_type == "Button":
            target = outer.children()[1].children()[0].children()[0].children()[0]
            if target.element_info.control_type == "Pane":
                return target
    except Exception:
        pass

    try:
        # 头像在右（文件传输助手）：路径 [0][1][0][1]
        target = item.children()[0].children()[1].children()[0].children()[1]
        if target.element_info.control_type == "Pane":
            return target
    except Exception:
        pass

    try:
        outer = item.children()[0]
        children = outer.children()
        if len(children) >= 2:
            return children[1]
    except Exception:
        pass

    return item


def _is_voice_message(item) -> bool:
    """判断消息条目是否为语音消息。

    微信语音消息的 window_text() 可能返回空字符串或时长（如 '3"' / "3''" / '3s'）。
    通过两种方式识别：
    1. item 自身的 window_text() 符合时长格式
    2. 递归子树中存在符合时长格式的 Text 节点
    """
    _DURATION_RE = _VOICE_DURATION_RE

    title = item.window_text().strip()
    if _DURATION_RE.match(title):
        return True

    def _walk(node) -> bool:
        try:
            if node.element_info.control_type == "Text":
                if _DURATION_RE.match(node.window_text().strip()):
                    return True
            for child in node.children():
                if _walk(child):
                    return True
        except Exception:
            pass
        return False

    return _walk(item)


async def _scroll_item_into_view(item, message_list, input_sim) -> None:
    """将消息条目滚动到聊天区可见范围内，确保点击坐标不超出列表边界。

    采用"小步快跑"策略：每次固定滚动 3 格，等待 UI 刷新后重新判断，
    避免依赖不可靠的像素/格换算经验值导致滚动量不足或过头。

    普通条目（高度 <= 列表高度）：要求完全可见。
    超大条目（高度 > 列表高度，如大图）：要求条目中心可见。
    """
    try:
        list_rect = message_list.rectangle()
        list_center_x = (list_rect.left + list_rect.right) // 2
        list_center_y = (list_rect.top + list_rect.bottom) // 2
        list_height = list_rect.bottom - list_rect.top
        step = 3
        last_item_rect = None

        for _ in range(3):
            item_rect = item.rectangle()

            # 如果连续两次获取的矩形区域相同，说明已经滚动到底部或顶部，无法继续滚动，直接退出
            if last_item_rect and item_rect == last_item_rect:
                break
            last_item_rect = item_rect

            item_top = item_rect.top
            item_bottom = item_rect.bottom
            item_center_y = (item_top + item_bottom) // 2
            item_height = item_bottom - item_top
            list_top = list_rect.top
            list_bottom = list_rect.bottom

            if item_height <= list_height:
                if item_top >= list_top and item_bottom <= list_bottom:
                    break
                # pynput scroll(0, +N): 滚轮向前（上滚）→ 内容下移 → 显示更旧消息
                # pynput scroll(0, -N): 滚轮向后（下滚）→ 内容上移 → 显示更新消息
                direction = 1 if item_top < list_top else -1
            else:
                if list_top <= item_center_y <= list_bottom:
                    break
                direction = 1 if item_center_y < list_top else -1

            input_sim._mouse_controller.position = (list_center_x, list_center_y)
            input_sim._mouse_controller.scroll(0, direction * step)
            await asyncio.sleep(0.4)
    except Exception:
        pass


async def _scroll_to_bottom(message_list, input_sim) -> None:
    """将消息列表滚动到底部，确保最新消息可见。

    pynput scroll(0, -N) = 滚轮向后（下滚）→ 内容上移 → 显示更新/底部消息。
    微信到达底部后会自动停止滚动，所以用足够大的滚动量即可。
    """
    try:
        list_rect = message_list.rectangle()
        list_center_x = (list_rect.left + list_rect.right) // 2
        list_center_y = (list_rect.top + list_rect.bottom) // 2
        input_sim._mouse_controller.position = (list_center_x, list_center_y)
        # 持续向下滚动（负值），每次滚动 50 格，共 20 次
        # 微信在到达历史消息底部后 wheel 不再生效，因此不会过度滚动
        for _ in range(20):
            input_sim._mouse_controller.scroll(0, -50)
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.5)
    except Exception:
        pass


async def _restore_and_activate_wechat(window_ctrl) -> bool:
    """恢复最小化并激活微信窗口，确保右键菜单弹出在微信上而非其他软件。

    先 restore（防止最小化状态），再 activate（置前台），等待窗口真正可见。
    返回 True 表示成功找到并激活，False 表示未找到微信窗口。
    """
    hwnd = _find_wechat_window(window_ctrl)
    if not hwnd:
        return False
    window_ctrl.set_state(hwnd, "restore")
    await asyncio.sleep(0.3)
    window_ctrl.set_state(hwnd, "activate")
    await asyncio.sleep(0.4)
    return True


async def _focus_message_list(message_list, input_sim) -> None:
    """单击聊天消息列表顶部空白区，将焦点从输入框拉回对话区。

    点击顶部（top + 10px）而非中心，避免误触附件气泡。
    顶部区域通常是时间戳或空白，不会触发附件操作。
    """
    try:
        rect = message_list.rectangle()
        cx = (rect.left + rect.right) // 2
        cy = rect.top + 10
        input_sim.mouse_click(cx, cy)
        await asyncio.sleep(0.3)
    except Exception:
        pass


async def _get_audio_text(
    item, sender, contact, msg_index, wechat_window, window_ctrl=None
):
    """获取语音消息的文字内容，优先读缓存，其次触发右键转文字"""
    cache = _load_audio_cache()
    cache_key = f"{contact}_{sender}_{msg_index}"

    if cache_key in cache:
        return cache[cache_key]

    exclude_texts = {sender, contact, "文件传输助手"}

    # 先尝试直接提取（已转换过的情况）
    texts = _collect_text_nodes(item, exclude_texts)
    if texts:
        result = f"[语音转文字] {''.join(texts)}"
        cache[cache_key] = result
        _save_audio_cache(cache)
        return result

    # 触发右键菜单转文字
    try:
        # 右键前恢复最小化并激活微信窗口，防止菜单弹到其他软件
        if window_ctrl:
            await _restore_and_activate_wechat(window_ctrl)
        bubble = _get_voice_bubble_pane(item)
        bubble.click_input(button="right")
        await asyncio.sleep(0.3)

        # 菜单是微信主窗口的子元素，不在顶层窗口列表中
        menu = wechat_window.child_window(control_type="Menu", class_name="CMenuWnd")
        if not menu.exists(timeout=1.0):
            return "[语音]"

        menu_list = menu.child_window(control_type="List")
        for mi in menu_list.children():
            if (
                mi.element_info.control_type == "MenuItem"
                and mi.window_text() == "语音转文字"
            ):
                mi.click_input()
                # 轮询等待转换结果，最多 8 秒，每 0.5 秒检查一次
                for _ in range(16):
                    await asyncio.sleep(0.5)
                    texts = _collect_text_nodes(item, exclude_texts)
                    if texts:
                        result = f"[语音转文字] {''.join(texts)}"
                        cache[cache_key] = result
                        _save_audio_cache(cache)
                        return result
                break
    except Exception as e:
        logger.error("Error converting audio: {}", e)

    return "[语音]"


# ── 附件处理 ──────────────────────────────────────────────────────────────────

_attachment_dir_env = os.environ.get(
    "WECHAT_ATTACHMENT_SAVE_DIR", "tools/wechat_attachments"
)

_attachment_cache_env = os.environ.get(
    "WECHAT_ATTACHMENT_CACHE_FILE", "tools/config/wechat_attachment_cache.json"
)


def _get_attachment_save_dir() -> str:
    return _resolve_template_path(_attachment_dir_env)


def _get_attachment_cache_file() -> str:
    return _resolve_template_path(_attachment_cache_env)


# 附件缓存 TTL（秒）：默认 3600（1小时），count=1 场景使用短 TTL
_ATTACHMENT_CACHE_TTL = int(os.environ.get("WECHAT_ATTACHMENT_CACHE_TTL", "3600"))
_ATTACHMENT_CACHE_TTL_SHORT = int(
    os.environ.get("WECHAT_ATTACHMENT_CACHE_TTL_SHORT", "60")
)


def _build_content_id(contact: str, title: str) -> str:
    """基于联系人和消息标题生成内容唯一标识，用于缓存键。

    用 MD5 哈希替代不稳定的位置序号（pos/_idx），确保：
    - 同一联系人同一张图片在不同 count 场景下缓存键一致
    - 新图片不会命中旧图片的缓存
    """
    raw = f"{contact}:{title}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


# 附件消息前缀 → 类型映射
_ATTACHMENT_PREFIXES = {
    "[图片]": "image",
    "[动图]": "image",
    "[文件]": "file",
    "[视频]": "file",
}

# 支持解析的文件扩展名（与 doc_reader 保持一致）
_PARSEABLE_EXTS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".doc",
    ".ppt",
    ".pptx",
    ".csv",
    ".xls",
    ".xlsx",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
}


def _migrate_legacy_cache_keys(cache: dict) -> dict:
    """清理旧格式缓存键（使用位置序号的键如 image_李旬_0）。

    旧格式键以纯数字结尾（如 _0、_72），新格式键以 8 位哈希结尾（如 _a3b2c1d0）。
    清理策略：删除不含 _cached_at 时间戳的旧条目（无法判断过期），
    保留有 _cached_at 的旧条目（以防正在使用旧版本的并行进程）。
    """
    if not cache:
        return cache
    numeric_suffix_re = re.compile(r"_(\d+)$")
    to_delete = []
    for key in cache:
        # 匹配旧格式键：image_xxx_数字 或 file_xxx_数字
        if numeric_suffix_re.search(key):
            entry = cache[key]
            # 无 _cached_at 的旧条目说明来自旧版本，无法判断过期时间，直接清除
            if "_cached_at" not in entry:
                to_delete.append(key)
    for key in to_delete:
        del cache[key]
    if to_delete:
        logger.info("已清理 {} 条旧格式附件缓存条目（无时间戳）", len(to_delete))
        _save_attachment_cache(cache)
    return cache


def _load_attachment_cache() -> dict:
    attachment_cache_file = _get_attachment_cache_file()
    if attachment_cache_file and os.path.exists(attachment_cache_file):
        try:
            with open(attachment_cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
                return _migrate_legacy_cache_keys(cache)
        except:
            return {}
    return {}


def _save_attachment_cache(cache: dict):
    attachment_cache_file = _get_attachment_cache_file()
    if not attachment_cache_file:
        return
    try:
        os.makedirs(os.path.dirname(attachment_cache_file), exist_ok=True)
        with open(attachment_cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 微信对话历史轮次管理（用于 monitor_wechat_messages 的上下文记忆）
# ═══════════════════════════════════════════════════════════════════════════════

# 历史文件存放目录，通过环境变量 WECHAT_HISTORY_DIR 可自定义
_wechat_history_env = os.environ.get(
    "WECHAT_HISTORY_DIR", "tools/config/wechat_history"
)

# 最多保留的历史轮次数
_MAX_HISTORY_ROUNDS = 5

# 向上滚动加载更早消息时，每次滚动的格数
_SCROLL_UP_STEP = 3
# 向上滚动最多轮数（防止 UI 卡死）
_SCROLL_UP_MAX_ITERATIONS = 15


def _get_wechat_history_dir() -> str:
    """获取微信对话历史文件的存放目录"""
    return _resolve_template_path(_wechat_history_env)


def _get_wechat_history_file(contact: str) -> str:
    """根据联系人名称生成安全的历史文件路径"""
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", contact)
    history_dir = _get_wechat_history_dir()
    return os.path.join(history_dir, f"{safe_name}.json")


def _load_wechat_history(contact: str) -> dict:
    """加载联系人的历史对话轮次

    Returns:
        {"rounds": [...], "last_updated": "..."} 或空字典
    """
    history_file = _get_wechat_history_file(contact)
    if not os.path.isfile(history_file):
        return {}
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_wechat_history(contact: str, rounds: list[dict]) -> None:
    """保存联系人的历史对话轮次到文件

    自动裁剪为最近 _MAX_HISTORY_ROUNDS 轮。
    rounds 中每条消息格式: {"type": "sent"/"received"/"system", "sender": "...", "content": "..."}
    """
    if not rounds:
        return
    history_file = _get_wechat_history_file(contact)
    try:
        os.makedirs(os.path.dirname(history_file), exist_ok=True)
        payload = {
            "contact": contact,
            "rounds": rounds,
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _split_messages_into_rounds(messages: list[dict]) -> list[list[dict]]:
    """将消息列表按轮次边界拆分为多个轮次

    轮次定义：从旧到新遍历消息，每当在 sent 消息之后出现 received 消息，
    就是一个新的 Round 开始。

    每轮消息保存为精简格式（仅保留 type、sender、content、attachment_path、link_url）。

    Returns:
        [round1_messages, round2_messages, ...]，每个元素是一条消息列表
    """
    if not messages:
        return []

    rounds = []
    current_round = []

    for msg in messages:
        msg_type = msg.get("type", "")
        # 跳过 system 消息（时间戳等）——不作为轮次拆分依据
        if msg_type == "system":
            continue

        # 如果当前轮次中已有 sent 消息，又出现 received 消息 → 新轮次开始
        has_sent_in_current = any(m.get("type") == "sent" for m in current_round)
        if has_sent_in_current and msg_type == "received":
            if current_round:
                rounds.append(current_round)
            current_round = []

        # 精简条目，只保留必要字段
        entry = {
            "type": msg_type,
            "sender": msg.get("sender", ""),
            "content": msg.get("content", ""),
        }
        if msg.get("attachment_path"):
            entry["attachment_path"] = msg["attachment_path"]
        if msg.get("link_url"):
            entry["link_url"] = msg["link_url"]
        current_round.append(entry)

    if current_round:
        rounds.append(current_round)

    return rounds


async def _scroll_chat_up(message_list, input_sim, times: int = 3) -> None:
    """向上滚动聊天区域，加载更早的消息

    每次滚轮向前（上滚），让更旧的消息进入可见区域。
    先聚焦消息列表顶部空白区，避免误触附件气泡。

    pynput scroll(0, +N): 滚轮向前（上滚）→ 内容下移 → 显示更旧消息
    """
    try:
        rect = message_list.rectangle()
        cx = (rect.left + rect.right) // 2
        cy = rect.top + 10

        for _ in range(min(times, _SCROLL_UP_MAX_ITERATIONS)):
            input_sim._mouse_controller.position = (cx, cy)
            input_sim._mouse_controller.scroll(0, _SCROLL_UP_STEP)
            await asyncio.sleep(0.4)
    except Exception:
        pass


def _deduplicate_messages(existing: list[dict], new: list[dict]) -> list[dict]:
    """将新读取的消息与已有消息列表去重合并

    基于 (type, sender, content) 三元组进行去重。
    假设 new 中的消息更新（在后面），existing 在前面。
    """
    seen = set()
    result = []

    for msg in existing:
        key = (msg.get("type", ""), msg.get("sender", ""), msg.get("content", ""))
        if key not in seen:
            seen.add(key)
            result.append(msg)

    for msg in new:
        key = (msg.get("type", ""), msg.get("sender", ""), msg.get("content", ""))
        if key not in seen:
            seen.add(key)
            result.append(msg)

    return result


def _deduplicate_boundary_rounds(
    previous_rounds: list[list[dict]],
    new_rounds: list[list[dict]],
) -> list[list[dict]]:
    """去掉 new_rounds 中与 previous_rounds 尾部重叠的轮次

    两个示例：
    - 文件 [8,7,6,5,4] + 窗口 [5,4,3,2,1] → 窗口的轮5、轮4与文件重叠 → 返回 [3,2,1]
    - 文件 [11,10,9,8,7] + 窗口 [5,4,3,2,1] → 完全不重叠 → 返回 [5,4,3,2,1]

    匹配规则：如果 new_rounds 中某轮有任意一条消息的 (type,sender,content)
    三元组出现在 previous_rounds 的任意轮次中，则认为该轮重叠。
    从 oldest 向 newest 遍历，一旦遇到不重叠的轮次，后续轮次都保留。
    """
    if not previous_rounds or not new_rounds:
        return list(new_rounds)

    # 收集文件历史中所有消息的键
    file_msg_keys = set()
    for round_msgs in previous_rounds:
        for msg in round_msgs:
            if msg.get("type") != "system":
                file_msg_keys.add(
                    (
                        msg.get("type", ""),
                        msg.get("sender", ""),
                        msg.get("content", ""),
                    )
                )

    # 从 oldest → newest 遍历窗口轮次，跳过与文件重叠的
    result = []
    found_non_overlap = False
    for round_msgs in new_rounds:
        # 已经找到非重叠轮次后，后续全部保留
        if found_non_overlap:
            result.append(round_msgs)
            continue

        # 检查当前轮次是否与文件重叠
        overlaps = False
        for msg in round_msgs:
            if msg.get("type") == "system":
                continue
            key = (msg.get("type", ""), msg.get("sender", ""), msg.get("content", ""))
            if key in file_msg_keys:
                overlaps = True
                break

        if overlaps:
            continue  # 重叠，跳过

        found_non_overlap = True
        result.append(round_msgs)

    return result


def _has_continuity_gap(
    file_rounds: list[list[dict]], current_messages: list[dict]
) -> bool:
    """检查文件中的历史轮次与当前窗口消息之间是否存在断裂

    连续性判断：文件中最新的那条消息，是否也出现在当前窗口的消息列表中？
    - 如果重叠 → 文件历史与当前窗口连续，无需从微信窗口补充加载
    - 如果完全不重叠 → 文件历史已过时（期间发生了未被监控的对话），需要从窗口加载

    基于 (type, sender, content) 三元组进行匹配。
    system 类型消息不参与比较。

    Returns:
        True 表示存在断裂，需要从窗口补充加载
        False 表示连续，文件历史可信
    """
    if not file_rounds or not current_messages:
        return True

    # 扁平化文件轮次中的所有消息，提取键集合
    file_msg_keys = set()
    for round_msgs in file_rounds:
        for msg in round_msgs:
            if msg.get("type") != "system":
                file_msg_keys.add(
                    (
                        msg.get("type", ""),
                        msg.get("sender", ""),
                        msg.get("content", ""),
                    )
                )

    # 检查当前窗口中是否有消息与文件历史重叠
    for msg in current_messages:
        if msg.get("type") == "system":
            continue
        key = (msg.get("type", ""), msg.get("sender", ""), msg.get("content", ""))
        if key in file_msg_keys:
            return False

    return True


def _is_system_divider(title: str) -> bool:
    """判断消息标题是否为微信系统分隔线（如'以下为新消息'、'查看更多消息'等）"""
    if not title:
        return True
    system_dividers = {"查看更多消息"}
    if title in system_dividers:
        return True
    if title.startswith("以下") and ("新消息" in title or "消息" in title):
        return True
    return False


def _detect_attachment_type(title: str) -> str | None:
    """根据消息文本识别附件类型，返回 'image'、'file' 或 None"""
    for prefix, atype in _ATTACHMENT_PREFIXES.items():
        if title.startswith(prefix):
            return atype
    return None


def _detect_link_message(title: str) -> bool:
    """检测消息是否为链接消息"""
    return title == "[链接]"


async def _get_link_url(
    item, window, input_sim, window_ctrl, message_list=None
) -> str | None:
    """获取链接消息的 URL

    通过右键菜单选择"用默认浏览器打开"，然后从浏览器地址栏获取 URL。
    返回 URL 字符串，如果失败则返回 None。
    """
    import pyperclip

    try:
        # 滚动到可见区域
        if message_list is not None:
            await _scroll_item_into_view(item, message_list, input_sim)

        # 右键点击获取菜单
        bubble = _get_voice_bubble_pane(item)
        bubble.click_input(button="right")
        await asyncio.sleep(0.5)

        # 查找菜单
        menu = window.child_window(control_type="Menu", class_name="CMenuWnd")
        if not menu.exists(timeout=1.5):
            return None

        # 查找"用默认浏览器打开"选项
        for mi in menu.child_window(control_type="List").children():
            if mi.element_info.control_type == "MenuItem":
                text = mi.window_text()
                if "浏览器" in text:
                    mi.click_input()
                    await asyncio.sleep(3.0)

                    # 切换到浏览器窗口并获取地址栏 URL
                    import win32gui

                    hwnd = win32gui.GetForegroundWindow()
                    title = win32gui.GetWindowText(hwnd)

                    # 聚焦地址栏并复制 URL
                    input_sim.keyboard_hotkey("ctrl", "l")
                    await asyncio.sleep(0.5)
                    input_sim.keyboard_hotkey("ctrl", "a")
                    await asyncio.sleep(0.2)
                    input_sim.keyboard_hotkey("ctrl", "c")
                    await asyncio.sleep(0.3)

                    url = pyperclip.paste()

                    # 关闭浏览器标签（Ctrl+W）
                    input_sim.keyboard_hotkey("ctrl", "w")
                    await asyncio.sleep(0.3)

                    return url if url and "http" in url else None
        return None
    except Exception as e:
        return None


async def _handle_save_dialog(
    save_path: str,
    input_sim,
    window_ctrl,
    keep_filename: bool = False,
    message_list=None,
) -> bool:
    """等待并处理 Windows '另存为' 对话框，填入保存路径后确认保存。

    keep_filename=True 时只切换目录、不修改文件名（用于图片等默认文件名正确的场景）。
    此时 save_path 可以直接传目录路径。
    message_list 不为 None 时，保存完成后立即将焦点拉回聊天区域顶部。

    确认保存策略（多层回退）：
    1. pywinauto 查找"保存"按钮并点击
    2. Enter 键确认
    3. Alt+S 快捷键确认
    """
    save_dir = save_path if keep_filename else os.path.dirname(save_path)

    # 等待另存为对话框出现（最多 5 秒）
    dialog_hwnd = None
    for _ in range(10):
        await asyncio.sleep(0.5)
        # 微信另存为对话框标题可能因版本不同而变化
        for dialog_title in ("另存为", "Save As", "保存", "Save"):
            dialog_hwnd = window_ctrl.find(title=dialog_title)
            if dialog_hwnd:
                break
        if dialog_hwnd:
            break

    if not dialog_hwnd:
        logger.info("[SaveDialog] ❌ 另存为对话框未出现")
        return False

    logger.info(f"[SaveDialog] ✓ 对话框出现, hwnd={dialog_hwnd}")
    window_ctrl.set_state(dialog_hwnd, "activate")
    await asyncio.sleep(0.5)

    # 切换到目标目录
    input_sim.keyboard_hotkey("alt", "d")
    await asyncio.sleep(0.3)
    input_sim.clipboard_set_and_paste(save_dir)
    await asyncio.sleep(0.3)
    input_sim.keyboard_hotkey("enter")
    await asyncio.sleep(1.0)

    if not keep_filename:
        # 修改文件名
        file_name = os.path.basename(save_path)
        dialog_hwnd = window_ctrl.find(title="另存为") or dialog_hwnd
        window_ctrl.set_state(dialog_hwnd, "activate")
        await asyncio.sleep(0.3)
        input_sim.keyboard_hotkey("alt", "n")
        await asyncio.sleep(0.2)
        input_sim.clipboard_set_and_paste(file_name)
        await asyncio.sleep(0.2)

    # 确认保存——多层回退策略
    # 策略 1：用 pywinauto 直接查找并点击"保存"按钮（最可靠）
    save_clicked = False
    try:
        from pywinauto import Application

        # 重新查找对话框句柄（切换目录后句柄可能变化）
        current_hwnd = None
        for dialog_title in ("另存为", "Save As", "保存", "Save"):
            current_hwnd = window_ctrl.find(title=dialog_title)
            if current_hwnd:
                break
        current_hwnd = current_hwnd or dialog_hwnd

        app = Application(backend="uia").connect(handle=current_hwnd)
        dlg = app.window(handle=current_hwnd)

        # 尝试各种可能的保存按钮标题
        for btn_title in ("保存", "Save", "确定", "OK", "是(Y)", "是(&Y)", "是", "Yes"):
            try:
                btn = dlg.child_window(title=btn_title, control_type="Button")
                if btn.exists(timeout=0.5):
                    btn.click_input()
                    save_clicked = True
                    logger.info(f"[SaveDialog] ✓ pywinauto 点击保存按钮: '{btn_title}'")
                    break
            except Exception:
                continue

        # 如果没找到标题匹配的按钮，尝试用 automation_id 查找
        if not save_clicked:
            try:
                btn = dlg.child_window(auto_id="1", control_type="Button")
                if btn.exists(timeout=0.5):
                    btn.click_input()
                    save_clicked = True
                    logger.info(
                        "[SaveDialog] ✓ pywinauto 通过 automation_id='1' 点击保存按钮"
                    )
            except Exception:
                pass
    except Exception as e:
        logger.info(f"[SaveDialog] pywinauto 查找保存按钮失败: {e}")

    # 策略 2：Enter 键确认（对话框焦点在保存按钮时有效）
    if not save_clicked:
        logger.info("[SaveDialog] 尝试 Enter 键确认保存...")
        input_sim.keyboard_hotkey("enter")
        await asyncio.sleep(1.0)
        save_clicked = True

    # 策略 3：Alt+S 快捷键（部分对话框支持）
    if not save_clicked:
        logger.info("[SaveDialog] 尝试 Alt+S 确认保存...")
        input_sim.keyboard_hotkey("alt", "s")
        await asyncio.sleep(1.0)

    # 处理文件已存在时弹出的"确认另存为"对话框
    # 默认焦点在"否"按钮，必须明确点击"是"按钮，不能用 Enter
    for confirm_title in ("确认另存为", "Confirm Save As"):
        confirm_hwnd = window_ctrl.find(title=confirm_title)
        if confirm_hwnd:
            logger.info(f"[SaveDialog] ✓ 检测到确认对话框: '{confirm_title}'")
            window_ctrl.set_state(confirm_hwnd, "activate")
            await asyncio.sleep(0.3)
            clicked = False
            try:
                from pywinauto import Application

                app = Application(backend="uia").connect(handle=confirm_hwnd)
                dlg = app.window(handle=confirm_hwnd)
                for btn_title in ("是(Y)", "是(&Y)", "是", "Yes"):
                    try:
                        btn = dlg.child_window(title=btn_title, control_type="Button")
                        if btn.exists(timeout=0.5):
                            btn.click_input()
                            clicked = True
                            logger.info(f"[SaveDialog] ✓ 点击确认按钮: '{btn_title}'")
                            break
                    except Exception:
                        continue
            except Exception:
                pass
            if not clicked:
                logger.info("[SaveDialog] 回退方案: Alt+Y 确认覆盖")
                input_sim.keyboard_hotkey("alt", "y")
            await asyncio.sleep(0.8)
            break

    # 验证保存是否成功：等待对话框关闭
    dialog_closed = False
    for _ in range(5):
        await asyncio.sleep(0.5)
        still_open = False
        for dialog_title in ("另存为", "Save As", "保存", "Save"):
            if window_ctrl.find(title=dialog_title):
                still_open = True
                break
        if not still_open:
            dialog_closed = True
            break

    if not dialog_closed:
        logger.info("[SaveDialog] ❌ 对话框仍然打开，保存可能失败")
        # 尝试按 Esc 关闭对话框，避免阻塞后续操作
        input_sim.keyboard_hotkey("esc")
        await asyncio.sleep(0.5)

    # 对话框关闭后焦点会落到微信输入框，立即将焦点拉回聊天区域
    if message_list is not None:
        await _focus_message_list(message_list, input_sim)

    if keep_filename:
        return os.path.isdir(save_dir)
    return os.path.exists(save_path)


def _safe_click_coords(bubble, list_rect):
    """计算气泡的安全点击坐标，确保坐标落在聊天列表可见区域内。

    优先使用气泡中心；若气泡底部超出列表底部，则将 y 坐标钳制到列表底部上方 10px。
    """
    b = bubble.rectangle()
    click_x = (b.left + b.right) // 2
    click_y = (b.top + b.bottom) // 2
    # 将 y 坐标限制在列表可见区域内（留 10px 安全边距）
    click_y = max(list_rect.top + 10, min(click_y, list_rect.bottom - 10))
    return click_x, click_y


def _find_image_viewer(window_ctrl) -> int | None:
    """查找微信图片查看器窗口句柄（ImagePreview 或 title 含"图片"的 WeChat 子窗口）"""
    for title_kw in ("图片", "ImagePreview"):
        hwnd = window_ctrl.find(title=title_kw, process_name=WECHAT_PROCESS_NAME)
        if hwnd:
            return hwnd
        for alt_name in _FALLBACK_PROCESS_NAMES:
            if alt_name == WECHAT_PROCESS_NAME:
                continue
            hwnd = window_ctrl.find(title=title_kw, process_name=alt_name)
            if hwnd:
                return hwnd
    return None


async def _close_image_viewer_if_open(
    window_ctrl, input_sim, max_wait: float = 3.0
) -> None:
    """若微信图片查看器已打开，发送 ESC 并等待其关闭。"""
    step = 0.3
    elapsed = 0.0
    while elapsed < max_wait:
        if _find_image_viewer(window_ctrl):
            input_sim.keyboard_hotkey("esc")
            await asyncio.sleep(step)
            elapsed += step
        else:
            break


async def _save_image_via_viewer(
    item, window, input_sim, window_ctrl, save_path: str, message_list=None
) -> bool:
    """图片另存为：左键点击缩略图触发原图缓存 → 等待查看器关闭 → 回到微信右键另存为"""
    logger.info("[SaveImage] 开始图片另存为流程...")

    # 先将焦点拉回聊天区域（上一次保存后焦点可能落到输入框）
    if message_list is not None:
        await _focus_message_list(message_list, input_sim)
    # 将图片条目完整滚动到可见区域，防止点击坐标超出微信窗口
    if message_list is not None:
        await _scroll_item_into_view(item, message_list, input_sim)
    await _restore_and_activate_wechat(window_ctrl)

    bubble = _get_voice_bubble_pane(item)
    logger.info(
        f"[SaveImage] 气泡类型={bubble.element_info.control_type}, "
        f"矩形={bubble.rectangle()}"
    )

    # 计算安全点击坐标（防止图片底部超出聊天区域导致点击落在窗口外）
    if message_list is not None:
        list_rect = message_list.rectangle()
        b_rect = bubble.rectangle()
        cx, cy = _safe_click_coords(bubble, list_rect)
        rel = (cx - b_rect.left, cy - b_rect.top)
        bubble.click_input(coords=rel)
    else:
        bubble.click_input()

    # 等待查看器出现（最多 3 秒），出现后关闭；若未出现说明图片已缓存，直接继续
    await asyncio.sleep(1.0)
    await _close_image_viewer_if_open(window_ctrl, input_sim, max_wait=3.0)

    # 确认查看器已完全关闭，再激活微信主窗口
    await asyncio.sleep(0.5)
    await _restore_and_activate_wechat(window_ctrl)
    # 额外等待微信主窗口完全获得焦点
    await asyncio.sleep(0.5)

    # 重新从 item 获取 bubble，因为查看器打开/关闭可能导致元素引用失效
    bubble = _get_voice_bubble_pane(item)
    logger.debug(
        f"[SaveImage] 查看器关闭后 bubble 类型={bubble.element_info.control_type}"
    )

    # 此时原图已缓存，在气泡上右键 → 另存为（与文件流程相同）
    if message_list is not None:
        list_rect = message_list.rectangle()
        b_rect = bubble.rectangle()
        cx, cy = _safe_click_coords(bubble, list_rect)
        rel = (cx - b_rect.left, cy - b_rect.top)
        bubble.click_input(button="right", coords=rel)
    else:
        bubble.click_input(button="right")
    await asyncio.sleep(0.4)

    menu = window.child_window(control_type="Menu", class_name="CMenuWnd")
    if not menu.exists(timeout=1.5):
        logger.info("[SaveImage] ❌ 右键菜单未出现")
        return False

    logger.info("[SaveImage] ✓ 右键菜单已出现")

    for mi in menu.child_window(control_type="List").children():
        if mi.element_info.control_type == "MenuItem" and (
            mi.window_text().startswith("另存为") or mi.window_text().startswith("保存")
        ):
            logger.info(f"[SaveImage] ✓ 找到菜单项: {mi.window_text()}")
            mi.click_input()
            # 图片使用默认文件名，只切换目录，不修改文件名
            result = await _handle_save_dialog(
                save_path,
                input_sim,
                window_ctrl,
                keep_filename=True,
                message_list=message_list,
            )
            logger.info(f"[SaveImage] 保存对话框结果: {result}")
            return result

    logger.info("[SaveImage] ❌ 未找到'另存为'菜单项")
    return False


async def _save_attachment_via_rightclick(
    item,
    window,
    input_sim,
    window_ctrl,
    is_image: bool,
    save_path: str,
    message_list=None,
) -> bool:
    """附件另存为入口：图片走查看器流程，其他附件直接右键气泡"""
    if is_image:
        return await _save_image_via_viewer(
            item, window, input_sim, window_ctrl, save_path, message_list
        )

    # 先将焦点拉回聊天区域（上一次保存后焦点可能落到输入框）
    if message_list is not None:
        await _focus_message_list(message_list, input_sim)
    # 右键前先将条目滚动到可见区域，再恢复激活微信窗口
    if message_list is not None:
        await _scroll_item_into_view(item, message_list, input_sim)
    await _restore_and_activate_wechat(window_ctrl)

    bubble = _get_voice_bubble_pane(item)
    bubble.click_input(button="right")
    await asyncio.sleep(0.4)

    menu = window.child_window(control_type="Menu", class_name="CMenuWnd")
    if not menu.exists(timeout=1.5):
        return False

    for mi in menu.child_window(control_type="List").children():
        if mi.element_info.control_type == "MenuItem" and (
            mi.window_text().startswith("另存为") or mi.window_text().startswith("保存")
        ):
            mi.click_input()
            # 只切换目录，保留微信默认文件名，避免修改文件名时出错
            return await _handle_save_dialog(
                save_path,
                input_sim,
                window_ctrl,
                keep_filename=True,
                message_list=message_list,
            )

    return False


def _extract_filename_from_item(item) -> str:
    """从文件消息 UI 元素中递归提取文件名（第一个非大小/来源的 Text 节点）"""
    _SIZE_PATTERN = re.compile(r"^\d+(\.\d+)?\s*(K|M|G|KB|MB|GB|B)$", re.IGNORECASE)
    _SOURCE_KEYWORDS = {"微信电脑版", "微信手机版", "微信"}

    def _walk(node) -> str:
        try:
            if node.element_info.control_type == "Text":
                text = node.window_text().strip()
                if (
                    text
                    and not _SIZE_PATTERN.match(text)
                    and text not in _SOURCE_KEYWORDS
                    and "." in text
                ):
                    return text
            for child in node.children():
                result = _walk(child)
                if result:
                    return result
        except Exception:
            pass
        return ""

    return _walk(item)


_SUMMARY_CHAR_LIMIT = 2000


async def _summarize_md(md_content: str, filename: str) -> str:
    """当 Markdown 内容超过字符阈值时，调用 LLM 生成中文摘要"""
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
        from ..doc_reader import DocumentReader

        cfg = DocumentReader.VISION_LLM_CONFIG
        llm = ChatOpenAI(
            model=cfg["model"],
            temperature=cfg["temperature"],
            top_p=cfg["top_p"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            extra_body=cfg["extra_body"],
        )
        prompt = (
            f"以下是文件《{filename}》的内容，请用中文生成一份简洁的摘要，"
            "涵盖核心观点、关键数据和主要结论，控制在500字以内：\n\n"
            f"{md_content[:8000]}"
        )
        resp = llm.invoke([HumanMessage(content=prompt)])
        return f"[摘要] {resp.content.strip()}"
    except Exception as e:
        return f"[摘要生成失败] {e}"


async def _get_attachment_content(
    item,
    sender: str,
    contact: str,
    msg_index: int,
    title: str,
    window,
    input_sim,
    window_ctrl,
    message_list=None,
    force_refresh: bool = False,
) -> dict:
    """处理附件消息：另存为本地 → 解析内容，返回 {content, attachment_path}

    缓存机制：
    - 缓存键使用 content_id（基于联系人+消息标题的哈希），而非位置序号
    - 缓存条目带 _cached_at 时间戳，超过 TTL 后自动失效
    - force_refresh=True 时跳过缓存，强制重新获取（适用于 count=1 获取最新消息的场景）
    """
    attachment_save_dir = _get_attachment_save_dir()
    os.makedirs(attachment_save_dir, exist_ok=True)

    atype = _detect_attachment_type(title)
    is_image = atype == "image"
    prefix = "image" if is_image else "file"

    # 使用 content_id 生成稳定的缓存键，替代旧的位置序号方案
    content_id = _build_content_id(contact, title)
    cache_key = f"{prefix}_{contact}_{content_id}"

    cache = _load_attachment_cache()

    # 检查缓存命中：需同时满足键存在、未过期
    # force_refresh=True 时使用短 TTL（60秒），适用于 count=1 获取最新消息
    # force_refresh=False 时使用标准 TTL（1小时），适用于全量获取场景
    if cache_key in cache:
        entry = cache[cache_key]
        cached_at = entry.get("_cached_at", 0)
        ttl = _ATTACHMENT_CACHE_TTL_SHORT if force_refresh else _ATTACHMENT_CACHE_TTL
        if time.time() - cached_at < ttl:
            # 缓存有效，直接返回（剔除内部字段）
            return {
                "content": entry.get("content", title),
                "attachment_path": entry.get("attachment_path"),
            }
        # 缓存已过期，删除并重新获取
        del cache[cache_key]

    # 记录保存前目录快照，保存后对比找到新文件
    before = (
        set(os.listdir(attachment_save_dir))
        if os.path.isdir(attachment_save_dir)
        else set()
    )
    os.makedirs(attachment_save_dir, exist_ok=True)

    ok = await _save_attachment_via_rightclick(
        item,
        window,
        input_sim,
        window_ctrl,
        is_image,
        save_path=attachment_save_dir,
        message_list=message_list,
    )
    if not ok:
        return {"content": title, "attachment_path": None}

    # 找到新增或被覆盖的附件文件
    after = set(os.listdir(attachment_save_dir))
    target_exts = (
        {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
        if is_image
        else _PARSEABLE_EXTS
    )

    new_files = [
        f for f in (after - before) if os.path.splitext(f)[1].lower() in target_exts
    ]
    save_path = os.path.join(attachment_save_dir, new_files[0]) if new_files else None

    # 如果没有新增文件，检测是否覆盖了已有文件（修改时间在最近5秒内）
    if not save_path:
        now = time.time()
        modified_files = [
            f
            for f in (before & after)
            if os.path.splitext(f)[1].lower() in target_exts
            and now - os.path.getmtime(os.path.join(attachment_save_dir, f)) < 5
        ]
        if is_image:
            save_path = (
                os.path.join(attachment_save_dir, modified_files[0])
                if modified_files
                else None
            )
        else:
            modified_files.sort(
                key=lambda f: os.path.getmtime(os.path.join(attachment_save_dir, f)),
                reverse=True,
            )
            save_path = (
                os.path.join(attachment_save_dir, modified_files[0])
                if modified_files
                else None
            )

    if not save_path or not os.path.exists(save_path):
        return {"content": title, "attachment_path": None}

    # 解析文件内容（调用 doc_reader，支持所有可解析格式）
    md_content = title
    try:
        from ..doc_reader import DocumentReader
        from ..security import PathValidator

        reader = DocumentReader(PathValidator([attachment_save_dir]))
        md_content = await reader.read_to_markdown(save_path)
    except Exception as e:
        md_content = f"[附件解析失败] {e}"

    # 内容过长时生成摘要
    if len(md_content) > _SUMMARY_CHAR_LIMIT:
        md_content = await _summarize_md(md_content, os.path.basename(save_path))

    # 写入缓存，附带时间戳用于 TTL 过期判断
    result = {
        "content": md_content,
        "attachment_path": save_path,
        "_cached_at": time.time(),
    }
    cache[cache_key] = result
    _save_attachment_cache(cache)
    return {"content": md_content, "attachment_path": save_path}


def _fix_llm_path_spaces(path: str) -> str:
    """修复 LLM 在数字与汉字之间错误插入的空格。

    LLM 有排版习惯，会在阿拉伯数字和汉字之间自动加空格（如 "2026 年" -> "2026年"）。
    本函数仅修复"数字↔汉字"边界处的空格，不影响路径中本身合法的空格（如 "Program Files"）。
    修复策略：先尝试修复，若修复后文件/目录存在则采用修复结果，否则返回原路径。
    """
    import os, re

    # 匹配：数字后跟空格再跟汉字，或汉字后跟空格再跟数字
    pattern = re.compile(r"(\d)\s+([\u4e00-\u9fff])|([\u4e00-\u9fff])\s+(\d)")
    fixed = pattern.sub(
        lambda m: (m.group(1) or "")
        + (m.group(2) or "")
        + (m.group(3) or "")
        + (m.group(4) or ""),
        path,
    )
    if fixed != path and (os.path.exists(fixed) or not os.path.exists(path)):
        return fixed
    return path


from fastmcp import Context

from ..context import mcp, get_windows_components

# Control whether WeChat tools are exposed
ENABLE_WECHAT_TOOLS = (
    os.environ.get("MCP_ENABLE_WECHAT_TOOLS", "true").lower() == "true"
)


def register_tool(*args, **kwargs):
    """Conditional tool registration decorator."""
    if ENABLE_WECHAT_TOOLS:
        return mcp.tool(*args, **kwargs)
    else:

        def decorator(func):
            return func

        return decorator


@register_tool()
async def send_wechat_file(
    chat_name: str,
    file_path: str,
    ctx: Context,
) -> str:
    """Send a file to a WeChat contact or group using the clipboard method.

    This tool automates the process of sending a file via WeChat by:
    1. Waking up WeChat using global hotkey (Ctrl+Alt+W)
    2. Finding and activating the WeChat window
    3. Using the search box (Ctrl+F) to find the contact
    4. Copying the file to the clipboard
    5. Pasting and sending the file

    Args:
        chat_name: The name of the contact or group to send the file to
        file_path: The absolute path to the file to send
        ctx: MCP context

    Returns:
        Result string indicating success or failure
    """
    try:
        # 修复 LLM 在数字与汉字之间错误插入的空格（如 "2026 年" -> "2026年"）
        file_path = _fix_llm_path_spaces(file_path)

        # Verify file exists
        if not os.path.exists(file_path):
            return f"Error: File does not exist: {file_path}"

        components = get_windows_components()
        window_ctrl = components["window_controller"]
        input_sim = components["input_simulator"]

        ctx.info(f"Starting to send file '{file_path}' to '{chat_name}' via WeChat")

        # Step 1: Wake up WeChat
        ctx.info("Waking up WeChat...")
        input_sim.keyboard_hotkey("ctrl", "alt", "w")
        await asyncio.sleep(1.5)  # Wait for window to appear (increased from 1.0s)

        # Find WeChat window
        hwnd = _find_wechat_window(window_ctrl)
        if not hwnd:
            # Try one more time with a longer wait
            ctx.info("WeChat window not found, trying again...")
            input_sim.keyboard_hotkey("ctrl", "alt", "w")
            await asyncio.sleep(2.0)
            hwnd = _find_wechat_window(window_ctrl)

            if not hwnd:
                return "Error: Could not find WeChat window. Please make sure WeChat is running."

        # Activate window
        ctx.info("Activating WeChat window...")
        window_ctrl.set_state(hwnd, "activate")
        await asyncio.sleep(0.5)

        # Step 2: Search for contact
        ctx.info(f"Searching for contact: {chat_name}")
        input_sim.keyboard_hotkey("ctrl", "f")
        await asyncio.sleep(0.5)

        # Paste contact name
        input_sim.clipboard_set_and_paste(chat_name)
        await asyncio.sleep(1.0)  # Wait for search results

        # Enter chat
        input_sim.keyboard_hotkey("enter")
        await asyncio.sleep(0.5)

        # Step 3: Copy file to clipboard
        ctx.info("Copying file to clipboard...")
        if not input_sim.clipboard_copy_file([file_path]):
            return "Error: Failed to copy file to clipboard."
        await asyncio.sleep(0.5)

        # Step 4: Paste and send
        ctx.info("Pasting and sending file...")
        input_sim.keyboard_hotkey("ctrl", "v")
        await asyncio.sleep(0.5)  # Wait for file to load in input box

        input_sim.keyboard_hotkey("enter")
        await asyncio.sleep(0.5)  # Wait for send to complete

        # Step 5: Close window
        ctx.info("Closing WeChat window...")
        input_sim.keyboard_hotkey("esc")

        ctx.info("File sent successfully")
        return f"Success: Sent file '{file_path}' to '{chat_name}'"

    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def send_wechat_message(
    chat_name: str,
    messages: list[str],
    ctx: Context,
) -> str:
    """向微信联系人或群聊连续发送一条或多条文本消息（剪贴板方式）。

    自动化流程：
    1. 使用全局热键（Ctrl+Alt+W）唤醒微信
    2. 查找并激活微信窗口
    3. 使用搜索框（Ctrl+F）查找联系人
    4. 按数组顺序逐条复制消息到剪贴板并粘贴发送
    5. 全部发送完成后关闭窗口

    Args:
        chat_name: 要发送消息的联系人或群聊名称
        messages: 要发送的文本消息列表，按数组顺序依次发送
        ctx: MCP 上下文

    Returns:
        表示成功或失败的结果字符串
    """
    try:
        # 兼容旧调用方式：如果传入单个字符串，自动转为列表
        if isinstance(messages, str):
            messages = [messages]

        if not messages:
            return "Error: messages list is empty"

        components = get_windows_components()
        window_ctrl = components["window_controller"]
        input_sim = components["input_simulator"]

        ctx.info(f"准备向 '{chat_name}' 发送 {len(messages)} 条微信消息")

        # Step 1: 唤醒微信
        ctx.info("正在唤醒微信...")
        input_sim.keyboard_hotkey("ctrl", "alt", "w")
        await asyncio.sleep(1.5)

        # 查找微信窗口
        hwnd = _find_wechat_window(window_ctrl)
        if not hwnd:
            ctx.info("未找到微信窗口，重试中...")
            input_sim.keyboard_hotkey("ctrl", "alt", "w")
            await asyncio.sleep(2.0)
            hwnd = _find_wechat_window(window_ctrl)

            if not hwnd:
                return "Error: 未找到微信窗口，请确保微信正在运行"

        # 激活窗口
        ctx.info("正在激活微信窗口...")
        window_ctrl.set_state(hwnd, "activate")
        await asyncio.sleep(0.5)

        # Step 2: 搜索联系人
        ctx.info(f"正在搜索联系人: {chat_name}")
        input_sim.keyboard_hotkey("ctrl", "f")
        await asyncio.sleep(0.5)

        # 粘贴联系人名称
        input_sim.clipboard_set_and_paste(chat_name)
        await asyncio.sleep(1.0)

        # 进入聊天
        input_sim.keyboard_hotkey("enter")
        await asyncio.sleep(0.5)

        # Step 3: 逐条发送消息
        for idx, msg in enumerate(messages, 1):
            ctx.info(f"正在发送第 {idx}/{len(messages)} 条消息...")
            input_sim.clipboard_set_and_paste(msg)
            await asyncio.sleep(0.3)
            input_sim.keyboard_hotkey("enter")
            # 最后一条消息不需要额外等待（后面直接关闭窗口）
            if idx < len(messages):
                await asyncio.sleep(0.5)

        # Step 4: 关闭窗口
        ctx.info("正在关闭微信窗口...")
        input_sim.keyboard_hotkey("esc")

        ctx.info(f"已成功向 '{chat_name}' 发送 {len(messages)} 条消息")
        return f"Success: 已向 '{chat_name}' 发送 {len(messages)} 条消息"

    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def get_wechat_unread_contacts(
    ctx: Context,
) -> str:
    """Get a list of contacts with unread messages in WeChat.

    This tool automates the process of finding unread messages by:
    1. Waking up WeChat using global hotkey (Ctrl+Alt+W)
    2. Finding and activating the WeChat window
    3. Scanning the conversation list for unread indicators

    Args:
        ctx: MCP context

    Returns:
        JSON string containing a list of contact names with unread messages
    """
    import json
    import re

    try:
        components = get_windows_components()
        window_ctrl = components["window_controller"]
        input_sim = components["input_simulator"]
        ui_auto = components["ui_automation"]

        ctx.info("Starting to check for unread WeChat messages")

        # Step 1: Wake up WeChat
        ctx.info("Waking up WeChat...")
        input_sim.keyboard_hotkey("ctrl", "alt", "w")
        await asyncio.sleep(1.5)  # Wait for window to appear

        # Find WeChat window
        hwnd = _find_wechat_window(window_ctrl)
        if not hwnd:
            # Try one more time with a longer wait
            ctx.info("WeChat window not found, trying again...")
            input_sim.keyboard_hotkey("ctrl", "alt", "w")
            await asyncio.sleep(2.0)
            hwnd = _find_wechat_window(window_ctrl)

            if not hwnd:
                return "Error: Could not find WeChat window. Please make sure WeChat is running."

        # Activate window
        ctx.info("Activating WeChat window...")
        window_ctrl.set_state(hwnd, "activate")
        await asyncio.sleep(0.5)

        # Step 2: Connect to UI Automation and find the session list
        ctx.info("Scanning conversation list...")
        ui_auto.connect(str(hwnd))
        window = ui_auto._window

        if not window:
            return "Error: Could not connect to WeChat UI."

        try:
            session_list = window.child_window(title="会话", control_type="List")
            if not session_list.exists():
                return "Error: Could not find conversation list."
        except Exception as e:
            return f"Error finding conversation list: {str(e)}"

        # Step 3: Extract unread contacts
        unread_contacts = []
        for item in session_list.children():
            try:
                if item.element_info.control_type == "ListItem":
                    children = item.children()
                    if children and children[0].element_info.control_type == "Pane":
                        pane_children = children[0].children()
                        # Unread items typically have 3 children in their first Pane
                        if len(pane_children) == 3:
                            title = item.window_text()
                            # Remove the "X条新消息" suffix if present
                            contact_name = re.sub(r"\d+条新消息$", "", title)
                            if contact_name and contact_name != "SessionListItem":
                                unread_contacts.append(contact_name)
            except Exception:
                continue

        # Step 4: Close window
        ctx.info("Closing WeChat window...")
        input_sim.keyboard_hotkey("esc")

        return json.dumps(unread_contacts, ensure_ascii=False)

    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def monitor_wechat_messages(
    contacts: str,
    ctx: Context,
) -> str:
    """监控微信特定联系人的未回复消息，同时提供历史对话轮次作为上下文。

    自动化流程：
    1. 使用全局热键（Ctrl+Alt+W）唤醒微信
    2. 遍历监控列表中的联系人
    3. 搜索每个联系人并打开其聊天窗口
    4. 解析聊天记录，找出未回复的消息
    5. 加载历史对话文件，必要时向上滚动补充上下文（最多5轮）
    6. 自动保存已完成的对话轮次到历史文件

    Args:
        contacts: 要监控的联系人名称，多个用逗号分隔
        ctx: MCP 上下文

    Returns:
        JSON 字符串，包含以下字段的数组：
        - chat_name: 联系人名称
        - messages: 本轮未回复的消息列表
        - history: 当前窗口可见的全部消息列表
        - previous_rounds: 历史对话轮次（最近5轮），用于上下文理解
          每轮格式: {"round_id": N, "messages": [{type, sender, content}, ...]}
    """
    import json

    try:
        # Parse the contacts list
        contact_list = [c.strip() for c in contacts.split(",") if c.strip()]
        if not contact_list:
            return "Error: No contacts provided to monitor."

        ctx.info(
            f"Monitoring WeChat for unreplied messages from: {', '.join(contact_list)}"
        )

        components = get_windows_components()
        window_ctrl = components["window_controller"]
        input_sim = components["input_simulator"]
        ui_auto = components["ui_automation"]

        # Step 1: Wake up WeChat
        ctx.info("Waking up WeChat...")
        input_sim.keyboard_hotkey("ctrl", "alt", "w")
        await asyncio.sleep(1.5)  # Wait for window to appear

        # Find WeChat window
        hwnd = _find_wechat_window(window_ctrl)
        if not hwnd:
            ctx.info("WeChat window not found, trying again...")
            input_sim.keyboard_hotkey("ctrl", "alt", "w")
            await asyncio.sleep(2.0)
            hwnd = _find_wechat_window(window_ctrl)

            if not hwnd:
                return "Error: Could not find WeChat window. Please make sure WeChat is running."

        # Activate window
        ctx.info("Activating WeChat window...")
        window_ctrl.set_state(hwnd, "activate")
        await asyncio.sleep(0.5)

        ui_auto.connect(str(hwnd))
        window = ui_auto._window

        if not window:
            return "Error: Could not connect to WeChat UI."

        results = []

        # Step 2: Iterate through contacts
        for contact in contact_list:
            ctx.info(f"Checking contact: {contact}")

            # 搜索联系人并进入对话
            input_sim.keyboard_hotkey("ctrl", "f")
            await asyncio.sleep(0.6)
            input_sim.clipboard_set_and_paste(contact)
            await asyncio.sleep(1.2)
            input_sim.keyboard_hotkey("enter")
            await asyncio.sleep(1.5)

            # 等待消息列表加载，最多重试 5 次
            message_list = None
            for _ in range(5):
                try:
                    ml = window.child_window(title="消息", control_type="List")
                    if ml.exists(timeout=1.0):
                        message_list = ml
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.8)

            if message_list is None:
                ctx.warning(f"Could not find message list for {contact}")
                continue

            # 第一阶段：纯文本扫描，不触发任何右键操作
            # raw_messages 保存每条消息的基础信息和对应的 UI item 引用
            raw_messages = []
            for idx, item in enumerate(message_list.children()):
                try:
                    if item.element_info.control_type != "ListItem":
                        continue
                    title = item.window_text()
                    if _is_system_divider(title):
                        continue
                    children = item.children()
                    if not children:
                        continue
                    first_child = children[0]
                    if first_child.element_info.control_type == "Text":
                        raw_messages.append(
                            {
                                "type": "system",
                                "content": title,
                                "_item": None,
                                "_idx": idx,
                            }
                        )
                        continue
                    if first_child.element_info.control_type != "Pane":
                        continue
                    pane_children = first_child.children()
                    if not pane_children:
                        continue
                    sender = ""
                    msg_type = "received"
                    is_voice = _is_voice_message(item)
                    # 语音消息的 window_text() 返回时长（如 '3"'），不是 '[语音]'
                    # 通过子树结构检测，统一标记为 '[语音]' 便于后续处理
                    normalized_content = "[语音]" if is_voice else title
                    if pane_children[0].element_info.control_type == "Button":
                        # 头像在左侧 → 对方发送
                        sender = pane_children[0].window_text()
                        msg_type = "received"
                    elif pane_children[-1].element_info.control_type == "Button":
                        # 头像在右侧 → 自己发送
                        sender = pane_children[-1].window_text()
                        if contact == "文件传输助手":
                            # 文件传输助手是自己给自己发消息的特殊联系人：
                            # - AI 回复（以固定前缀开头的文字消息）→ sent
                            # - 用户自己发的消息（语音备忘、普通文字等）→ received（待处理）
                            msg_type = (
                                "sent"
                                if (
                                    not is_voice
                                    and normalized_content.startswith(
                                        WECHAT_AI_REPLY_PREFIX
                                    )
                                )
                                else "received"
                            )
                        else:
                            msg_type = "sent"
                    raw_messages.append(
                        {
                            "type": msg_type,
                            "sender": sender,
                            "content": normalized_content,
                            "_item": item,
                            "_idx": idx,
                        }
                    )
                except Exception:
                    continue

            # 第二阶段：从底部找出未回复消息的索引范围（遇到 sent 停止）
            unreplied_indices = []
            for i in range(len(raw_messages) - 1, -1, -1):
                raw = raw_messages[i]
                if raw["type"] == "system":
                    continue
                if raw["type"] == "sent":
                    break
                unreplied_indices.insert(0, i)

            # 第三阶段：对未回复消息触发右键解析（语音/附件），其余消息保持原始文本
            # 处理前先将聊天区滚动到第一条未回复消息，确保附件条目在可见区域内
            if unreplied_indices:
                first_item = raw_messages[unreplied_indices[0]].get("_item")
                if first_item is not None:
                    await _scroll_item_into_view(first_item, message_list, input_sim)

            parsed_messages = []
            unreplied_set = set(unreplied_indices)
            for pos, raw in enumerate(raw_messages):
                if raw["type"] == "system":
                    parsed_messages.append(
                        {"type": "system", "content": raw["content"]}
                    )
                    continue
                content = raw["content"]
                attachment_path = None
                link_url = None
                if pos in unreplied_set and raw["_item"] is not None:
                    if content.startswith("[语音]"):
                        content = await _get_audio_text(
                            raw["_item"],
                            raw["sender"],
                            contact,
                            raw["_idx"],
                            window,
                            window_ctrl,
                        )
                    elif _detect_link_message(content):
                        # 链接消息：获取 URL
                        link_url = await _get_link_url(
                            raw["_item"],
                            window,
                            input_sim,
                            window_ctrl,
                            message_list=message_list,
                        )
                        if link_url:
                            content = f"""
                            [链接] {link_url}
                            如果链接是一般网页，调用fetch_web_fetch工具解析。
                            如果网页是微信公众号信息或者设置有反爬虫机制，调用 crawl_mcp_crawl_wechat_article 工具解析。
                            解析时可以配合调用 playwright_mcp_* 系列工具来辅助完成，禁止使用 chrome_devtools_mcp_* 或 BochaAISearch_* 等工具。
                            """
                    elif _detect_attachment_type(content) and raw["type"] == "received":
                        att = await _get_attachment_content(
                            raw["_item"],
                            raw["sender"],
                            contact,
                            raw["_idx"],
                            content,
                            window,
                            input_sim,
                            window_ctrl,
                            message_list=message_list,
                        )
                        content = att["content"]
                        attachment_path = att["attachment_path"]
                msg_entry = {
                    "type": raw["type"],
                    "sender": raw["sender"],
                    "content": content,
                }
                if attachment_path:
                    msg_entry["attachment_path"] = attachment_path
                if link_url:
                    msg_entry["link_url"] = link_url
                parsed_messages.append(msg_entry)

            # 从 parsed_messages 中提取未回复消息
            unreplied_messages = []
            for msg in reversed(parsed_messages):
                if msg["type"] == "system":
                    continue
                if msg["type"] == "sent":
                    break
                entry = {
                    "sender": msg["sender"],
                    "type": msg["type"],
                    "content": msg["content"],
                }
                if "attachment_path" in msg:
                    entry["attachment_path"] = msg["attachment_path"]
                if "link_url" in msg:
                    entry["link_url"] = msg["link_url"]
                unreplied_messages.insert(0, entry)

            # ═══════════════════════════════════════════════════════════
            # 历史轮次处理：加载已有历史 + 必要时向上滚动补充上下文
            # ═══════════════════════════════════════════════════════════
            history_data = _load_wechat_history(contact)
            previous_rounds = history_data.get("rounds", [])

            # 判断是否需要从微信窗口向上滚动加载更早消息：
            # 1. 文件历史轮次不足5轮
            # 2. 文件历史与当前窗口消息不连续（期间发生了未被监控的对话）
            has_gap = _has_continuity_gap(previous_rounds, parsed_messages)
            needs_scroll = len(previous_rounds) < _MAX_HISTORY_ROUNDS or has_gap

            if needs_scroll:
                if len(previous_rounds) < _MAX_HISTORY_ROUNDS:
                    ctx.info(
                        f"历史轮次不足（{len(previous_rounds)}/{_MAX_HISTORY_ROUNDS}），"
                        f"向上滚动加载更早消息..."
                    )
                else:
                    ctx.info(
                        f"文件历史轮次已满（{len(previous_rounds)}/{_MAX_HISTORY_ROUNDS}），"
                        f"但与当前窗口消息不连续，向上滚动加载缺失的上下文..."
                    )
                await _scroll_chat_up(message_list, input_sim, times=4)
                await asyncio.sleep(0.5)

                # 重新扫描可见消息，只采集文本元数据（不触发附件解析）
                additional_messages = []
                for item in message_list.children():
                    try:
                        if item.element_info.control_type != "ListItem":
                            continue
                        title = item.window_text()
                        if _is_system_divider(title):
                            continue
                        children = item.children()
                        if not children:
                            continue
                        first_child = children[0]
                        if first_child.element_info.control_type == "Text":
                            additional_messages.append(
                                {
                                    "type": "system",
                                    "content": title,
                                }
                            )
                            continue
                        if first_child.element_info.control_type != "Pane":
                            continue
                        pane_children = first_child.children()
                        if not pane_children:
                            continue
                        sender = ""
                        msg_type = "received"
                        is_voice = _is_voice_message(item)
                        normalized_content = "[语音]" if is_voice else title
                        if pane_children[0].element_info.control_type == "Button":
                            sender = pane_children[0].window_text()
                            msg_type = "received"
                        elif pane_children[-1].element_info.control_type == "Button":
                            sender = pane_children[-1].window_text()
                            if contact == "文件传输助手":
                                msg_type = (
                                    "sent"
                                    if (
                                        not is_voice
                                        and normalized_content.startswith(
                                            WECHAT_AI_REPLY_PREFIX
                                        )
                                    )
                                    else "received"
                                )
                            else:
                                msg_type = "sent"
                        additional_messages.append(
                            {
                                "type": msg_type,
                                "sender": sender,
                                "content": normalized_content,
                            }
                        )
                    except Exception:
                        continue

                # 去重合并：additional_messages（更旧） + parsed_messages（当前窗口）
                full_messages = _deduplicate_messages(
                    additional_messages, parsed_messages
                )
            else:
                full_messages = parsed_messages

            # 将完整消息拆分为轮次，保存已完成的轮次到历史文件
            all_rounds = _split_messages_into_rounds(full_messages)

            # 排除最后一轮未完成的轮次（只有 received 没有 sent 回复的轮次）
            completed_rounds = list(all_rounds)
            if completed_rounds:
                last_round = completed_rounds[-1]
                has_sent = any(m.get("type") == "sent" for m in last_round)
                if not has_sent:
                    completed_rounds.pop()

            # 合并文件历史轮次与窗口新读取的轮次
            # 边界去重：窗口轮次中与文件尾部重叠的轮次（相同消息）会被移除
            deduped_completed = _deduplicate_boundary_rounds(
                previous_rounds, completed_rounds
            )
            all_completed_rounds = previous_rounds + deduped_completed
            _save_wechat_history(contact, all_completed_rounds)

            # 最终返回的历史轮次（最近5轮）
            final_previous_rounds = (
                all_completed_rounds[-_MAX_HISTORY_ROUNDS:]
                if all_completed_rounds
                else []
            )

            # 将监控结果添加到列表中
            # 即使没有未回复消息，只要处理过历史数据也返回上下文
            if unreplied_messages or final_previous_rounds:
                results.append(
                    {
                        "chat_name": contact,
                        "messages": unreplied_messages,
                        "history": parsed_messages,
                        "previous_rounds": final_previous_rounds,
                    }
                )

        return json.dumps(results, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"


@register_tool()
async def get_wechat_messages(
    chat_name: str,
    count: int,
    ctx: Context,
) -> str:
    """Get chat messages from a WeChat contact or group.

    This tool automates the process of reading chat messages via WeChat by:
    1. Waking up WeChat using global hotkey (Ctrl+Alt+W)
    2. Finding and activating the WeChat window
    3. Using the search box (Ctrl+F) to find the contact
    4. Getting the UI element tree of the window
    5. Parsing the chat messages from the UI tree

    IMPORTANT:
    1. [图片], [文件], [视频], [语音] are ALL messages. count=1 returns the single
       latest message regardless of type.
    2. Set count to EXACTLY what the user asked for: "last message" → count=1,
       "last N messages" → count=N. Do NOT guess a larger number.

    Args:
        chat_name: The name of the contact or group to get messages from
        count: Number of latest messages to retrieve.
            1 = only the single last message (recommended: just check the returned
                JSON to see its type — if it's not what you need, call again with a
                slightly larger count like 3 or 5).
            0 = all visible messages (⚠️ SLOW — only use for full history tasks).
            N = the last N messages.
        ctx: MCP context

    Returns:
        JSON string containing the chat messages. Each message has fields:
        type (sent/received/system), sender, content, and optionally attachment_path.
        Returns "[]" if the last message was sent by you (not by the contact).
    """
    import json

    try:
        components = get_windows_components()
        window_ctrl = components["window_controller"]
        input_sim = components["input_simulator"]
        ui_auto = components["ui_automation"]

        ctx.info(f"Starting to get messages from '{chat_name}' via WeChat")

        # Step 1: Wake up WeChat
        ctx.info("Waking up WeChat...")
        input_sim.keyboard_hotkey("ctrl", "alt", "w")
        await asyncio.sleep(1.5)  # Wait for window to appear

        # Find WeChat window
        hwnd = _find_wechat_window(window_ctrl)
        if not hwnd:
            # Try one more time with a longer wait
            ctx.info("WeChat window not found, trying again...")
            input_sim.keyboard_hotkey("ctrl", "alt", "w")
            await asyncio.sleep(2.0)
            hwnd = _find_wechat_window(window_ctrl)

            if not hwnd:
                return "Error: Could not find WeChat window. Please make sure WeChat is running."

        # Activate window
        ctx.info("Activating WeChat window...")
        window_ctrl.set_state(hwnd, "activate")
        await asyncio.sleep(0.5)

        # Step 2: Search for contact
        ctx.info(f"Searching for contact: {chat_name}")
        input_sim.keyboard_hotkey("ctrl", "f")
        await asyncio.sleep(0.5)

        # Paste contact name
        input_sim.clipboard_set_and_paste(chat_name)
        await asyncio.sleep(1.0)  # Wait for search results

        # Enter chat
        input_sim.keyboard_hotkey("enter")
        await asyncio.sleep(1.0)  # Wait for chat history to load

        # Step 3: Get UI element tree
        ctx.info("Getting UI element tree...")
        ui_auto.connect(str(hwnd))
        window = ui_auto._window

        if not window:
            return "Error: Could not connect to WeChat UI."

        try:
            message_list = window.child_window(title="消息", control_type="List")
            if not message_list.exists():
                return "Error: Could not find message list."
        except Exception as e:
            return f"Error finding message list: {str(e)}"

        # Step 4: 先滚动到底部，确保最新消息可见
        ctx.info("Scrolling to bottom of chat...")
        await _scroll_to_bottom(message_list, input_sim)

        # Step 5: 从底部收集消息元数据
        # count=0: 收集全部消息（从上到下）；count>0: 只从底部收集需要的条数（从下到上）
        all_children = list(message_list.children())
        need_more = count > 0
        # count=0 时从上到下遍历全部；count>0 时从底部向上只收集需要的条数
        children_iter = reversed(all_children) if need_more else all_children
        ctx.info(
            f"Parsing chat messages ({'bottom-up, up to ' + str(count) if need_more else 'all'})..."
        )
        raw_messages = []

        for item in children_iter:
            try:
                if item.element_info.control_type != "ListItem":
                    continue

                title = item.window_text()
                if not title or _is_system_divider(title):
                    continue

                children = item.children()
                if not children:
                    continue

                first_child = children[0]
                if first_child.element_info.control_type == "Text":
                    if not need_more:
                        raw_messages.append(
                            {
                                "type": "system",
                                "content": title,
                                "_item": None,
                            }
                        )
                    continue
                elif first_child.element_info.control_type == "Pane":
                    pane_children = first_child.children()
                    if not pane_children:
                        continue

                    sender = ""
                    msg_type = "received"

                    if pane_children[0].element_info.control_type == "Button":
                        sender = pane_children[0].window_text()
                        if chat_name == "文件传输助手":
                            if title.startswith(WECHAT_AI_REPLY_PREFIX):
                                msg_type = "sent"
                            else:
                                msg_type = "received"
                        else:
                            msg_type = "received"
                    elif pane_children[-1].element_info.control_type == "Button":
                        sender = pane_children[-1].window_text()
                        if chat_name == "文件传输助手":
                            if title.startswith(WECHAT_AI_REPLY_PREFIX):
                                msg_type = "sent"
                            else:
                                msg_type = "received"
                        else:
                            msg_type = "sent"

                    is_attachment = _detect_attachment_type(title) is not None
                    is_voice = title.startswith("[语音]")

                    raw_messages.append(
                        {
                            "type": msg_type,
                            "sender": sender,
                            "content": title,
                            "_item": item,
                            "_is_attachment": is_attachment,
                            "_is_voice": is_voice,
                        }
                    )

                    # count>0 时收集够了就停止
                    if need_more and len(raw_messages) >= count:
                        break
            except Exception:
                continue

        # 从底部反向遍历的，翻转回正常顺序（旧→新）
        if need_more:
            raw_messages.reverse()

        if not raw_messages:
            input_sim.keyboard_hotkey("esc")
            return "[]"

        # 确定需要处理附件（保存/解析）的消息索引范围
        if count == 0:
            # count=0 时不处理全部附件（会破坏UI树），只处理最近20条收到的消息
            process_indices = set()
            limit = 20
            for i in range(len(raw_messages) - 1, -1, -1):
                raw = raw_messages[i]
                if raw["type"] != "system" and raw["type"] != "sent":
                    process_indices.add(i)
                    limit -= 1
                    if limit <= 0:
                        break
        elif count == 1:
            # 只处理最后一条非sent消息
            process_indices = set()
            for i in range(len(raw_messages) - 1, -1, -1):
                raw = raw_messages[i]
                if raw["type"] != "system" and raw["type"] != "sent":
                    process_indices.add(i)
                    break
        else:
            # 只处理最后 count 条非system消息
            process_indices = set()
            needed = count
            for i in range(len(raw_messages) - 1, -1, -1):
                raw = raw_messages[i]
                if raw["type"] != "system":
                    process_indices.add(i)
                    needed -= 1
                    if needed <= 0:
                        break

        # Step 5: 第二遍——仅对需要处理的消息触发附件保存（语音/图片/文件）
        ctx.info(f"Processing attachments for {len(process_indices)} messages...")
        messages = []

        for pos, raw in enumerate(raw_messages):
            if raw["type"] == "system":
                messages.append({"type": "system", "content": raw["content"]})
                continue

            content = raw["content"]
            attachment_path = None
            item = raw["_item"]

            if pos in process_indices and item is not None:
                msg_idx = pos
                if raw.get("_is_voice"):
                    content = await _get_audio_text(
                        item,
                        raw["sender"],
                        chat_name,
                        msg_idx,
                        window,
                        window_ctrl,
                    )
                elif raw.get("_is_attachment") and raw["type"] == "received":
                    # count=1 场景强制刷新缓存，确保获取的是最新消息而非旧缓存
                    att = await _get_attachment_content(
                        item,
                        raw["sender"],
                        chat_name,
                        msg_idx,
                        raw["content"],
                        window,
                        input_sim,
                        window_ctrl,
                        message_list=message_list,
                        force_refresh=(count == 1),
                    )
                    content = att["content"]
                    attachment_path = att["attachment_path"]

            msg_entry = {
                "type": raw["type"],
                "sender": raw["sender"],
                "content": content,
            }
            if attachment_path:
                msg_entry["attachment_path"] = attachment_path
            messages.append(msg_entry)

        # Step 6: Close window
        ctx.info("Closing WeChat window...")
        input_sim.keyboard_hotkey("esc")

        # 根据 count 返回结果
        if count == 0:
            return json.dumps(messages, ensure_ascii=False)
        elif count == 1:
            last_msg = messages[-1]
            if last_msg.get("type") == "sent":
                return "[]"
            return json.dumps([last_msg], ensure_ascii=False)
        else:
            return json.dumps(messages[-count:], ensure_ascii=False)

    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"

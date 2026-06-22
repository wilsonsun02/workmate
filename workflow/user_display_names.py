"""Map sys_users.username to page display name (sys_users.name)."""

from __future__ import annotations

import re
from typing import Dict


def build_username_display_map() -> Dict[str, str]:
    """Return {username: display_name} only where display_name differs from username."""
    from admin_api.services.user_service import UserService

    out: Dict[str, str] = {}
    for user in UserService.get_users():
        username = str(user.get("username") or "").strip()
        if not username:
            continue
        raw_name = str(user.get("name_raw") or "").strip()
        display = raw_name or str(user.get("name") or "").strip() or username
        if display and display != username:
            out[username] = display
    return out


# Do not replace username inside paths, ids, or technical tokens.
_USERNAME_BOUNDARY_BEFORE = r"(?<![\w/.\\@=\-])"
_USERNAME_BOUNDARY_AFTER = r"(?![\w/.\\\-])"


def apply_display_names_to_text(text: str) -> str:
    """
    Replace login usernames with sys_users.name in assistant-facing text
    (tables, prose summaries like「在线 2 人 (qiuhao、leizhen）」等).
    """
    if not text or not str(text).strip():
        return text or ""

    name_map = build_username_display_map()
    if not name_map:
        return text

    result = str(text)
    for username, display in sorted(name_map.items(), key=lambda item: -len(item[0])):
        result = result.replace(f"**{username}**", f"**{display}**")
        result = re.sub(
            rf"{_USERNAME_BOUNDARY_BEFORE}{re.escape(username)}(?=（你）)",
            display,
            result,
        )
        result = re.sub(
            rf"\|\s*([🟢⚪]?\s*\|?\s*)\*?\*?{re.escape(username)}\*?\*?（你）?",
            lambda m: m.group(0).replace(username, display),
            result,
        )
        result = re.sub(
            rf"{_USERNAME_BOUNDARY_BEFORE}{re.escape(username)}(?=\s*\|)",
            display,
            result,
        )
        # Prose lists: (qiuhao、leizhen), qiuhao、leizhen, qiuhao, leizhen
        result = re.sub(
            rf"{_USERNAME_BOUNDARY_BEFORE}{re.escape(username)}{_USERNAME_BOUNDARY_AFTER}",
            display,
            result,
        )
    return result

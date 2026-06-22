import re


class CommandParser:
    """指令解析器"""

    COMMAND_PATTERNS = {
        "execute": [r"执行[任务:]?\s*(.+)", r"运行[任务:]?\s*(.+)", r"做\s+(.+)"],
        "query": [r"查询[状态:]?", r"状态", r"列表"],
        "help": [r"帮助", r"help", r"命令"],
    }

    def parse(self, content: str) -> dict:
        """解析用户指令"""
        content = content.strip()
        for cmd, patterns in self.COMMAND_PATTERNS.items():
            for pattern in patterns:
                match = re.match(pattern, content)
                if match:
                    return {"command": cmd, "params": match.groups(), "raw": content}
        return {"command": "execute", "params": (content,), "raw": content}

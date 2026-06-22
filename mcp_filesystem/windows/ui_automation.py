"""UI automation controller component for Windows automation."""

import time
from typing import Dict, Optional, Any

# Try to import pywinauto
try:
    import pywinauto
    from pywinauto.application import Application
    from pywinauto.findwindows import ElementNotFoundError
except ImportError:
    pywinauto = None
    Application = None
    ElementNotFoundError = Exception

try:
    import win32gui as _win32gui
except ImportError:
    _win32gui = None

from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)

# Windows 系统对话框常见元素的 automation_id 映射表
# 这些 ID 在不同系统语言下保持稳定，比 title 更可靠
_SYSTEM_ELEMENT_IDS: Dict[str, str] = {
    "文件名": "1001",
    "file name": "1001",
    "保存": "1",
    "save": "1",
    "取消": "2",
    "cancel": "2",
    "打开": "1",
    "open": "1",
    "文件类型": "1136",
    "file type": "1136",
}


class UIAutomationController:
    """UI automation controller - handles UI element interaction."""

    def __init__(self):
        """Initialize UI automation controller."""
        self._check_dependencies()
        self._app: Optional[Application] = None
        self._window = None

    def _check_dependencies(self):
        """Check if required dependencies are installed."""
        if pywinauto is None:
            logger.warning(
                "pywinauto not installed. UI automation features will be unavailable."
            )

    def connect(self, window: str) -> bool:
        """Connect to an application window.

        Args:
            window: Window title or handle

        Returns:
            bool: Success
        """
        if not pywinauto:
            return False

        try:
            # 1. 如果传入的是数字句柄，直接用 Desktop 获取该句柄的窗口包装器
            # 比 Application.connect().top_window() 更精确，不会返回错误的顶层窗口
            if str(window).isdigit():
                desktop = pywinauto.Desktop(backend="uia")
                self._window = desktop.window(handle=int(window))
                if self._window.exists():
                    return True
                return False

            # 2. 尝试通过标题连接（适用于独立进程的主窗口）
            try:
                self._app = Application(backend="uia").connect(title_re=window)
                if self._app:
                    try:
                        self._window = self._app.window(title_re=window)
                        if not self._window.exists():
                            self._window = self._app.top_window()
                    except Exception:
                        self._window = self._app.top_window()
                    return True
            except ElementNotFoundError:
                pass

            # 3. 使用 win32gui 枚举所有窗口查找句柄（能找到对话框等子窗口）
            if _win32gui:
                hwnd = None

                def _enum_callback(h, _):
                    nonlocal hwnd
                    if hwnd:
                        return
                    if _win32gui.IsWindowVisible(h):
                        title = _win32gui.GetWindowText(h)
                        if window.lower() in title.lower():
                            hwnd = h

                _win32gui.EnumWindows(_enum_callback, None)

                if hwnd:
                    self._app = Application(backend="uia").connect(handle=hwnd)
                    if self._app:
                        self._window = self._app.top_window()
                        return True

            # 4. 最后尝试 Desktop 全局查找
            try:
                desktop = pywinauto.Desktop(backend="uia")
                self._window = desktop.window(title_re=window)
                if self._window.exists():
                    return True
            except Exception:
                pass

            return False
        except Exception as e:
            logger.error(f"Error connecting to window {window}: {e}")
            return False

    def find_element(self, criteria: Dict[str, Any]) -> Optional[Any]:
        """Find a UI element using multi-strategy fallback.

        Strategy order:
        1. Direct search by title/automation_id/control_type
        2. Fallback to known system dialog automation_id mapping
        3. Deep descendants search

        Args:
            criteria: Dictionary with search criteria

        Returns:
            UI element wrapper or None
        """
        if not self._window:
            return None

        try:
            kwargs = {}
            if "element_name" in criteria and criteria["element_name"]:
                kwargs["title"] = criteria["element_name"]
            if "automation_id" in criteria and criteria["automation_id"]:
                kwargs["auto_id"] = criteria["automation_id"]
            if "control_type" in criteria and criteria["control_type"]:
                kwargs["control_type"] = criteria["control_type"]

            if not kwargs:
                return self._window

            # 策略1：直接按条件查找
            element = self._window.child_window(**kwargs)
            if element.exists():
                return element

            # 策略2：title 找不到时，查映射表获取 automation_id 重试
            if "title" in kwargs and "auto_id" not in kwargs:
                mapped_id = _SYSTEM_ELEMENT_IDS.get(kwargs["title"].lower())
                if mapped_id:
                    fallback_kwargs = {k: v for k, v in kwargs.items() if k != "title"}
                    fallback_kwargs["auto_id"] = mapped_id
                    element = self._window.child_window(**fallback_kwargs)
                    if element.exists():
                        logger.info(
                            f"Found element via automation_id '{mapped_id}' for title '{kwargs['title']}'"
                        )
                        return element

            # 策略3：遍历所有后代元素做精确/模糊匹配（对 title 和 auto_id 都适用）
            search_title = kwargs.get("title", "").lower()
            search_auto_id = kwargs.get("auto_id", "")
            if search_title or search_auto_id:
                for desc in self._window.descendants():
                    try:
                        if (
                            search_auto_id
                            and desc.element_info.automation_id == search_auto_id
                        ):
                            logger.info(
                                f"Found element via descendants scan, auto_id='{search_auto_id}'"
                            )
                            return desc
                        if search_title and search_title in desc.window_text().lower():
                            logger.info(
                                f"Found element via descendants scan, title='{search_title}'"
                            )
                            return desc
                    except Exception:
                        continue

            return element
        except Exception as e:
            logger.error(f"Error finding element: {e}")
            return None

    def click(
        self, element: Any, button: str = "left", double_click: bool = False
    ) -> bool:
        """Click a UI element.

        Args:
            element: UI element wrapper
            button: Mouse button (left, right, middle)
            double_click: Whether to double click

        Returns:
            bool: Success
        """
        if not element:
            return False

        try:
            if double_click:
                element.double_click_input(button=button)
            else:
                element.click_input(button=button)
            return True
        except Exception as e:
            logger.error(f"Error clicking element: {e}")
            return False

    def input(self, element: Any, text: str, clear_first: bool = False) -> bool:
        """Input text into a UI element using multi-strategy fallback.

        Strategy order:
        1. set_edit_text (direct set, no keyboard simulation, most reliable)
        2. type_keys (keyboard simulation)

        Args:
            element: UI element wrapper
            text: Text to input
            clear_first: Whether to clear existing text

        Returns:
            bool: Success
        """
        if not element:
            return False

        try:
            if clear_first:
                try:
                    element.set_text("")
                except Exception:
                    element.click_input()
                    element.type_keys("^a{DELETE}")

            # 策略1：set_edit_text 直接设置文本，不依赖键盘模拟，对 UWP 应用更可靠
            try:
                element.set_edit_text(text)
                return True
            except Exception:
                pass

            # 策略2：type_keys 键盘模拟
            element.type_keys(text, with_spaces=True)
            return True
        except Exception as e:
            logger.error(f"Error inputting text: {e}")
            return False

    def wait(self, criteria: Dict[str, Any], timeout: int = 30) -> Optional[Any]:
        """Wait for a UI element to appear.

        Args:
            criteria: Search criteria
            timeout: Timeout in seconds

        Returns:
            UI element wrapper or None
        """
        if not self._window:
            return None

        start_time = time.time()
        while time.time() - start_time < timeout:
            element = self.find_element(criteria)
            if element and element.exists():
                return element
            time.sleep(0.5)

        return None

    def list_elements(self, window: str) -> list:
        """列出窗口所有后代元素的 automation_id、title、control_type，用于诊断。

        Args:
            window: 窗口标题或句柄

        Returns:
            list of dict: 每个元素的属性字典
        """
        if not self.connect(window):
            return []

        result = []
        try:
            for desc in self._window.descendants():
                try:
                    result.append(
                        {
                            "automation_id": desc.element_info.automation_id,
                            "title": desc.window_text(),
                            "control_type": desc.element_info.control_type,
                        }
                    )
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Error listing elements: {e}")
        return result

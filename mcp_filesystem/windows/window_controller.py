"""Window controller component for Windows automation."""

import time
from typing import Dict, Optional

# Try to import pywin32 modules
try:
    import win32gui
    import win32con
    import win32process
    import win32api
except ImportError:
    win32gui = None
    win32con = None
    win32process = None
    win32api = None

# Try to import psutil for process name resolution
try:
    import psutil
except ImportError:
    psutil = None

from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class WindowController:
    """Window controller component - handles window finding, state, and control."""

    def __init__(self):
        """Initialize window controller."""
        self._check_dependencies()

    def _check_dependencies(self):
        """Check if required dependencies are installed."""
        if win32gui is None:
            logger.warning(
                "pywin32 not installed. Window control features will be unavailable."
            )

    def find(
        self,
        title: Optional[str] = None,
        class_name: Optional[str] = None,
        process_name: Optional[str] = None,
    ) -> Optional[int]:
        """Find a window handle based on criteria.

        Args:
            title: Window title (partial match)
            class_name: Window class name
            process_name: Process name owning the window

        Returns:
            Window handle (int) or None if not found
        """
        if not win32gui:
            return None

        found_hwnd = None

        def enum_windows_callback(hwnd, _):
            nonlocal found_hwnd
            if found_hwnd:
                return

            if not win32gui.IsWindowVisible(hwnd):
                return

            # Check title
            if title:
                window_text = win32gui.GetWindowText(hwnd)
                if not window_text or title.lower() not in window_text.lower():
                    return

            # Check class name
            if class_name:
                window_class = win32gui.GetClassName(hwnd)
                if not window_class or class_name.lower() != window_class.lower():
                    return

            # Check process name
            if process_name and psutil:
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    proc = psutil.Process(pid)
                    if process_name.lower() not in proc.name().lower():
                        return
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return

            found_hwnd = hwnd

        try:
            win32gui.EnumWindows(enum_windows_callback, None)
            return found_hwnd
        except Exception as e:
            logger.error(f"Error finding window: {e}")
            return None

    def get_state(self, hwnd: int) -> Dict:
        """Get window state.

        Args:
            hwnd: Window handle

        Returns:
            Dict with window state info
        """
        if not win32gui:
            return {"error": "pywin32 not installed"}

        try:
            if not win32gui.IsWindow(hwnd):
                return {"error": "Invalid window handle"}

            rect = win32gui.GetWindowRect(hwnd)
            placement = win32gui.GetWindowPlacement(hwnd)

            # placement[1] is showCmd
            state_map = {
                win32con.SW_SHOWNORMAL: "Normal",
                win32con.SW_SHOWMINIMIZED: "Minimized",
                win32con.SW_SHOWMAXIMIZED: "Maximized",
                win32con.SW_HIDE: "Hidden",
            }

            state = state_map.get(placement[1], "Unknown")
            if not win32gui.IsWindowVisible(hwnd):
                state = "Hidden"

            return {
                "title": win32gui.GetWindowText(hwnd),
                "class": win32gui.GetClassName(hwnd),
                "state": state,
                "visible": bool(win32gui.IsWindowVisible(hwnd)),
                "active": hwnd == win32gui.GetForegroundWindow(),
                "position": {"x": rect[0], "y": rect[1]},
                "size": {"width": rect[2] - rect[0], "height": rect[3] - rect[1]},
                "handle": hwnd,
            }
        except Exception as e:
            return {"error": str(e)}

    def set_state(self, hwnd: int, state: str) -> bool:
        """Set window state.

        Args:
            hwnd: Window handle
            state: Target state (activate, minimize, maximize, restore, hide, show, close)

        Returns:
            bool: Success
        """
        if not win32gui:
            return False

        try:
            if not win32gui.IsWindow(hwnd):
                return False

            state = state.lower()

            if state == "activate":
                # Restore if minimized
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

                # Bring to front using multiple strategies
                try:
                    # Strategy 1: Standard SetForegroundWindow
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    try:
                        # Strategy 2: ShowWindow + SetForegroundWindow
                        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                        win32gui.SetForegroundWindow(hwnd)
                    except Exception:
                        try:
                            # Strategy 3: Simulate Alt key press to allow foreground change
                            # This is a known trick to bypass foreground lock timeout
                            import ctypes

                            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)  # Alt down
                            win32gui.SetForegroundWindow(hwnd)
                            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)  # Alt up
                        except Exception:
                            # Strategy 4: SwitchToThisWindow (undocumented but effective)
                            try:
                                ctypes.windll.user32.SwitchToThisWindow(hwnd, True)
                            except Exception:
                                pass

                # Verify if activation succeeded
                time.sleep(0.1)
                active_hwnd = win32gui.GetForegroundWindow()
                if active_hwnd != hwnd:
                    # Final attempt: Minimize then Restore to force focus
                    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    try:
                        win32gui.SetForegroundWindow(hwnd)
                    except:
                        pass

            elif state == "minimize":
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)

            elif state == "maximize":
                win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)

            elif state == "restore":
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

            elif state == "hide":
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE)

            elif state == "show":
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

            elif state == "close":
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)

            else:
                logger.warning(f"Unknown window state: {state}")
                return False

            return True

        except Exception as e:
            logger.error(f"Error setting window state: {e}")
            return False

    def close(self, hwnd: int, force: bool = False) -> bool:
        """Close window.

        Args:
            hwnd: Window handle
            force: Whether to force close (terminate process)

        Returns:
            bool: Success
        """
        if not win32gui:
            return False

        try:
            if force and win32process and psutil:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    proc = psutil.Process(pid)
                    proc.kill()
                    return True
                except Exception:
                    pass

            # Normal close
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            return True

        except Exception as e:
            logger.error(f"Error closing window: {e}")
            return False

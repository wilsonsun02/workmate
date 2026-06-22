"""Input simulator component for Windows automation."""

import time
from typing import Optional, List

# Try to import pynput
try:
    from pynput import mouse, keyboard
    from pynput.mouse import Button
    from pynput.keyboard import Key
except ImportError:
    mouse = None
    keyboard = None
    Button = None
    Key = None

try:
    import win32clipboard
    import win32con
except ImportError:
    win32clipboard = None
    win32con = None

from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class InputSimulator:
    """Input simulator - handles mouse and keyboard simulation."""

    def __init__(self):
        """Initialize input simulator."""
        self._check_dependencies()
        if mouse and keyboard:
            self._mouse_controller = mouse.Controller()
            self._keyboard_controller = keyboard.Controller()
        else:
            self._mouse_controller = None
            self._keyboard_controller = None

    def _check_dependencies(self):
        """Check if required dependencies are installed."""
        if mouse is None or keyboard is None:
            logger.warning(
                "pynput not installed. Input simulation features will be unavailable."
            )
        if win32clipboard is None:
            logger.warning(
                "win32clipboard not installed. Clipboard features will be unavailable."
            )

    def mouse_click(
        self, x: int, y: int, button: str = "left", double_click: bool = False
    ) -> bool:
        """Click mouse at coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            button: Mouse button (left, right, middle)
            double_click: Whether to double click

        Returns:
            bool: Success
        """
        if not self._mouse_controller:
            return False

        try:
            # Move to position
            self._mouse_controller.position = (x, y)
            time.sleep(0.1)

            # Map button string to Button object
            btn_map = {
                "left": Button.left,
                "right": Button.right,
                "middle": Button.middle,
            }
            btn = btn_map.get(button.lower(), Button.left)

            # Click
            count = 2 if double_click else 1
            self._mouse_controller.click(btn, count)

            return True
        except Exception as e:
            logger.error(f"Error clicking mouse: {e}")
            return False

    def mouse_move(self, x: int, y: int, duration: float = 0.0) -> bool:
        """Move mouse to coordinates.

        Args:
            x: Target X coordinate
            y: Target Y coordinate
            duration: Movement duration in seconds (0 for instant)

        Returns:
            bool: Success
        """
        if not self._mouse_controller:
            return False

        try:
            if duration <= 0:
                self._mouse_controller.position = (x, y)
            else:
                # Smooth movement
                start_x, start_y = self._mouse_controller.position
                steps = int(duration * 60)  # 60 fps
                if steps < 1:
                    steps = 1

                dx = (x - start_x) / steps
                dy = (y - start_y) / steps

                for i in range(steps):
                    self._mouse_controller.position = (
                        start_x + dx * (i + 1),
                        start_y + dy * (i + 1),
                    )
                    time.sleep(duration / steps)

                # Ensure final position is exact
                self._mouse_controller.position = (x, y)

            return True
        except Exception as e:
            logger.error(f"Error moving mouse: {e}")
            return False

    def mouse_drag(
        self, x1: int, y1: int, x2: int, y2: int, button: str = "left"
    ) -> bool:
        """Drag mouse from start to end coordinates.

        Args:
            x1: Start X
            y1: Start Y
            x2: End X
            y2: End Y
            button: Mouse button to hold

        Returns:
            bool: Success
        """
        if not self._mouse_controller:
            return False

        try:
            # Move to start
            self._mouse_controller.position = (x1, y1)
            time.sleep(0.1)

            # Map button
            btn_map = {
                "left": Button.left,
                "right": Button.right,
                "middle": Button.middle,
            }
            btn = btn_map.get(button.lower(), Button.left)

            # Press button
            self._mouse_controller.press(btn)
            time.sleep(0.1)

            # Move to end (smoothly)
            self.mouse_move(x2, y2, duration=0.5)
            time.sleep(0.1)

            # Release button
            self._mouse_controller.release(btn)

            return True
        except Exception as e:
            logger.error(f"Error dragging mouse: {e}")
            return False

    def keyboard_type(self, text: str) -> bool:
        """Type text.

        Args:
            text: Text to type

        Returns:
            bool: Success
        """
        if not self._keyboard_controller:
            return False

        try:
            self._keyboard_controller.type(text)
            return True
        except Exception as e:
            logger.error(f"Error typing text: {e}")
            return False

    def keyboard_hotkey(self, *keys: str) -> bool:
        """Press hotkey combination.

        Args:
            keys: List of keys (e.g., "ctrl", "c")

        Returns:
            bool: Success
        """
        if not self._keyboard_controller:
            return False

        try:
            # Map key strings to Key objects
            key_map = {
                "ctrl": Key.ctrl,
                "shift": Key.shift,
                "alt": Key.alt,
                "enter": Key.enter,
                "esc": Key.esc,
                "tab": Key.tab,
                "backspace": Key.backspace,
                "delete": Key.delete,
                "up": Key.up,
                "down": Key.down,
                "left": Key.left,
                "right": Key.right,
                "home": Key.home,
                "end": Key.end,
                "page_up": Key.page_up,
                "page_down": Key.page_down,
                "f1": Key.f1,
                "f2": Key.f2,
                "f3": Key.f3,
                "f4": Key.f4,
                "f5": Key.f5,
                "f6": Key.f6,
                "f7": Key.f7,
                "f8": Key.f8,
                "f9": Key.f9,
                "f10": Key.f10,
                "f11": Key.f11,
                "f12": Key.f12,
            }

            parsed_keys = []
            for k in keys:
                k_lower = k.lower()
                if k_lower in key_map:
                    parsed_keys.append(key_map[k_lower])
                elif len(k) == 1:
                    parsed_keys.append(k)
                else:
                    logger.warning(f"Unknown key: {k}")
                    return False

            # Press keys in order
            for k in parsed_keys:
                self._keyboard_controller.press(k)

            time.sleep(0.1)

            # Release keys in reverse order
            for k in reversed(parsed_keys):
                self._keyboard_controller.release(k)

            return True
        except Exception as e:
            logger.error(f"Error pressing hotkey: {e}")
            return False

    def clipboard_set_and_paste(self, text: str) -> bool:
        """Set text to clipboard and simulate Ctrl+V to paste it.

        This is useful for bypassing input method editors (IME) when typing paths or special characters.

        Args:
            text: Text to paste

        Returns:
            bool: Success
        """
        if not win32clipboard or not self._keyboard_controller:
            return False

        try:
            # Set text to clipboard
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()

            # Wait a tiny bit for clipboard to be ready
            time.sleep(0.1)

            # Simulate Ctrl+V
            return self.keyboard_hotkey("ctrl", "v")
        except Exception as e:
            logger.error(f"Error in clipboard_set_and_paste: {e}")
            try:
                win32clipboard.CloseClipboard()
            except:
                pass
            return False

    def clipboard_read(self) -> Optional[str]:
        """Read text from clipboard.

        Returns:
            Clipboard text or None if failed/empty
        """
        if not win32clipboard:
            return None

        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    return text
                elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_TEXT):
                    text = win32clipboard.GetClipboardData(win32con.CF_TEXT)
                    return text.decode("gbk", errors="ignore")
                return None
            finally:
                win32clipboard.CloseClipboard()
        except Exception as e:
            logger.error(f"Error reading clipboard: {e}")
            try:
                win32clipboard.CloseClipboard()
            except:
                pass
            return None

    def clipboard_copy_file(self, file_paths: List[str]) -> bool:
        """Copy files to clipboard (CF_HDROP format).

        This allows pasting files directly into applications like WeChat, Explorer, etc.

        Args:
            file_paths: List of absolute file paths

        Returns:
            bool: Success
        """
        if not win32clipboard:
            return False

        try:
            import struct
            import os

            # Verify files exist
            valid_paths = [p for p in file_paths if os.path.exists(p)]
            if not valid_paths:
                logger.error("No valid files to copy")
                return False

            # Create DROPFILES structure
            # typedef struct _DROPFILES {
            #   DWORD pFiles; // offset to file list
            #   POINT pt;     // drop point (not used here)
            #   BOOL fNC;     // is non-client area (not used here)
            #   BOOL fWide;   // is Unicode
            # } DROPFILES, *LPDROPFILES;

            offset = struct.calcsize("5I")
            files = ("\0".join(valid_paths) + "\0\0").encode("utf-16le")
            data = struct.pack("5I", offset, 0, 0, 0, 1) + files

            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_HDROP, data)
            win32clipboard.CloseClipboard()
            return True
        except Exception as e:
            logger.error(f"Error copying files to clipboard: {e}")
            try:
                win32clipboard.CloseClipboard()
            except:
                pass
            return False

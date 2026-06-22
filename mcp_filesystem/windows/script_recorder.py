"""Script recorder component for Windows automation."""

import json
import time
from typing import Dict, List, Optional, Any

# Try to import pynput
try:
    from pynput import mouse, keyboard
except ImportError:
    mouse = None
    keyboard = None

from fastmcp.utilities.logging import get_logger
from .input_simulator import InputSimulator

logger = get_logger(__name__)


class ScriptRecorder:
    """Script recorder - records and plays back user actions."""

    def __init__(self):
        """Initialize script recorder."""
        self._check_dependencies()
        self._is_recording = False
        self._actions: List[Dict[str, Any]] = []
        self._start_time: Optional[float] = None
        self._mouse_listener = None
        self._keyboard_listener = None
        self._input_simulator = InputSimulator()

    def _check_dependencies(self):
        """Check if required dependencies are installed."""
        if mouse is None or keyboard is None:
            logger.warning(
                "pynput not installed. Script recording features will be unavailable."
            )

    def start(self) -> bool:
        """Start recording.

        Returns:
            bool: Success
        """
        if not mouse or not keyboard:
            return False

        if self._is_recording:
            return False

        self._actions = []
        self._start_time = time.time()
        self._is_recording = True

        # Start listeners
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click, on_scroll=self._on_scroll
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )

        self._mouse_listener.start()
        self._keyboard_listener.start()

        logger.info("Recording started")
        return True

    def stop(self, save_path: Optional[str] = None) -> Dict[str, Any]:
        """Stop recording.

        Args:
            save_path: Path to save the script

        Returns:
            Dict with recording info
        """
        if not self._is_recording:
            return {"error": "Not recording"}

        self._is_recording = False

        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None

        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener = None

        duration = time.time() - (self._start_time or 0)

        result = {
            "success": True,
            "actions_count": len(self._actions),
            "duration": duration,
            "actions": self._actions,
        }

        if save_path:
            try:
                with open(save_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2)
                result["saved_to"] = save_path
            except Exception as e:
                result["save_error"] = str(e)

        logger.info(f"Recording stopped. {len(self._actions)} actions recorded.")
        return result

    def _record_action(self, action_type: str, **kwargs):
        """Record an action with timestamp."""
        if not self._is_recording:
            return

        timestamp = time.time() - (self._start_time or 0)
        action = {"type": action_type, "timestamp": timestamp, **kwargs}
        self._actions.append(action)

    def _on_click(self, x, y, button, pressed):
        if pressed:
            self._record_action(
                "mouse_click", x=x, y=y, button=str(button).replace("Button.", "")
            )

    def _on_scroll(self, x, y, dx, dy):
        self._record_action("mouse_scroll", x=x, y=y, dx=dx, dy=dy)

    def _on_press(self, key):
        try:
            key_char = key.char
        except AttributeError:
            key_char = str(key).replace("Key.", "")

        self._record_action("key_press", key=key_char)

    def _on_release(self, key):
        try:
            key_char = key.char
        except AttributeError:
            key_char = str(key).replace("Key.", "")

        self._record_action("key_release", key=key_char)

        # Stop recording on Ctrl+Shift+R (simplified check)
        # In a real implementation, we'd track modifier state

    def playback(
        self, script_path: str, speed: float = 1.0, repeat: int = 1
    ) -> Dict[str, Any]:
        """Playback a recorded script.

        Args:
            script_path: Path to script file
            speed: Playback speed multiplier
            repeat: Number of times to repeat

        Returns:
            Dict with playback result
        """
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            actions = data.get("actions", [])
            if not actions:
                return {"success": False, "error": "No actions in script"}

            logger.info(f"Playing back script: {script_path} ({len(actions)} actions)")

            for _ in range(repeat):
                start_time = time.time()

                for i, action in enumerate(actions):
                    # Calculate delay
                    target_time = action["timestamp"] / speed
                    current_time = time.time() - start_time

                    if target_time > current_time:
                        time.sleep(target_time - current_time)

                    # Execute action
                    self._execute_action(action)

            return {"success": True, "actions_played": len(actions) * repeat}

        except Exception as e:
            logger.error(f"Playback error: {e}")
            return {"success": False, "error": str(e)}

    def _execute_action(self, action: Dict[str, Any]):
        """Execute a single action."""
        action_type = action["type"]

        if action_type == "mouse_click":
            self._input_simulator.mouse_move(action["x"], action["y"])
            self._input_simulator.mouse_click(
                action["x"], action["y"], button=action["button"]
            )

        elif action_type == "key_press":
            # Simplified: just type for now, handling press/release properly requires more complex logic
            pass

        elif action_type == "key_release":
            # Simplified
            pass

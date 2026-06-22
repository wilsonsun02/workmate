"""Windows automation components for MCP filesystem server."""

from .process_manager import ProcessManager
from .window_controller import WindowController
from .ui_automation import UIAutomationController
from .input_simulator import InputSimulator
from .script_recorder import ScriptRecorder

__all__ = [
    "ProcessManager",
    "WindowController",
    "UIAutomationController",
    "InputSimulator",
    "ScriptRecorder",
]

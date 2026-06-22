"""Process manager component for Windows automation."""

import os
import time
import subprocess
from typing import Dict, List, Optional, Union, Any
from pathlib import Path

# Try to import psutil, but don't fail if not installed (for non-Windows dev environments)
try:
    import psutil
except ImportError:
    psutil = None

# Try to import pylnk for shortcut handling
try:
    import pylnk
except ImportError:
    pylnk = None

from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class ProcessManager:
    """Process manager component - handles application start, stop, and process info."""

    def __init__(self):
        """Initialize process manager."""
        self._check_dependencies()

    def _check_dependencies(self):
        """Check if required dependencies are installed."""
        if psutil is None:
            logger.warning(
                "psutil not installed. Process management features will be limited."
            )

    def start(
        self,
        target: str,
        mode: str = "process_name",
        wait_ready: bool = True,
        timeout: int = 30,
    ) -> Dict[str, Union[bool, str, int]]:
        """Start an application.

        Args:
            target: Target identifier (process name, path, or .lnk file)
            mode: Identification mode ("process_name", "path", "lnk")
            wait_ready: Whether to wait for the application to be ready
            timeout: Start timeout in seconds

        Returns:
            Dict with keys: success, name, pid, error
        """
        try:
            executable_path = target

            # Handle shortcut (.lnk) files
            if mode == "lnk" or target.lower().endswith(".lnk"):
                if not os.path.exists(target):
                    return {"success": False, "error": f"Shortcut not found: {target}"}

                # If pylnk is available, resolve the target
                if pylnk:
                    try:
                        lnk = pylnk.parse(target)
                        executable_path = lnk.path
                        logger.info(f"Resolved shortcut {target} to {executable_path}")
                    except Exception as e:
                        logger.warning(f"Failed to parse shortcut with pylnk: {e}")
                        # Fallback: let Windows handle the .lnk file
                        executable_path = target
                else:
                    # Let Windows handle the .lnk file
                    executable_path = target

            # Handle process name (try to find path or just run it)
            elif mode == "process_name":
                # If it's just a name like "notepad", subprocess.Popen usually handles it if in PATH
                # If it ends with .exe, use it as is
                if not target.lower().endswith(".exe"):
                    executable_path = f"{target}.exe"
                else:
                    executable_path = target

            logger.info(f"Starting application: {executable_path}")

            # Start the process
            process = subprocess.Popen(
                executable_path,
                shell=True if mode == "lnk" else False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            pid = process.pid
            name = Path(executable_path).name

            # Wait for process to be ready if requested
            if wait_ready and psutil:
                start_time = time.time()
                is_ready = False

                while time.time() - start_time < timeout:
                    try:
                        if not psutil.pid_exists(pid):
                            # Process might have spawned a child and exited (common with launchers)
                            # This is a simplified check; robust implementation would track children
                            break

                        proc = psutil.Process(pid)
                        if proc.status() == psutil.STATUS_RUNNING:
                            is_ready = True
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        break
                    time.sleep(0.5)

                if not is_ready:
                    logger.warning(
                        f"Process {pid} did not reach running state within {timeout}s"
                    )

            return {"success": True, "name": name, "pid": pid, "error": None}

        except Exception as e:
            logger.error(f"Failed to start application {target}: {e}")
            return {"success": False, "name": target, "pid": -1, "error": str(e)}

    def stop(
        self,
        target: str,
        force: bool = False,
        timeout: int = 10,
    ) -> Dict[str, Union[bool, str]]:
        """Stop an application.

        Args:
            target: Process name or PID (as string)
            force: Whether to force terminate
            timeout: Stop timeout in seconds

        Returns:
            Dict with keys: success, error
        """
        if not psutil:
            return {"success": False, "error": "psutil not installed"}

        try:
            target_pid = None
            if target.isdigit():
                target_pid = int(target)

            found = False
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if target_pid and proc.info["pid"] == target_pid:
                        self._kill_process(proc, force, timeout)
                        found = True
                        break
                    elif (
                        proc.info["name"]
                        and proc.info["name"].lower() == target.lower()
                    ):
                        self._kill_process(proc, force, timeout)
                        found = True
                        # Don't break, kill all instances with this name
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not found:
                return {"success": False, "error": f"Process not found: {target}"}

            return {"success": True, "error": None}

        except Exception as e:
            logger.error(f"Failed to stop application {target}: {e}")
            return {"success": False, "error": str(e)}

    def _kill_process(self, proc: Any, force: bool, timeout: int):
        """Helper to kill a process."""
        if force:
            proc.kill()
        else:
            proc.terminate()

        try:
            proc.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            if not force:
                logger.warning(f"Process {proc.pid} did not terminate, forcing kill")
                proc.kill()
                proc.wait(timeout=1)

    def list(
        self,
        filter_str: Optional[str] = None,
        include_system: bool = False,
    ) -> List[Dict]:
        """List running processes.

        Args:
            filter_str: Process name filter
            include_system: Whether to include system processes (simplified check)

        Returns:
            List of process info dictionaries
        """
        if not psutil:
            return []

        processes = []
        for proc in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_info", "create_time"]
        ):
            try:
                info = proc.info

                # Filter by name
                if filter_str and filter_str.lower() not in info["name"].lower():
                    continue

                # Simple system filter (skip common system processes if not requested)
                if not include_system:
                    system_procs = [
                        "system",
                        "registry",
                        "smss.exe",
                        "csrss.exe",
                        "wininit.exe",
                        "services.exe",
                        "lsass.exe",
                        "svchost.exe",
                    ]
                    if info["name"].lower() in system_procs:
                        continue

                # Format memory to MB
                memory_mb = round(info["memory_info"].rss / (1024 * 1024), 1)

                processes.append(
                    {
                        "name": info["name"],
                        "pid": info["pid"],
                        "cpu_percent": info["cpu_percent"],
                        "memory_mb": memory_mb,
                        "create_time": info["create_time"],
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return processes

    def get_info(self, target: str) -> Dict:
        """Get detailed process information.

        Args:
            target: Process name or PID

        Returns:
            Dict with process details
        """
        if not psutil:
            return {"error": "psutil not installed"}

        try:
            target_pid = None
            if target.isdigit():
                target_pid = int(target)

            target_proc = None
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if target_pid and proc.info["pid"] == target_pid:
                        target_proc = proc
                        break
                    elif (
                        proc.info["name"]
                        and proc.info["name"].lower() == target.lower()
                    ):
                        target_proc = proc
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not target_proc:
                return {"error": f"Process not found: {target}"}

            # Get detailed info
            with target_proc.oneshot():
                info = {
                    "name": target_proc.name(),
                    "pid": target_proc.pid,
                    "status": target_proc.status(),
                    "cpu_percent": target_proc.cpu_percent(interval=0.1),
                    "memory_mb": round(
                        target_proc.memory_info().rss / (1024 * 1024), 1
                    ),
                    "create_time": datetime.fromtimestamp(
                        target_proc.create_time()
                    ).isoformat(),
                    "exe": target_proc.exe(),
                    "cwd": target_proc.cwd(),
                    "cmdline": target_proc.cmdline(),
                    "username": target_proc.username(),
                }
                return info

        except Exception as e:
            return {"error": str(e)}


from datetime import datetime

"""同花顺期货通自动化工具

此模块提供操作同花顺期货通 (happ) 的完整自动化流程：
- 启动应用 -> 激活窗口 -> 输入合约 -> 切换K线
"""

import os
import time
from dotenv import load_dotenv

from ..paths import app_base_dir

PROJECT_ROOT = app_base_dir()
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from fastmcp import Context
from ..context import mcp, get_windows_components

ENABLE_HAPP_TOOLS = os.environ.get("MCP_ENABLE_HAPP_TOOLS", "true").lower() == "true"


def register_tool(*args, **kwargs):
    """Conditional tool registration decorator based on ENABLE_HAPP_TOOLS."""
    if ENABLE_HAPP_TOOLS:
        return mcp.tool(*args, **kwargs)
    else:

        def decorator(func):
            return func

        return decorator


# 同花顺期货通配置
HAPP_WINDOW_TITLE = os.environ.get("HAPP_WINDOW_TITLE", "同花顺期货通")
HAPP_PROCESS_NAME = os.environ.get("HAPP_PROCESS_NAME", "happ")


@register_tool()
async def happ_full_automation(
    contract_code: str = "AL2605", period: str = "M1", ctx: Context = None
) -> str:
    """同花顺期货通完整自动化流程

    依次执行：启动应用 -> 激活窗口 -> 输入合约 -> 切换K线

    Args:
        contract_code: 合约代码，如 "AL2605" (沪铝2605)
        period: K线周期，如 "M1"(1分钟), "M5"(5分钟), "M15"(15分钟), "D"(日线), "05"(分时)

    Returns:
        执行结果信息
    """
    try:
        components = get_windows_components()
        process_manager = components["process_manager"]
        window_controller = components["window_controller"]
        input_sim = components["input_simulator"]

        results = []

        # 调试信息
        results.append(
            f"调试信息: 窗口标题='{HAPP_WINDOW_TITLE}', 进程名='{HAPP_PROCESS_NAME}'"
        )

        # Step 1: 启动应用
        processes = process_manager.list()
        app_running = any(
            HAPP_PROCESS_NAME.lower() in p.get("name", "").lower() for p in processes
        )

        if not app_running:
            result = process_manager.start(
                HAPP_PROCESS_NAME, mode="process_name", wait_ready=True, timeout=30
            )
            if result.get("success"):
                results.append(f"✓ 启动应用成功 (PID: {result.get('pid')})")
                time.sleep(3)
            else:
                results.append(f"✗ 启动应用失败: {result.get('error')}")
                results.append(f"提示: 请确认进程名 '{HAPP_PROCESS_NAME}' 是否正确")
                return "\n".join(results)
        else:
            results.append("✓ 应用已在运行中")

        # Step 2: 激活窗口
        hwnd = window_controller.find(
            title=HAPP_WINDOW_TITLE, process_name=HAPP_PROCESS_NAME
        )
        if hwnd:
            # 先 restore（防止最小化状态），再 activate（置前台），最后 maximize（最大化全屏）
            window_controller.set_state(hwnd, "restore")
            time.sleep(0.3)
            window_controller.set_state(hwnd, "activate")
            time.sleep(0.4)
            window_controller.set_state(hwnd, "maximize")
            time.sleep(0.5)
            results.append(f"✓ 窗口已激活并最大化 (hwnd: {hwnd})")
        else:
            results.append(
                f"✗ 未找到窗口: 标题='{HAPP_WINDOW_TITLE}', 进程='{HAPP_PROCESS_NAME}'"
            )
            results.append("提示: 请确认窗口标题和进程名是否正确")
            return "\n".join(results)

        # Step 3: 切换大小写
        input_sim.keyboard_hotkey("capslock")
        time.sleep(0.3)

        # Step 4: 输入合约代码
        input_sim.keyboard_type(contract_code)
        time.sleep(0.5)
        input_sim.keyboard_hotkey("enter")
        time.sleep(2)
        results.append(f"✓ 已输入合约 '{contract_code}' 并确认")

        # Step 5: 切换K线周期
        if period == "05" or period == "分时":
            # 切换到分时图的特殊逻辑：先切换到1分钟K线，再按一次回车
            input_sim.keyboard_type("M1")
            time.sleep(0.5)
            input_sim.keyboard_hotkey("enter")
            time.sleep(1)
            input_sim.keyboard_hotkey("enter")
            time.sleep(1)
            results.append(f"✓ 已切换到分时图")
        else:
            # 正常的K线切换逻辑
            input_sim.keyboard_type(period)
            time.sleep(0.5)
            input_sim.keyboard_hotkey("enter")
            time.sleep(1)
            results.append(f"✓ 已切换到 {period} K线")

        return "\n".join(results)

    except Exception as e:
        return f"Error: {type(e).__name__}: {str(e)}"

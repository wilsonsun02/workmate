import os

import httpx
from loguru import logger


def get_agent_base_url() -> str:
    return os.environ.get("WORKMATE_AGENT_BASE_URL", "http://127.0.0.1:8009").rstrip(
        "/"
    )


async def notify_agent_reload(reason: str = "") -> bool:
    # """Notify the standalone Agent service to reload in-memory runtime state."""
    # url = f"{get_agent_base_url()}/agent/reload"
    # try:
    #     async with httpx.AsyncClient(timeout=3.0) as client:
    #         response = await client.post(url, json={"reason": reason})
    #         response.raise_for_status()
    #     logger.info("Agent runtime reload notified: {}", reason or "unspecified")
    #     return True
    # except Exception as error:
    #     logger.warning("Agent runtime reload notify failed ({}): {}", url, error)
    #     return False
    return True

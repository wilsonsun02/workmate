from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

from loguru import logger

_STATE: dict[str, object] = {
    "configured": False,
    "log_path": "",
}

_RE_URL_KEY = re.compile(r"([?&](?:key|token|api[_-]?key)=)([^&\s]+)", re.IGNORECASE)
_RE_BEARER = re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]+)", re.IGNORECASE)
_RE_INLINE_SECRET = re.compile(
    r"((?:api[_-]?key|token|secret|password)\s*[:=]\s*)([^\s,;\"']+)",
    re.IGNORECASE,
)


def _redact_sensitive(text: str) -> str:
    """Mask common secrets before writing logs."""
    if not text:
        return text
    text = _RE_URL_KEY.sub(r"\1***REDACTED***", text)
    text = _RE_BEARER.sub(r"\1***REDACTED***", text)
    text = _RE_INLINE_SECRET.sub(r"\1***REDACTED***", text)
    return text


def _is_true_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _stdout_sink():
    """Return sys.stdout when it is writable; None for windowed PyInstaller builds."""
    stream = sys.stdout
    if stream is None:
        return None
    try:
        if hasattr(stream, "writable") and not stream.writable():
            return None
    except Exception:
        return None
    return stream


def _default_source_logger_patcher(record) -> None:
    """Unify src= for native Loguru logs; keep explicit bind (e.g. stdlib intercept)."""
    extra = record["extra"]
    if extra.get("source_logger") in (None, "", "-"):
        extra["source_logger"] = record["name"]


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        level_name = (
            record.levelname
            if record.levelname in {"DEBUG", "INFO", "ERROR"}
            else "INFO"
        )
        message = _redact_sensitive(record.getMessage())
        logger.bind(source_logger=record.name).log(level_name, message)


def _runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def resolve_logs_dir(
    app_name: str, base_dir: str | os.PathLike[str] | None = None
) -> Path:
    if app_name == "desktop":
        if getattr(sys, "frozen", False):
            logs_dir = _runtime_base_dir() / "logs"
        else:
            logs_dir = (_runtime_base_dir() / "desktop_temp" / "logs").resolve()
    else:
        candidate = Path(base_dir).resolve() if base_dir else _runtime_base_dir()
        logs_dir = candidate / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def init_logging(
    app_name: str,
    *,
    base_dir: str | os.PathLike[str] | None = None,
    level: str = "INFO",
) -> Path:
    normalized_level = str(level).strip().upper()
    if normalized_level not in {"DEBUG", "INFO", "ERROR"}:
        normalized_level = "INFO"
    logs_dir = resolve_logs_dir(app_name, base_dir=base_dir)
    log_file = logs_dir / f"{app_name}.log"

    if _STATE["configured"] and _STATE["log_path"] == str(log_file):
        return log_file

    logger.remove()
    logger.configure(
        extra={"source_logger": "-"},
        patcher=_default_source_logger_patcher,
    )
    fmt = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | "
        "{name}:{function}:{line} | src={extra[source_logger]} - {message}"
    )
    logger.add(
        str(log_file),
        level=normalized_level,
        encoding="utf-8",
        rotation="20 MB",
        retention=10,
        enqueue=True,
        delay=True,
        format=fmt,
        filter=lambda record: bool(
            record.update(message=_redact_sensitive(record["message"])) or True
        ),
    )
    if _is_true_env("WORKMATE_LOG_STDOUT", default=False):
        stdout = _stdout_sink()
        if stdout is not None:
            logger.add(
                stdout,
                level=normalized_level,
                enqueue=True,
                format=fmt,
                colorize=False,
                filter=lambda record: bool(
                    record.update(message=_redact_sensitive(record["message"])) or True
                ),
            )
    root = logging.getLogger()
    root.handlers = [_InterceptHandler()]
    root.setLevel(getattr(logging, normalized_level, logging.INFO))
    for noisy in ("mcp.shared.session", "pydantic"):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    _STATE["configured"] = True
    _STATE["log_path"] = str(log_file)
    return log_file

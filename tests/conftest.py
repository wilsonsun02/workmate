"""Shared pytest fixtures for the Workmate test suite.

All fixtures avoid real external services, real secrets, and
machine-specific paths.  Imports inside test functions keep import-time
side-effects isolated from module-level code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Content-security helpers – shared across test_content_security.py classes
# ---------------------------------------------------------------------------


def write_rules_json(config_dir: Path, overrides: dict | None = None) -> Path:
    """Write a minimal ``content_security_rules.json`` into *config_dir*.

    Returns the path to the written file so callers can monkeypatch
    ``ContentSecurityEngine._CONFIG_PATH``.
    """
    rules = {
        "enabled": True,
        "channels": ["wechat", "wechat_work"],
        "keywords_blacklist": ["机密", "内部定价", "password123"],
        "rule_sources": {},
        "custom_rules": ["不得泄露客户手机号"],
        "llm_review_enabled": False,
        "notify_owner": True,
        "owner_notify_message": "【安全通知】{violations}",
        "client_safe_message": "该消息未通过安全审查",
        "llm_review_prompt_template": "",
        **(overrides or {}),
    }
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "content_security_rules.json"
    path.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def content_security_engine(tmp_path: Path, monkeypatch):
    """Return a ContentSecurityEngine whose config file lives in *tmp_path*."""
    config_dir = tmp_path / "config"
    rules_path = write_rules_json(config_dir)

    monkeypatch.setattr(
        "workflow.content_security.ContentSecurityEngine._CONFIG_PATH",
        str(rules_path),
    )
    from workflow.content_security import ContentSecurityEngine

    eng = ContentSecurityEngine()
    eng._rules_cache = None
    eng._cache_timestamp = 0
    return eng

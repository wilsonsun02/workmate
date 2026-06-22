"""Tests for ``workflow.content_security`` — keyword scanning, message building,
and file-text extraction.

These tests exercise the deterministic, non-LLM parts of the content
security engine.  No real LLM calls, external services, or network access.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# _keyword_scan
# ---------------------------------------------------------------------------


class DescribeKeywordScan:
    """Tests for ``ContentSecurityEngine._keyword_scan``."""

    def test_detects_blacklisted_keyword(self, content_security_engine):
        violations = content_security_engine._keyword_scan("这份文件包含机密信息")
        assert len(violations) >= 1
        assert any("机密" in v for v in violations)

    def test_no_violations_for_clean_content(self, content_security_engine):
        violations = content_security_engine._keyword_scan("今天天气很好")
        assert violations == []

    def test_detects_multiple_keywords(self, content_security_engine):
        violations = content_security_engine._keyword_scan("机密文件显示内部定价为100元")
        assert len(violations) >= 2

    def test_empty_content_no_violations(self, content_security_engine):
        violations = content_security_engine._keyword_scan("")
        assert violations == []

    def test_keywords_disabled_when_config_empty(self, tmp_path: Path, monkeypatch):
        """When keywords_blacklist is empty, no violations should be raised."""
        from tests.conftest import write_rules_json

        config_dir = tmp_path / "config"
        rules_path = write_rules_json(config_dir, overrides={"keywords_blacklist": []})

        monkeypatch.setattr(
            "workflow.content_security.ContentSecurityEngine._CONFIG_PATH",
            str(rules_path),
        )
        from workflow.content_security import ContentSecurityEngine

        eng = ContentSecurityEngine()
        eng._rules_cache = None
        eng._cache_timestamp = 0
        violations = eng._keyword_scan("机密文件")
        assert violations == []

    def test_keyword_scan_runs_even_when_engine_disabled(
        self, tmp_path: Path, monkeypatch
    ):
        """_keyword_scan doesn't check enabled flag — that's check_text's job."""
        from tests.conftest import write_rules_json

        config_dir = tmp_path / "config"
        rules_path = write_rules_json(config_dir, overrides={"enabled": False})

        monkeypatch.setattr(
            "workflow.content_security.ContentSecurityEngine._CONFIG_PATH",
            str(rules_path),
        )
        from workflow.content_security import ContentSecurityEngine

        eng = ContentSecurityEngine()
        eng._rules_cache = None
        eng._cache_timestamp = 0
        violations = eng._keyword_scan("机密")
        assert len(violations) >= 1


# ---------------------------------------------------------------------------
# build_owner_notify_message
# ---------------------------------------------------------------------------


class DescribeBuildOwnerNotifyMessage:
    """Tests for ``ContentSecurityEngine.build_owner_notify_message``."""

    def test_builds_message_with_violations(self, content_security_engine):
        from workflow.content_security import CheckResult

        result = CheckResult(
            passed=False,
            violations=["包含禁止关键词「机密」"],
        )
        msg = content_security_engine.build_owner_notify_message(result)
        assert "机密" in msg
        assert "【安全通知】" in msg

    def test_empty_when_notify_disabled(self, tmp_path: Path, monkeypatch):
        from tests.conftest import write_rules_json
        from workflow.content_security import ContentSecurityEngine, CheckResult

        config_dir = tmp_path / "config"
        rules_path = write_rules_json(config_dir, overrides={"notify_owner": False})

        monkeypatch.setattr(
            "workflow.content_security.ContentSecurityEngine._CONFIG_PATH",
            str(rules_path),
        )
        eng = ContentSecurityEngine()
        eng._rules_cache = None
        eng._cache_timestamp = 0

        result = CheckResult(passed=False, violations=["test"])
        assert eng.build_owner_notify_message(result) == ""

    def test_appends_context(self, content_security_engine):
        from workflow.content_security import CheckResult

        result = CheckResult(
            passed=False,
            violations=["包含禁止关键词「内部定价」"],
        )
        msg = content_security_engine.build_owner_notify_message(
            result, context="wechat:张三"
        )
        assert "wechat:张三" in msg


# ---------------------------------------------------------------------------
# _extract_file_text
# ---------------------------------------------------------------------------


class DescribeExtractFileText:
    """Tests for ``ContentSecurityEngine._extract_file_text``."""

    @pytest.mark.parametrize(
        "ext,content",
        [
            (".txt", "hello world"),
            (".md", "# Markdown title"),
            (".json", '{"key": "value"}'),
            (".csv", "a,b,c"),
            (".log", "INFO: started"),
            (".yaml", "key: value"),
            (".yml", "key: value"),
            (".xml", "<root/>"),
            (".ini", "[section]\nkey=val"),
        ],
    )
    def test_extracts_text_file_content(
        self, content_security_engine, tmp_path: Path, ext, content
    ):
        file_path = tmp_path / f"test{ext}"
        file_path.write_text(content, encoding="utf-8")
        extracted = content_security_engine._extract_file_text(str(file_path))
        assert extracted == content

    def test_uppercase_extension_still_extracts(
        self, content_security_engine, tmp_path: Path
    ):
        file_path = tmp_path / "README.TXT"
        file_path.write_text("uppercase ext test", encoding="utf-8")
        extracted = content_security_engine._extract_file_text(str(file_path))
        assert extracted == "uppercase ext test"

    def test_file_without_extension_returns_empty(
        self, content_security_engine, tmp_path: Path
    ):
        file_path = tmp_path / "noext"
        file_path.write_text("no extension", encoding="utf-8")
        assert content_security_engine._extract_file_text(str(file_path)) == ""

    def test_unsupported_extension_returns_empty(
        self, content_security_engine, tmp_path: Path
    ):
        file_path = tmp_path / "image.png"
        file_path.write_text("fake png", encoding="utf-8")
        assert content_security_engine._extract_file_text(str(file_path)) == ""

    def test_missing_file_returns_empty(
        self, content_security_engine, tmp_path: Path
    ):
        assert (
            content_security_engine._extract_file_text(
                str(tmp_path / "does_not_exist.txt")
            )
            == ""
        )

    def test_binary_file_read_with_errors_ignore(
        self, content_security_engine, tmp_path: Path
    ):
        """Files with non-UTF-8 bytes should decode with errors='ignore'."""
        file_path = tmp_path / "broken.log"
        file_path.write_bytes(b"valid start \xff\xfe broken end")
        extracted = content_security_engine._extract_file_text(str(file_path))
        assert "valid start" in extracted
        assert "broken end" in extracted


# ---------------------------------------------------------------------------
# CheckResult dataclass
# ---------------------------------------------------------------------------


class DescribeCheckResult:
    """Tests for the ``CheckResult`` dataclass."""

    def test_failed_result_stores_all_fields(self):
        from workflow.content_security import CheckResult

        r = CheckResult(
            passed=False,
            violations=["v1"],
            safe_content="blocked",
            raw_content="original",
            intercept_type="keyword",
        )
        assert r.passed is False
        assert r.violations == ["v1"]
        assert r.safe_content == "blocked"
        assert r.raw_content == "original"
        assert r.intercept_type == "keyword"

    def test_passed_result_uses_defaults(self):
        from workflow.content_security import CheckResult

        r = CheckResult(passed=True)
        assert r.passed is True
        assert r.violations == []
        assert r.safe_content == ""
        assert r.raw_content == ""
        assert r.intercept_type == ""


# ---------------------------------------------------------------------------
# ContentSecurityBlockedError
# ---------------------------------------------------------------------------


class DescribeContentSecurityBlockedError:
    """Tests for ``ContentSecurityBlockedError``."""

    def test_stores_message_and_violations(self):
        from workflow.content_security import ContentSecurityBlockedError

        err = ContentSecurityBlockedError("blocked!", ["v1", "v2"])
        assert err.block_message == "blocked!"
        assert err.violations == ["v1", "v2"]
        assert str(err) == "blocked!"

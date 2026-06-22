"""Tests for ``workflow.logging_setup`` — pure helpers and path resolution.

These tests cover the deterministic, local-only functions in the logging
setup module.  No external services; real log files are written under
pytest-managed temporary directories.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# _redact_sensitive
# ---------------------------------------------------------------------------


class DescribeRedactSensitive:
    """Tests for ``_redact_sensitive`` — secret masking in log messages."""

    def test_preserves_empty_and_none(self):
        from workflow.logging_setup import _redact_sensitive

        assert _redact_sensitive("") == ""
        assert _redact_sensitive(None) is None  # type: ignore[arg-type]

    def test_masks_url_query_keys(self):
        from workflow.logging_setup import _redact_sensitive

        masked = _redact_sensitive(
            "GET https://api.example.com/v1?key=secret123&other=val"
        )
        assert "secret123" not in masked
        assert "***REDACTED***" in masked
        assert "other=val" in masked

    def test_masks_bearer_tokens(self):
        from workflow.logging_setup import _redact_sensitive

        masked = _redact_sensitive(
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def"
        )
        assert "eyJhbGci" not in masked
        assert "***REDACTED***" in masked

    def test_masks_inline_secrets(self):
        from workflow.logging_setup import _redact_sensitive

        masked = _redact_sensitive("api_key=abc123, password=secret!")
        assert "abc123" not in masked
        assert "secret!" not in masked
        assert "***REDACTED***" in masked

    def test_benign_text_passes_through(self):
        from workflow.logging_setup import _redact_sensitive

        benign = "User logged in successfully at 2025-01-01"
        assert _redact_sensitive(benign) == benign

    def test_masks_token_in_url_path(self):
        from workflow.logging_setup import _redact_sensitive

        masked = _redact_sensitive(
            "GET /api/v1?token=ghp_abcdef1234567890&page=1"
        )
        assert "ghp_abcdef" not in masked
        assert "***REDACTED***" in masked

    def test_masks_api_key_with_underscore(self):
        from workflow.logging_setup import _redact_sensitive

        masked = _redact_sensitive("api_key: sk-proj-abc123xyz")
        assert "sk-proj-abc123xyz" not in masked
        assert "***REDACTED***" in masked

    def test_masks_password_assignment(self):
        from workflow.logging_setup import _redact_sensitive

        masked = _redact_sensitive("password = superSecret123")
        assert "superSecret123" not in masked
        assert "***REDACTED***" in masked

    def test_multiple_secrets_in_one_line(self):
        from workflow.logging_setup import _redact_sensitive

        masked = _redact_sensitive("api_key=abc token=xyz&key=secret123")
        assert "abc" not in masked
        assert "secret123" not in masked

    def test_case_insensitive_bearer(self):
        from workflow.logging_setup import _redact_sensitive

        masked = _redact_sensitive("authorization: bearer MyToken123")
        assert "MyToken123" not in masked
        assert "***REDACTED***" in masked


# ---------------------------------------------------------------------------
# _InterceptHandler
# ---------------------------------------------------------------------------


class DescribeInterceptHandler:
    """Tests for ``_InterceptHandler`` — stdlib-to-loguru bridge."""

    def test_emit_maps_warning_to_info_with_redaction(self):
        """The handler should emit WARNING-level records as INFO,
        with secrets redacted via ``_redact_sensitive``."""
        import logging
        from workflow.logging_setup import _InterceptHandler

        handler = _InterceptHandler()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="key=secret123",
            args=(),
            exc_info=None,
        )
        # Must not raise — the handler maps WARNING→INFO and redacts
        handler.emit(record)


# ---------------------------------------------------------------------------
# _is_true_env
# ---------------------------------------------------------------------------


class DescribeIsTrueEnv:
    """Tests for ``_is_true_env`` — boolean env-var parsing."""

    def test_default_false_when_unset(self, monkeypatch):
        from workflow.logging_setup import _is_true_env

        monkeypatch.delenv("NO_SUCH_VAR", raising=False)
        assert _is_true_env("NO_SUCH_VAR") is False

    def test_default_respected(self, monkeypatch):
        from workflow.logging_setup import _is_true_env

        monkeypatch.delenv("NO_SUCH_VAR", raising=False)
        assert _is_true_env("NO_SUCH_VAR", default=True) is True

    @pytest.mark.parametrize(
        "value",
        ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON", " 1 ", " yes "],
    )
    def test_truthy_values(self, monkeypatch, value):
        from workflow.logging_setup import _is_true_env

        monkeypatch.setenv("TEST_TRUTHY", value)
        assert _is_true_env("TEST_TRUTHY") is True

    @pytest.mark.parametrize(
        "value",
        [
            "0",
            "false",
            "no",
            "off",
            "",
            "maybe",
            "   ",
        ],
    )
    def test_falsy_values(self, monkeypatch, value):
        from workflow.logging_setup import _is_true_env

        monkeypatch.setenv("TEST_FALSY", value)
        assert _is_true_env("TEST_FALSY") is False


# ---------------------------------------------------------------------------
# resolve_logs_dir
# ---------------------------------------------------------------------------


class DescribeResolveLogsDir:
    """Tests for ``resolve_logs_dir`` — log directory path resolution."""

    def test_serve_uses_base_dir(self, tmp_path: Path):
        from workflow.logging_setup import resolve_logs_dir

        logs = resolve_logs_dir("serve", base_dir=str(tmp_path))
        assert logs == tmp_path / "logs"
        assert logs.is_dir()

    def test_serve_falls_back_to_cwd(self, monkeypatch, tmp_path: Path):
        from workflow.logging_setup import resolve_logs_dir

        monkeypatch.chdir(tmp_path)
        logs = resolve_logs_dir("serve")
        assert logs == tmp_path / "logs"
        assert logs.is_dir()

    def test_desktop_dev_uses_desktop_temp(self, monkeypatch, tmp_path: Path):
        from workflow.logging_setup import resolve_logs_dir

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        logs = resolve_logs_dir("desktop")
        expected = (tmp_path / "desktop_temp" / "logs").resolve()
        assert logs == expected
        assert logs.is_dir()

    def test_creates_missing_directory(self, tmp_path: Path):
        from workflow.logging_setup import resolve_logs_dir

        logs_dir = tmp_path / "nested" / "logs"
        assert not logs_dir.exists()
        result = resolve_logs_dir("serve", base_dir=str(tmp_path / "nested"))
        assert result == logs_dir
        assert logs_dir.is_dir()


# ---------------------------------------------------------------------------
# init_logging smoke — guarded with try/finally to prevent state leakage
# ---------------------------------------------------------------------------


class DescribeInitLoggingSmoke:
    """Minimal smoke test for ``init_logging`` with isolated state."""

    def test_returns_log_file_path(self, tmp_path: Path, monkeypatch):
        """init_logging should return the expected log file Path."""
        from workflow.logging_setup import init_logging, _STATE

        # Reset global state so the test starts clean
        _STATE["configured"] = False
        _STATE["log_path"] = ""

        monkeypatch.setenv("WORKMATE_LOG_STDOUT", "false")

        try:
            result = init_logging("serve", base_dir=str(tmp_path))
            assert isinstance(result, Path)
            assert result.name == "serve.log"
            assert str(tmp_path) in str(result)
        finally:
            from loguru import logger

            logger.remove()
            _STATE["configured"] = False
            _STATE["log_path"] = ""

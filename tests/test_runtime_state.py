"""Tests for ``api.runtime_state`` — pure helpers and path constructors.

These tests cover the deterministic, side-effect-free functions in the
runtime state module.  Path tests use ``monkeypatch`` to control
``workflow.config.BASE_DIR`` without touching the real filesystem.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# _stream_stop_key
# ---------------------------------------------------------------------------


class DescribeStreamStopKey:
    """Tests for ``_stream_stop_key`` — key construction for stream stop flags."""

    def test_normal_ids(self):
        from api.runtime_state import _stream_stop_key

        assert _stream_stop_key("thread-1", "session-a") == "thread-1::session-a"

    def test_empty_thread_id(self):
        from api.runtime_state import _stream_stop_key

        assert _stream_stop_key("", "session-a") == "::session-a"

    def test_empty_session_id(self):
        from api.runtime_state import _stream_stop_key

        assert _stream_stop_key("thread-1", "") == "thread-1::"

    def test_both_empty(self):
        from api.runtime_state import _stream_stop_key

        assert _stream_stop_key("", "") == "::"

    def test_none_thread_id(self):
        from api.runtime_state import _stream_stop_key

        assert _stream_stop_key(None, "session-a") == "::session-a"  # type: ignore[arg-type]

    def test_none_session_id(self):
        from api.runtime_state import _stream_stop_key

        assert _stream_stop_key("thread-1", None) == "thread-1::"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Path constructors
# ---------------------------------------------------------------------------


class DescribePathConstructors:
    """Tests for path-building helpers in ``api.runtime_state``.

    These functions use ``BASE_DIR`` imported from ``workflow.config`` at
    module load time — it's a local string copy, so monkeypatching the
    source module won't affect it.  Instead we verify the returned path
    has the expected structure (suffix components, type).
    """

    def test_desktop_chat_state_file_structure(self):
        from api.runtime_state import desktop_chat_state_file

        path = desktop_chat_state_file()
        assert isinstance(path, Path)
        assert path.parts[-2:] == ("config", "desktop_chat_states.json")

    def test_checkpointer_db_path_structure(self):
        from api.runtime_state import checkpointer_db_path

        path = checkpointer_db_path()
        assert isinstance(path, Path)
        assert path.parts[-2:] == ("checkpoints", "checkpoints.db")


# ---------------------------------------------------------------------------
# get_preload_status
# ---------------------------------------------------------------------------


class DescribePreloadStatus:
    """Tests for ``get_preload_status`` — returns the default preload state dict."""

    def test_returns_dict_with_expected_keys(self):
        from api.runtime_state import get_preload_status

        status = get_preload_status()
        assert isinstance(status, dict)
        assert "enabled" in status
        assert "done" in status
        assert "ok" in status
        assert "message" in status

    def test_mutation_affects_global_state(self):
        """The returned dict is the shared global — mutations are visible to
        subsequent callers (this is by design in the production code)."""
        from api.runtime_state import get_preload_status

        status = get_preload_status()
        original = status["done"]
        try:
            status["done"] = not original
            assert get_preload_status()["done"] == (not original)
        finally:
            status["done"] = original


# ---------------------------------------------------------------------------
# get_mcp_runtime_self_check
# ---------------------------------------------------------------------------


class DescribeMcpRuntimeSelfCheck:
    """Tests for ``get_mcp_runtime_self_check`` and ``set_mcp_runtime_self_check``."""

    def test_default_has_expected_keys(self):
        from api.runtime_state import get_mcp_runtime_self_check

        check = get_mcp_runtime_self_check()
        assert isinstance(check, dict)
        assert "ok" in check
        assert "checked" in check
        assert "missed" not in check  # key is 'missing_commands'

    def test_set_and_get_roundtrip(self):
        from api.runtime_state import (
            get_mcp_runtime_self_check,
            set_mcp_runtime_self_check,
        )

        original = dict(get_mcp_runtime_self_check())
        try:
            new_value = {"ok": False, "checked": True, "summary": "test"}
            set_mcp_runtime_self_check(new_value)
            assert get_mcp_runtime_self_check()["ok"] is False
            assert get_mcp_runtime_self_check()["summary"] == "test"
        finally:
            set_mcp_runtime_self_check(original)


# ---------------------------------------------------------------------------
# get_runtime_output_base_dir / set_runtime_output_base_dir
# ---------------------------------------------------------------------------


class DescribeRuntimeOutputBaseDir:
    """Tests for ``get_runtime_output_base_dir`` / ``set_runtime_output_base_dir``."""

    def test_set_and_get_roundtrip(self):
        from api.runtime_state import (
            get_runtime_output_base_dir,
            set_runtime_output_base_dir,
        )

        original = get_runtime_output_base_dir()
        try:
            set_runtime_output_base_dir("/tmp/test-output")
            assert get_runtime_output_base_dir() == "/tmp/test-output"
        finally:
            set_runtime_output_base_dir(original)

    def test_set_converts_to_str(self):
        from api.runtime_state import (
            get_runtime_output_base_dir,
            set_runtime_output_base_dir,
        )

        original = get_runtime_output_base_dir()
        try:
            set_runtime_output_base_dir(Path("/tmp/from-path"))
            assert isinstance(get_runtime_output_base_dir(), str)
        finally:
            set_runtime_output_base_dir(original)


# ---------------------------------------------------------------------------
# get_desktop_chat_state_lock
# ---------------------------------------------------------------------------


class DescribeDesktopChatStateLock:
    """Tests for ``get_desktop_chat_state_lock``."""

    def test_returns_singleton_asyncio_lock(self):
        from api.runtime_state import get_desktop_chat_state_lock

        lock1 = get_desktop_chat_state_lock()
        lock2 = get_desktop_chat_state_lock()
        assert lock1 is lock2
        assert lock1 is not None


# ---------------------------------------------------------------------------
# get_mcp_preload_status / set_mcp_preload_status
# ---------------------------------------------------------------------------


class DescribeMcpPreloadStatus:
    """Tests for ``get_mcp_preload_status`` / ``set_mcp_preload_status``."""

    def test_default_has_expected_keys(self):
        from api.runtime_state import get_mcp_preload_status

        status = get_mcp_preload_status()
        assert "done" in status
        assert "ok" in status
        assert "message" in status
        assert "success_servers" in status
        assert "failed_servers" in status
        assert "tools_count" in status

    def test_set_and_get_roundtrip(self):
        from api.runtime_state import (
            get_mcp_preload_status,
            set_mcp_preload_status,
        )

        original = dict(get_mcp_preload_status())
        try:
            new_value = {
                "done": True,
                "ok": True,
                "message": "5 servers ok",
                "success_servers": ["a", "b"],
                "failed_servers": [],
                "tools_count": 10,
            }
            set_mcp_preload_status(new_value)
            assert get_mcp_preload_status()["tools_count"] == 10
        finally:
            set_mcp_preload_status(original)

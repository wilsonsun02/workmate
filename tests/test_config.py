"""Tests for ``workflow.config`` — pure helpers and path/URL resolution.

These tests use monkeypatching to control environment variables before
module import so that ``workflow.config`` module-level code sees
predictable values.  No external services or real secrets required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# _parse_dirs_csv
# ---------------------------------------------------------------------------


class DescribeParseDirsCsv:
    """Tests for ``_parse_dirs_csv`` — CSV-to-list parsing."""

    @pytest.mark.parametrize(
        "input_csv, expected",
        [
            ("/home/user/docs", ["/home/user/docs"]),
            ("/a, /b , /c", ["/a", "/b", "/c"]),
            ("/a,  , /b,,", ["/a", "/b"]),
            ("", []),
            ("  ,  ,  ", []),
            (",", []),
            ("C:\\Users\\docs, D:\\data", ["C:\\Users\\docs", "D:\\data"]),
            (
                "/home/user/My Documents, /tmp/test dir",
                ["/home/user/My Documents", "/tmp/test dir"],
            ),
        ],
    )
    def test_parse_dirs_csv(self, input_csv, expected):
        from workflow.config import _parse_dirs_csv

        assert _parse_dirs_csv(input_csv) == expected


# ---------------------------------------------------------------------------
# _env_int
# ---------------------------------------------------------------------------


class DescribeEnvInt:
    """Tests for ``_env_int`` — safe integer env-var parsing."""

    def test_returns_default_when_unset(self, monkeypatch):
        from workflow.config import _env_int

        monkeypatch.delenv("NO_SUCH_INT", raising=False)
        assert _env_int("NO_SUCH_INT", 42) == 42

    def test_parses_valid_integer(self, monkeypatch):
        from workflow.config import _env_int

        monkeypatch.setenv("TEST_INT", "8080")
        assert _env_int("TEST_INT", 3000) == 8080

    def test_falls_back_to_default_on_garbage(self, monkeypatch):
        from workflow.config import _env_int

        monkeypatch.setenv("TEST_GARBAGE", "not-a-number")
        assert _env_int("TEST_GARBAGE", 99) == 99

    def test_empty_string_falls_back(self, monkeypatch):
        from workflow.config import _env_int

        monkeypatch.setenv("TEST_EMPTY", "   ")
        assert _env_int("TEST_EMPTY", 7) == 7

    def test_zero_is_valid(self, monkeypatch):
        from workflow.config import _env_int

        monkeypatch.setenv("TEST_ZERO", "0")
        assert _env_int("TEST_ZERO", 10) == 0

    def test_negative_value(self, monkeypatch):
        from workflow.config import _env_int

        monkeypatch.setenv("TEST_NEG", "-5")
        assert _env_int("TEST_NEG", 0) == -5

    def test_hex_string_falls_back(self, monkeypatch):
        from workflow.config import _env_int

        monkeypatch.setenv("TEST_HEX", "0xFF")
        assert _env_int("TEST_HEX", 42) == 42

    def test_float_string_falls_back(self, monkeypatch):
        from workflow.config import _env_int

        monkeypatch.setenv("TEST_FLOAT", "3.14")
        assert _env_int("TEST_FLOAT", 10) == 10

    def test_large_value(self, monkeypatch):
        from workflow.config import _env_int

        monkeypatch.setenv("TEST_LARGE", "999999")
        assert _env_int("TEST_LARGE", 0) == 999999


# ---------------------------------------------------------------------------
# resolve_env_file_path
# ---------------------------------------------------------------------------


class DescribeResolveEnvFilePath:
    """Tests for ``resolve_env_file_path`` — .env path resolution."""

    def test_override_via_env_var(self, monkeypatch, tmp_path: Path):
        from workflow.config import resolve_env_file_path

        custom = tmp_path / "custom.env"
        custom.write_text("KEY=val")
        monkeypatch.setenv("WORKMATE_ENV_FILE", str(custom))
        assert resolve_env_file_path() == custom

    def test_default_returns_dotenv_path(self, monkeypatch):
        from workflow.config import resolve_env_file_path

        monkeypatch.delenv("WORKMATE_ENV_FILE", raising=False)
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        result = resolve_env_file_path()
        assert isinstance(result, Path)
        assert result.name == ".env"

    def test_expands_user_tilde(self, monkeypatch):
        from workflow.config import resolve_env_file_path

        monkeypatch.setenv("WORKMATE_ENV_FILE", "~/.workmate.env")
        result = resolve_env_file_path()
        assert result == Path("~/.workmate.env").expanduser()


# ---------------------------------------------------------------------------
# normalize_admin_ws_url
# ---------------------------------------------------------------------------


class DescribeNormalizeAdminWsUrl:
    """Tests for ``normalize_admin_ws_url`` — WebSocket URL normalization."""

    def test_none_uses_default(self):
        from workflow.config import normalize_admin_ws_url

        url = normalize_admin_ws_url(None)
        assert url.startswith("ws://")
        assert url.endswith("/api/admin/client/ws")
        assert "127.0.0.1:8010" in url

    def test_empty_string_uses_default(self):
        from workflow.config import normalize_admin_ws_url

        url = normalize_admin_ws_url("")
        assert url.startswith("ws://")
        assert url.endswith("/api/admin/client/ws")

    def test_http_converted_to_ws(self):
        from workflow.config import normalize_admin_ws_url

        url = normalize_admin_ws_url("http://192.168.1.1:8010")
        assert url == "ws://192.168.1.1:8010/api/admin/client/ws"

    def test_https_converted_to_wss(self):
        from workflow.config import normalize_admin_ws_url

        url = normalize_admin_ws_url("https://admin.example.com")
        assert url.startswith("wss://")
        assert "admin.example.com" in url

    def test_ws_preserved(self):
        from workflow.config import normalize_admin_ws_url

        url = normalize_admin_ws_url("ws://localhost:8010/api/admin/client/ws")
        assert url.startswith("ws://")
        assert "localhost:8010" in url

    def test_path_appended_when_missing(self):
        from workflow.config import normalize_admin_ws_url

        url = normalize_admin_ws_url("http://10.0.0.1:8010")
        assert url.endswith("/api/admin/client/ws")

    def test_admin_api_base_path_normalized(self):
        from workflow.config import normalize_admin_ws_url

        url = normalize_admin_ws_url("http://host:8010/api/admin")
        assert url.endswith("/api/admin/client/ws")
        assert url.count("/api/admin/client/ws") == 1

    def test_wss_preserved(self):
        from workflow.config import normalize_admin_ws_url

        url = normalize_admin_ws_url("wss://secure.example.com:8010")
        assert url.startswith("wss://")
        assert "secure.example.com" in url

    def test_no_scheme_defaults_to_ws(self):
        from workflow.config import normalize_admin_ws_url

        url = normalize_admin_ws_url("192.168.1.1:8010")
        assert url.startswith("ws://")
        assert "192.168.1.1:8010" in url

    def test_admin_client_in_path_normalized(self):
        from workflow.config import normalize_admin_ws_url

        url = normalize_admin_ws_url("http://host:8010/api/admin/client")
        assert url.endswith("/api/admin/client/ws")
        assert url.count("/api/admin/client/ws") == 1

    def test_generic_path_appended(self):
        """When the URL has a non-admin path, ws path is appended."""
        from workflow.config import normalize_admin_ws_url

        url = normalize_admin_ws_url("http://host:8010/some/other/path")
        assert url.endswith("/some/other/path/api/admin/client/ws")


# ---------------------------------------------------------------------------
# get_admin_service_origin / get_admin_api_base / normalize_admin_api_base
# ---------------------------------------------------------------------------


class DescribeAdminServiceOrigin:
    """Tests for ``get_admin_service_origin``, ``get_admin_api_base``,
    and ``normalize_admin_api_base``."""

    def test_origin_from_env_base(self, monkeypatch):
        from workflow.config import get_admin_service_origin

        monkeypatch.setenv(
            "WORKMATE_ADMIN_API_BASE", "http://admin.example.com:8010"
        )
        assert get_admin_service_origin() == "http://admin.example.com:8010"

    def test_origin_strips_trailing_slash(self, monkeypatch):
        from workflow.config import get_admin_service_origin

        monkeypatch.setenv(
            "WORKMATE_ADMIN_API_BASE", "http://admin.example.com:8010/"
        )
        assert get_admin_service_origin() == "http://admin.example.com:8010"

    def test_origin_strips_admin_api_path(self, monkeypatch):
        from workflow.config import get_admin_service_origin

        monkeypatch.setenv(
            "WORKMATE_ADMIN_API_BASE",
            "http://admin.example.com:8010/api/admin",
        )
        assert get_admin_service_origin() == "http://admin.example.com:8010"

    def test_api_base_appends_path(self, monkeypatch):
        from workflow.config import get_admin_api_base

        monkeypatch.setenv(
            "WORKMATE_ADMIN_API_BASE", "http://admin.example.com:8010"
        )
        assert get_admin_api_base() == "http://admin.example.com:8010/api/admin"

    def test_api_base_does_not_double_path(self, monkeypatch):
        from workflow.config import get_admin_api_base

        monkeypatch.setenv(
            "WORKMATE_ADMIN_API_BASE",
            "http://admin.example.com:8010/api/admin",
        )
        assert get_admin_api_base() == "http://admin.example.com:8010/api/admin"

    def test_origin_with_explicit_url_param(self):
        from workflow.config import get_admin_service_origin

        origin = get_admin_service_origin(
            "https://custom.example.com:9000/api/admin"
        )
        assert origin == "https://custom.example.com:9000"

    def test_normalize_admin_api_base(self):
        from workflow.config import normalize_admin_api_base

        result = normalize_admin_api_base("http://10.0.0.1:8010/some/path")
        assert result.endswith("/api/admin")

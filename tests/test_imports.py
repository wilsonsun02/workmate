"""Import sanity tests — verify key project modules are importable without errors.

These tests ensure that modules which *should* import cleanly in a test
environment actually do.  Each test imports the module and asserts the
presence of its key public API surface (not just that the import didn't
crash).

Modules that require real MySQL, Redis, LLM keys, Docker, Windows GUI,
or WeChat runtime are intentionally excluded.
"""

from __future__ import annotations


class DescribeSafeImports:
    """Project modules that should import without external service deps."""

    def test_workflow_logging_setup(self):
        import workflow.logging_setup

        assert hasattr(workflow.logging_setup, "_redact_sensitive")
        assert hasattr(workflow.logging_setup, "resolve_logs_dir")
        assert hasattr(workflow.logging_setup, "init_logging")

    def test_workflow_content_security(self):
        import workflow.content_security

        assert hasattr(workflow.content_security, "ContentSecurityEngine")
        assert hasattr(workflow.content_security, "CheckResult")
        assert hasattr(workflow.content_security, "ContentSecurityBlockedError")

    def test_workflow_config(self):
        import workflow.config

        assert hasattr(workflow.config, "BASE_DIR")
        assert hasattr(workflow.config, "_parse_dirs_csv")
        assert hasattr(workflow.config, "_env_int")
        assert hasattr(workflow.config, "normalize_admin_ws_url")
        assert hasattr(workflow.config, "get_admin_service_origin")
        assert hasattr(workflow.config, "resolve_env_file_path")

    def test_workflow_subagents_config(self):
        import workflow.subagents_config

        assert hasattr(workflow.subagents_config, "_find_tools_by_mcp_list")

    def test_api_routers_package(self):
        import api.routers

        # The routers package should exist and have a docstring
        assert api.routers.__doc__ is not None

    def test_api_runtime_state(self):
        import api.runtime_state

        assert hasattr(api.runtime_state, "_stream_stop_key")
        assert hasattr(api.runtime_state, "get_preload_status")
        assert hasattr(api.runtime_state, "desktop_chat_state_file")
        assert hasattr(api.runtime_state, "checkpointer_db_path")

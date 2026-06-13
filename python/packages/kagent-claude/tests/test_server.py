"""Tests for kagent-claude golden image entrypoint (server.py)."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from a2a.types import AgentSkill

from kagent.claude.server import (
    _env,
    _env_bool,
    _env_float,
    _env_int,
    _interpolate_env_vars,
    _parse_comma_list,
    _parse_dirs,
    _parse_effort,
    _parse_mcp_servers,
    _parse_permission_mode,
    _parse_skills,
    _parse_tools,
    build_app,
)

# ---------------------------------------------------------------------------
# _env
# ---------------------------------------------------------------------------


class TestEnv:
    def test_returns_value(self):
        with patch.dict(os.environ, {"TEST_KEY": "hello"}, clear=True):
            assert _env("TEST_KEY") == "hello"

    def test_strips_whitespace(self):
        with patch.dict(os.environ, {"TEST_KEY": "  spaced  "}, clear=True):
            assert _env("TEST_KEY") == "spaced"

    def test_returns_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env("MISSING_KEY", "fallback") == "fallback"

    def test_returns_empty_string_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env("MISSING_KEY") == ""


# ---------------------------------------------------------------------------
# _env_bool
# ---------------------------------------------------------------------------


class TestEnvBool:
    @pytest.mark.parametrize("val", ["true", "True", "TRUE", "1", "yes", "on", "ON"])
    def test_truthy_values(self, val):
        with patch.dict(os.environ, {"FLAG": val}, clear=True):
            assert _env_bool("FLAG") is True

    @pytest.mark.parametrize("val", ["false", "False", "0", "no", "off", ""])
    def test_falsy_values(self, val):
        with patch.dict(os.environ, {"FLAG": val}, clear=True):
            assert _env_bool("FLAG") is False

    def test_default_false(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_bool("MISSING") is False

    def test_default_true(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_bool("MISSING", True) is True


# ---------------------------------------------------------------------------
# _env_int
# ---------------------------------------------------------------------------


class TestEnvInt:
    def test_valid_int(self):
        with patch.dict(os.environ, {"COUNT": "42"}, clear=True):
            assert _env_int("COUNT") == 42

    def test_negative_int(self):
        with patch.dict(os.environ, {"COUNT": "-5"}, clear=True):
            assert _env_int("COUNT") == -5

    def test_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_int("MISSING", 10) == 10

    def test_invalid_returns_default_with_warning(self):
        with patch.dict(os.environ, {"COUNT": "abc"}, clear=True):
            with patch("kagent.claude.server.logger") as mock_logger:
                result = _env_int("COUNT", 99)
                assert result == 99
                mock_logger.warning.assert_called_once()
                assert "Invalid integer" in mock_logger.warning.call_args[0][0]


# ---------------------------------------------------------------------------
# _env_float
# ---------------------------------------------------------------------------


class TestEnvFloat:
    def test_valid_float(self):
        with patch.dict(os.environ, {"RATE": "3.14"}, clear=True):
            assert _env_float("RATE") == pytest.approx(3.14)

    def test_integer_string_as_float(self):
        with patch.dict(os.environ, {"RATE": "5"}, clear=True):
            assert _env_float("RATE") == 5.0

    def test_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_float("MISSING", 1.5) == pytest.approx(1.5)

    def test_invalid_returns_default_with_warning(self):
        with patch.dict(os.environ, {"RATE": "not-a-float"}, clear=True):
            with patch("kagent.claude.server.logger") as mock_logger:
                result = _env_float("RATE", 2.0)
                assert result == pytest.approx(2.0)
                mock_logger.warning.assert_called_once()
                assert "Invalid float" in mock_logger.warning.call_args[0][0]


# ---------------------------------------------------------------------------
# _parse_tools
# ---------------------------------------------------------------------------


class TestParseTools:
    def test_empty_string_returns_defaults(self):
        result = _parse_tools("")
        assert result == ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]

    def test_comma_separated(self):
        result = _parse_tools("Bash,Read")
        assert result == ["Bash", "Read"]

    def test_strips_whitespace(self):
        result = _parse_tools(" Bash , Read , Write ")
        assert result == ["Bash", "Read", "Write"]

    def test_filters_empty_items(self):
        result = _parse_tools("Bash,,Read,,,Write")
        assert result == ["Bash", "Read", "Write"]

    def test_single_tool(self):
        result = _parse_tools("Bash")
        assert result == ["Bash"]


# ---------------------------------------------------------------------------
# _interpolate_env_vars
# ---------------------------------------------------------------------------


class TestInterpolateEnvVars:
    def test_dollar_var(self):
        with patch.dict(os.environ, {"MY_VAR": "resolved"}, clear=True):
            assert _interpolate_env_vars("$MY_VAR") == "resolved"

    def test_braced_var(self):
        with patch.dict(os.environ, {"MY_VAR": "resolved"}, clear=True):
            assert _interpolate_env_vars("${MY_VAR}") == "resolved"

    def test_escaped_dollar(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _interpolate_env_vars("$$LITERAL") == "$LITERAL"

    def test_missing_var_resolves_to_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _interpolate_env_vars("$NONEXISTENT") == ""

    def test_mixed_references(self):
        with patch.dict(os.environ, {"A": "one", "B": "two"}, clear=True):
            assert _interpolate_env_vars("$A and ${B}") == "one and two"

    def test_recursive_dict(self):
        with patch.dict(os.environ, {"TOKEN": "secret"}, clear=True):
            result = _interpolate_env_vars({"key": "$TOKEN", "nested": {"inner": "${TOKEN}"}})
            assert result == {"key": "secret", "nested": {"inner": "secret"}}

    def test_recursive_list(self):
        with patch.dict(os.environ, {"VAL": "x"}, clear=True):
            result = _interpolate_env_vars(["$VAL", "${VAL}"])
            assert result == ["x", "x"]

    def test_non_string_passthrough_int(self):
        assert _interpolate_env_vars(42) == 42

    def test_non_string_passthrough_bool(self):
        assert _interpolate_env_vars(True) is True

    def test_non_string_passthrough_none(self):
        assert _interpolate_env_vars(None) is None

    def test_string_with_no_vars(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _interpolate_env_vars("plain text") == "plain text"

    def test_var_embedded_in_string(self):
        with patch.dict(os.environ, {"HOST": "localhost"}, clear=True):
            assert _interpolate_env_vars("http://$HOST:8080") == "http://localhost:8080"


# ---------------------------------------------------------------------------
# _parse_mcp_servers
# ---------------------------------------------------------------------------


class TestParseMcpServers:
    def test_empty_string_returns_none(self):
        assert _parse_mcp_servers("") is None

    def test_valid_json_dict(self):
        val = json.dumps({"gh": {"command": "npx", "args": ["server-github"]}})
        result = _parse_mcp_servers(val)
        assert result == {"gh": {"command": "npx", "args": ["server-github"]}}

    def test_non_dict_json_returns_none_with_warning(self):
        with patch("kagent.claude.server.logger") as mock_logger:
            result = _parse_mcp_servers(json.dumps(["not", "a", "dict"]))
            assert result is None
            mock_logger.warning.assert_called_once()
            assert "JSON object" in mock_logger.warning.call_args[0][0]

    def test_invalid_json_returns_none_with_warning(self):
        with patch("kagent.claude.server.logger") as mock_logger:
            result = _parse_mcp_servers("{bad json")
            assert result is None
            mock_logger.warning.assert_called_once()
            assert "Failed to parse" in mock_logger.warning.call_args[0][0]

    def test_env_var_interpolation_in_values(self):
        with patch.dict(os.environ, {"MY_TOKEN": "secret123"}, clear=True):
            val = json.dumps({"gh": {"env": {"GITHUB_TOKEN": "$MY_TOKEN"}}})
            result = _parse_mcp_servers(val)
            assert result == {"gh": {"env": {"GITHUB_TOKEN": "secret123"}}}

    def test_env_var_interpolation_braced_syntax(self):
        with patch.dict(os.environ, {"MY_TOKEN": "secret123"}, clear=True):
            val = json.dumps({"gh": {"env": {"GITHUB_TOKEN": "${MY_TOKEN}"}}})
            result = _parse_mcp_servers(val)
            assert result["gh"]["env"]["GITHUB_TOKEN"] == "secret123"


# ---------------------------------------------------------------------------
# _parse_skills
# ---------------------------------------------------------------------------


class TestParseSkills:
    def test_empty_string_returns_default_skill(self):
        result = _parse_skills("")
        assert len(result) == 1
        assert isinstance(result[0], AgentSkill)
        assert result[0].id == "general"
        assert result[0].name == "General assistance"
        assert "coding" in result[0].tags

    def test_valid_json_array(self):
        val = json.dumps([
            {
                "id": "k8s",
                "name": "Kubernetes",
                "description": "K8s management",
                "tags": ["k8s", "devops"],
                "examples": ["List pods"],
            }
        ])
        result = _parse_skills(val)
        assert len(result) == 1
        assert result[0].id == "k8s"
        assert result[0].name == "Kubernetes"
        assert result[0].tags == ["k8s", "devops"]

    def test_single_object_wrapped_in_list(self):
        val = json.dumps({"id": "solo", "name": "Solo Skill", "description": "desc"})
        result = _parse_skills(val)
        assert len(result) == 1
        assert result[0].id == "solo"

    def test_invalid_json_returns_default_with_warning(self):
        with patch("kagent.claude.server.logger") as mock_logger:
            result = _parse_skills("{bad json")
            assert len(result) == 1
            assert result[0].id == "general"
            mock_logger.warning.assert_called_once()

    def test_multiple_skills(self):
        val = json.dumps([
            {"id": "a", "name": "A", "description": "Skill A", "tags": []},
            {"id": "b", "name": "B", "description": "Skill B", "tags": ["tag"]},
        ])
        result = _parse_skills(val)
        assert len(result) == 2
        assert result[0].id == "a"
        assert result[1].id == "b"

    def test_missing_fields_use_defaults(self):
        val = json.dumps([{}])
        result = _parse_skills(val)
        assert len(result) == 1
        assert result[0].id == "skill"
        assert result[0].name == "Skill"
        assert result[0].description == ""
        assert result[0].tags == []
        assert result[0].examples == []

    def test_malformed_items_return_default(self):
        """Non-dict items in list cause AttributeError, caught gracefully."""
        with patch("kagent.claude.server.logger") as mock_logger:
            result = _parse_skills(json.dumps(["not-a-dict"]))
            assert len(result) == 1
            assert result[0].id == "general"
            mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# _parse_permission_mode
# ---------------------------------------------------------------------------


class TestParsePermissionMode:
    def test_empty_string_returns_none(self):
        assert _parse_permission_mode("") is None

    def test_valid_modes(self):
        assert _parse_permission_mode("default") == "default"
        assert _parse_permission_mode("acceptEdits") == "acceptEdits"
        assert _parse_permission_mode("bypassPermissions") == "bypassPermissions"
        assert _parse_permission_mode("plan") == "plan"
        assert _parse_permission_mode("dontAsk") == "dontAsk"

    def test_case_insensitive(self):
        assert _parse_permission_mode("ACCEPTEDITS") == "acceptEdits"
        assert _parse_permission_mode("bypasspermissions") == "bypassPermissions"
        assert _parse_permission_mode("Plan") == "plan"
        assert _parse_permission_mode("DONTASK") == "dontAsk"

    def test_strips_whitespace(self):
        assert _parse_permission_mode("  plan  ") == "plan"

    def test_invalid_returns_none_with_warning(self):
        with patch("kagent.claude.server.logger") as mock_logger:
            result = _parse_permission_mode("invalid_mode")
            assert result is None
            mock_logger.warning.assert_called_once()
            assert "Invalid CLAUDE_PERMISSION_MODE" in mock_logger.warning.call_args[0][0]


# ---------------------------------------------------------------------------
# _parse_effort
# ---------------------------------------------------------------------------


class TestParseEffort:
    def test_empty_string_returns_none(self):
        assert _parse_effort("") is None

    def test_valid_levels(self):
        assert _parse_effort("low") == "low"
        assert _parse_effort("medium") == "medium"
        assert _parse_effort("high") == "high"
        assert _parse_effort("xhigh") == "xhigh"
        assert _parse_effort("max") == "max"

    def test_case_insensitive(self):
        assert _parse_effort("LOW") == "low"
        assert _parse_effort("High") == "high"
        assert _parse_effort("MAX") == "max"

    def test_strips_whitespace(self):
        assert _parse_effort("  medium  ") == "medium"

    def test_invalid_returns_none_with_warning(self):
        with patch("kagent.claude.server.logger") as mock_logger:
            result = _parse_effort("ultra")
            assert result is None
            mock_logger.warning.assert_called_once()
            assert "Invalid CLAUDE_EFFORT" in mock_logger.warning.call_args[0][0]


# ---------------------------------------------------------------------------
# _parse_comma_list
# ---------------------------------------------------------------------------


class TestParseCommaList:
    def test_empty_string_returns_empty_list(self):
        assert _parse_comma_list("") == []

    def test_comma_separated(self):
        result = _parse_comma_list("Bash,Write,Edit")
        assert result == ["Bash", "Write", "Edit"]

    def test_strips_whitespace(self):
        result = _parse_comma_list(" Bash , Write ")
        assert result == ["Bash", "Write"]

    def test_filters_empty_items(self):
        result = _parse_comma_list("Bash,,Write,,,")
        assert result == ["Bash", "Write"]

    def test_single_item(self):
        result = _parse_comma_list("Bash")
        assert result == ["Bash"]


# ---------------------------------------------------------------------------
# _parse_dirs
# ---------------------------------------------------------------------------


class TestParseDirs:
    def test_empty_string_returns_empty_list(self):
        assert _parse_dirs("") == []

    def test_comma_separated_absolute_paths(self):
        result = _parse_dirs("/data/shared,/mnt/datasets")
        assert result == ["/data/shared", "/mnt/datasets"]

    def test_strips_whitespace(self):
        result = _parse_dirs(" /data , /mnt ")
        assert result == ["/data", "/mnt"]

    def test_filters_empty_items(self):
        result = _parse_dirs("/data,,/mnt,,,")
        assert result == ["/data", "/mnt"]

    def test_single_path(self):
        result = _parse_dirs("/data/shared")
        assert result == ["/data/shared"]

    def test_warns_on_relative_path(self):
        with patch("kagent.claude.server.logger") as mock_logger:
            result = _parse_dirs("relative/path,/absolute/path")
            assert result == ["relative/path", "/absolute/path"]
            mock_logger.warning.assert_called_once()
            assert "non-absolute" in mock_logger.warning.call_args[0][0]

    def test_multiple_relative_paths_warn_each(self):
        with patch("kagent.claude.server.logger") as mock_logger:
            result = _parse_dirs("foo,bar")
            assert result == ["foo", "bar"]
            assert mock_logger.warning.call_count == 2


# ---------------------------------------------------------------------------
# build_app
# ---------------------------------------------------------------------------


class TestBuildApp:
    """Tests for build_app() with mocked dependencies."""

    def _build_with_env(self, env_vars: dict):
        """Helper: run build_app() with given env vars and mocked deps."""
        with (
            patch.dict(os.environ, env_vars, clear=True),
            patch("kagent.claude.server.ClaudeAgentOptions") as MockOptions,
            patch("kagent.claude.server.KAgentApp") as MockApp,
            patch("kagent.claude.server.ClaudeAgentExecutorConfig") as MockConfig,
        ):
            MockOptions.return_value = MagicMock(name="options_instance")
            MockApp.return_value = MagicMock(name="app_instance")
            MockConfig.return_value = MagicMock(name="config_instance")

            result = build_app()

            return result, MockOptions, MockApp, MockConfig

    def test_default_env_produces_expected_options(self):
        _, MockOptions, MockApp, MockConfig = self._build_with_env({})

        options_kwargs = MockOptions.call_args[1]
        default_tools = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
        assert options_kwargs["tools"] == default_tools
        assert options_kwargs["allowed_tools"] == default_tools
        assert "system_prompt" not in options_kwargs
        assert options_kwargs["max_turns"] == 25

        config_kwargs = MockConfig.call_args[1]
        assert config_kwargs["execution_timeout"] == pytest.approx(300.0)
        assert config_kwargs["enable_streaming"] is True
        assert config_kwargs["enable_hitl"] is False

    def test_custom_tools(self):
        _, MockOptions, _, _ = self._build_with_env({"CLAUDE_TOOLS": "Bash,Read"})
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["tools"] == ["Bash", "Read"]
        # When CLAUDE_ALLOWED_TOOLS is unset, defaults to same as tools
        assert options_kwargs["allowed_tools"] == ["Bash", "Read"]

    def test_allowed_tools_separate_from_tools(self):
        _, MockOptions, _, _ = self._build_with_env({
            "CLAUDE_TOOLS": "Bash,Read,Write,Edit",
            "CLAUDE_ALLOWED_TOOLS": "Read,Edit",
        })
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["tools"] == ["Bash", "Read", "Write", "Edit"]
        assert options_kwargs["allowed_tools"] == ["Read", "Edit"]

    def test_allowed_tools_without_explicit_tools(self):
        _, MockOptions, _, _ = self._build_with_env({
            "CLAUDE_ALLOWED_TOOLS": "Read,Glob",
        })
        options_kwargs = MockOptions.call_args[1]
        # tools defaults
        assert options_kwargs["tools"] == [
            "Bash", "Read", "Write", "Edit", "Glob", "Grep"
        ]
        # allowed_tools is the explicit override
        assert options_kwargs["allowed_tools"] == ["Read", "Glob"]

    def test_system_prompt_set(self):
        _, MockOptions, _, _ = self._build_with_env(
            {"CLAUDE_SYSTEM_PROMPT": "You are helpful."}
        )
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["system_prompt"] == "You are helpful."

    def test_system_prompt_empty_not_set(self):
        _, MockOptions, _, _ = self._build_with_env({})
        options_kwargs = MockOptions.call_args[1]
        assert "system_prompt" not in options_kwargs

    def test_max_turns(self):
        _, MockOptions, _, _ = self._build_with_env({"CLAUDE_MAX_TURNS": "10"})
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["max_turns"] == 10

    def test_hitl_true_with_no_timeout_uses_hitl_timeout(self):
        _, _, _, MockConfig = self._build_with_env({"CLAUDE_HITL": "true"})
        config_kwargs = MockConfig.call_args[1]
        assert config_kwargs["enable_hitl"] is True
        assert config_kwargs["execution_timeout"] == pytest.approx(600.0)

    def test_hitl_true_with_custom_hitl_timeout(self):
        _, _, _, MockConfig = self._build_with_env(
            {"CLAUDE_HITL": "true", "CLAUDE_HITL_TIMEOUT": "900"}
        )
        config_kwargs = MockConfig.call_args[1]
        assert config_kwargs["execution_timeout"] == pytest.approx(900.0)

    def test_hitl_true_with_explicit_timeout_uses_claude_timeout(self):
        _, _, _, MockConfig = self._build_with_env(
            {"CLAUDE_HITL": "true", "CLAUDE_TIMEOUT": "120"}
        )
        config_kwargs = MockConfig.call_args[1]
        assert config_kwargs["execution_timeout"] == pytest.approx(120.0)

    def test_streaming_disabled(self):
        _, _, _, MockConfig = self._build_with_env({"CLAUDE_STREAMING": "false"})
        config_kwargs = MockConfig.call_args[1]
        assert config_kwargs["enable_streaming"] is False

    def test_mcp_servers_added_to_options(self):
        mcp_config = json.dumps({"fetch": {"command": "npx", "args": ["server-fetch"]}})
        _, MockOptions, _, _ = self._build_with_env({"CLAUDE_MCP_SERVERS": mcp_config})

        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["mcp_servers"] == {
            "fetch": {"command": "npx", "args": ["server-fetch"]}
        }

    def test_mcp_servers_auto_approve_wildcards(self):
        mcp_config = json.dumps({
            "fetch": {"command": "npx"},
            "github": {"command": "gh"},
        })
        _, MockOptions, _, _ = self._build_with_env({"CLAUDE_MCP_SERVERS": mcp_config})

        options_kwargs = MockOptions.call_args[1]
        allowed = options_kwargs["allowed_tools"]
        # Base tools + auto-generated wildcards
        assert "mcp__fetch__*" in allowed
        assert "mcp__github__*" in allowed
        # Base tools still present
        assert "Bash" in allowed

    def test_allowed_mcp_tools_overrides_wildcard(self):
        mcp_config = json.dumps({"fetch": {"command": "npx"}})
        _, MockOptions, _, _ = self._build_with_env({
            "CLAUDE_MCP_SERVERS": mcp_config,
            "CLAUDE_ALLOWED_MCP_TOOLS": "mcp__fetch__get,mcp__fetch__post",
        })

        options_kwargs = MockOptions.call_args[1]
        allowed = options_kwargs["allowed_tools"]
        assert "mcp__fetch__get" in allowed
        assert "mcp__fetch__post" in allowed
        assert "mcp__fetch__*" not in allowed

    def test_skills_enabled_sets_cwd_and_setting_sources(self):
        _, MockOptions, _, _ = self._build_with_env({"CLAUDE_SKILLS": "true"})
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["cwd"] == "/app"
        assert options_kwargs["setting_sources"] == ["project"]
        assert options_kwargs["skills"] == "all"

    def test_skills_with_custom_cwd(self):
        _, MockOptions, _, _ = self._build_with_env({
            "CLAUDE_SKILLS": "true",
            "CLAUDE_CWD": "/workspace",
        })
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["cwd"] == "/workspace"

    def test_skills_filter(self):
        _, MockOptions, _, _ = self._build_with_env({
            "CLAUDE_SKILLS": "true",
            "CLAUDE_SKILLS_FILTER": "git,docker",
        })
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["skills"] == ["git", "docker"]

    def test_skills_disabled_by_default(self):
        _, MockOptions, _, _ = self._build_with_env({})
        options_kwargs = MockOptions.call_args[1]
        assert "cwd" not in options_kwargs
        assert "setting_sources" not in options_kwargs

    def test_agent_card_defaults(self):
        _, _, MockApp, _ = self._build_with_env({})
        app_kwargs = MockApp.call_args[1]
        card = app_kwargs["agent_card"]
        assert card.name == "claude-agent"
        assert card.description == "Claude-powered agent running on kagent"
        assert card.url == "http://localhost:8080/"

    def test_custom_agent_card(self):
        _, _, MockApp, _ = self._build_with_env({
            "AGENT_NAME": "my-agent",
            "AGENT_DESCRIPTION": "Custom agent",
            "AGENT_PORT": "9090",
        })
        app_kwargs = MockApp.call_args[1]
        card = app_kwargs["agent_card"]
        assert card.name == "my-agent"
        assert card.description == "Custom agent"
        assert card.url == "http://localhost:9090/"

    def test_tracing_enabled_by_default(self):
        _, _, MockApp, _ = self._build_with_env({})
        app_kwargs = MockApp.call_args[1]
        assert app_kwargs["tracing"] is True

    def test_tracing_disabled(self):
        _, _, MockApp, _ = self._build_with_env({"AGENT_TRACING": "false"})
        app_kwargs = MockApp.call_args[1]
        assert app_kwargs["tracing"] is False

    def test_returns_app_instance(self):
        result, _, MockApp, _ = self._build_with_env({})
        assert result is MockApp.return_value

    def test_model_set(self):
        _, MockOptions, _, _ = self._build_with_env({"CLAUDE_MODEL": "claude-sonnet-4-5"})
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["model"] == "claude-sonnet-4-5"

    def test_model_not_set_by_default(self):
        _, MockOptions, _, _ = self._build_with_env({})
        options_kwargs = MockOptions.call_args[1]
        assert "model" not in options_kwargs

    def test_fallback_model_set(self):
        _, MockOptions, _, _ = self._build_with_env(
            {"CLAUDE_FALLBACK_MODEL": "claude-haiku-4"}
        )
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["fallback_model"] == "claude-haiku-4"

    def test_fallback_model_not_set_by_default(self):
        _, MockOptions, _, _ = self._build_with_env({})
        options_kwargs = MockOptions.call_args[1]
        assert "fallback_model" not in options_kwargs

    def test_permission_mode_set(self):
        _, MockOptions, _, _ = self._build_with_env(
            {"CLAUDE_PERMISSION_MODE": "bypassPermissions"}
        )
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["permission_mode"] == "bypassPermissions"

    def test_permission_mode_case_insensitive(self):
        _, MockOptions, _, _ = self._build_with_env(
            {"CLAUDE_PERMISSION_MODE": "acceptedits"}
        )
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["permission_mode"] == "acceptEdits"

    def test_permission_mode_not_set_by_default(self):
        _, MockOptions, _, _ = self._build_with_env({})
        options_kwargs = MockOptions.call_args[1]
        assert "permission_mode" not in options_kwargs

    def test_permission_mode_invalid_ignored(self):
        _, MockOptions, _, _ = self._build_with_env(
            {"CLAUDE_PERMISSION_MODE": "badvalue"}
        )
        options_kwargs = MockOptions.call_args[1]
        assert "permission_mode" not in options_kwargs

    def test_max_budget_usd_set(self):
        _, MockOptions, _, _ = self._build_with_env({"CLAUDE_MAX_BUDGET_USD": "5.50"})
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["max_budget_usd"] == pytest.approx(5.50)

    def test_max_budget_usd_not_set_by_default(self):
        _, MockOptions, _, _ = self._build_with_env({})
        options_kwargs = MockOptions.call_args[1]
        assert "max_budget_usd" not in options_kwargs

    def test_max_budget_usd_zero_not_set(self):
        _, MockOptions, _, _ = self._build_with_env({"CLAUDE_MAX_BUDGET_USD": "0"})
        options_kwargs = MockOptions.call_args[1]
        assert "max_budget_usd" not in options_kwargs

    def test_effort_set(self):
        _, MockOptions, _, _ = self._build_with_env({"CLAUDE_EFFORT": "low"})
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["effort"] == "low"

    def test_effort_case_insensitive(self):
        _, MockOptions, _, _ = self._build_with_env({"CLAUDE_EFFORT": "HIGH"})
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["effort"] == "high"

    def test_effort_not_set_by_default(self):
        _, MockOptions, _, _ = self._build_with_env({})
        options_kwargs = MockOptions.call_args[1]
        assert "effort" not in options_kwargs

    def test_effort_invalid_ignored(self):
        _, MockOptions, _, _ = self._build_with_env({"CLAUDE_EFFORT": "turbo"})
        options_kwargs = MockOptions.call_args[1]
        assert "effort" not in options_kwargs

    def test_model_with_fallback_both_set(self):
        _, MockOptions, _, _ = self._build_with_env({
            "CLAUDE_MODEL": "claude-opus-4-5",
            "CLAUDE_FALLBACK_MODEL": "claude-sonnet-4-5",
        })
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["model"] == "claude-opus-4-5"
        assert options_kwargs["fallback_model"] == "claude-sonnet-4-5"

    def test_all_new_options_combined(self):
        _, MockOptions, _, _ = self._build_with_env({
            "CLAUDE_MODEL": "claude-sonnet-4-5",
            "CLAUDE_FALLBACK_MODEL": "claude-haiku-4",
            "CLAUDE_PERMISSION_MODE": "acceptEdits",
            "CLAUDE_MAX_BUDGET_USD": "10.0",
            "CLAUDE_EFFORT": "medium",
        })
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["model"] == "claude-sonnet-4-5"
        assert options_kwargs["fallback_model"] == "claude-haiku-4"
        assert options_kwargs["permission_mode"] == "acceptEdits"
        assert options_kwargs["max_budget_usd"] == pytest.approx(10.0)
        assert options_kwargs["effort"] == "medium"

    def test_disallowed_tools_set(self):
        _, MockOptions, _, _ = self._build_with_env(
            {"CLAUDE_DISALLOWED_TOOLS": "Bash,Write"}
        )
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["disallowed_tools"] == ["Bash", "Write"]

    def test_disallowed_tools_not_set_by_default(self):
        _, MockOptions, _, _ = self._build_with_env({})
        options_kwargs = MockOptions.call_args[1]
        assert "disallowed_tools" not in options_kwargs

    def test_disallowed_tools_single(self):
        _, MockOptions, _, _ = self._build_with_env(
            {"CLAUDE_DISALLOWED_TOOLS": "Bash"}
        )
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["disallowed_tools"] == ["Bash"]

    def test_add_dirs_set(self):
        _, MockOptions, _, _ = self._build_with_env(
            {"CLAUDE_ADD_DIRS": "/data/shared,/mnt/datasets"}
        )
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["add_dirs"] == ["/data/shared", "/mnt/datasets"]

    def test_add_dirs_not_set_by_default(self):
        _, MockOptions, _, _ = self._build_with_env({})
        options_kwargs = MockOptions.call_args[1]
        assert "add_dirs" not in options_kwargs

    def test_add_dirs_single_path(self):
        _, MockOptions, _, _ = self._build_with_env(
            {"CLAUDE_ADD_DIRS": "/data/shared"}
        )
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["add_dirs"] == ["/data/shared"]

    def test_strict_mcp_config_true(self):
        _, MockOptions, _, _ = self._build_with_env(
            {"CLAUDE_STRICT_MCP_CONFIG": "true"}
        )
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["strict_mcp_config"] is True

    def test_strict_mcp_config_not_set_by_default(self):
        _, MockOptions, _, _ = self._build_with_env({})
        options_kwargs = MockOptions.call_args[1]
        assert "strict_mcp_config" not in options_kwargs

    def test_strict_mcp_config_false_not_set(self):
        _, MockOptions, _, _ = self._build_with_env(
            {"CLAUDE_STRICT_MCP_CONFIG": "false"}
        )
        options_kwargs = MockOptions.call_args[1]
        assert "strict_mcp_config" not in options_kwargs

    def test_security_hardened_agent(self):
        """Integration test: a fully locked-down read-only agent."""
        _, MockOptions, _, _ = self._build_with_env({
            "CLAUDE_TOOLS": "Read,Glob,Grep",
            "CLAUDE_ALLOWED_TOOLS": "Read,Glob",
            "CLAUDE_DISALLOWED_TOOLS": "Bash,Write,Edit",
            "CLAUDE_PERMISSION_MODE": "dontAsk",
            "CLAUDE_STRICT_MCP_CONFIG": "true",
            "CLAUDE_MAX_BUDGET_USD": "2.0",
        })
        options_kwargs = MockOptions.call_args[1]
        assert options_kwargs["tools"] == ["Read", "Glob", "Grep"]
        assert options_kwargs["allowed_tools"] == ["Read", "Glob"]
        assert options_kwargs["disallowed_tools"] == ["Bash", "Write", "Edit"]
        assert options_kwargs["permission_mode"] == "dontAsk"
        assert options_kwargs["strict_mcp_config"] is True
        assert options_kwargs["max_budget_usd"] == pytest.approx(2.0)

"""
kagent-claude golden image entrypoint.

A fully env-configurable Claude agent server for the kagent platform.
No Python required — configure everything via environment variables.

Environment Variables:
    ANTHROPIC_API_KEY       Required. Claude API key.
    KAGENT_URL              Auto-injected by kagent controller.
    KAGENT_NAME             Auto-injected by kagent controller.
    KAGENT_NAMESPACE        Auto-injected by kagent controller.

    CLAUDE_TOOLS            Comma-separated tool list.
                            Default: Bash,Read,Write,Edit,Glob,Grep
    CLAUDE_SYSTEM_PROMPT    System prompt for Claude. Default: none.
    CLAUDE_MAX_TURNS        Max turns before Claude stops. Default: 25.
    CLAUDE_TIMEOUT          Execution timeout in seconds. Default: 300.
    CLAUDE_STREAMING        Stream intermediate events. Default: true.
    CLAUDE_HITL             Enable HITL tool approval. Default: false.
    CLAUDE_HITL_TIMEOUT     HITL-specific timeout (overrides CLAUDE_TIMEOUT
                            when HITL is enabled). Default: 600.
    CLAUDE_MCP_SERVERS      JSON object mapping server names to their config.
                            Supports both stdio servers (command/args) and
                            remote HTTP/SSE servers (type/url/headers).
                            Values in the config that look like $ENV_VAR are
                            resolved against the pod environment at startup.
                            Examples:
                              Stdio:  {"gh": {"command": "npx",
                                "args": ["@modelcontextprotocol/server-github"],
                                "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}}}
                              HTTP:   {"fetch": {"type": "http",
                                "url": "http://mcp-server.svc/mcp"}}
                            Default: none (no MCP servers).
    CLAUDE_ALLOWED_MCP_TOOLS
                            Comma-separated MCP tool patterns to auto-approve.
                            Default: all tools from all configured servers
                            (mcp__<server-name>__* for each server).
                            Example: "mcp__fetch__*,mcp__github__list_issues"
    CLAUDE_SKILLS           Enable skill discovery. Default: false.
                            Mount skills via ConfigMap at
                            /app/.claude/skills/<name>/SKILL.md
    CLAUDE_SKILLS_FILTER    Comma-separated list of skill names to enable.
                            Default: all discovered skills.
    CLAUDE_CWD              Working directory for skill discovery.
                            Default: /app.

    AGENT_NAME              Agent card name. Default: claude-agent.
    AGENT_DESCRIPTION       Agent card description.
                            Default: Claude-powered agent running on kagent.
    AGENT_VERSION           Agent card version. Default: package version.
    AGENT_SKILLS            JSON array of skill objects. Each object should
                            have: id, name, description, tags (list), and
                            optionally examples (list).
                            Default: a single "general" skill.
    AGENT_PORT              Port to listen on. Default: 8080.
    AGENT_TRACING           Enable OpenTelemetry tracing. Default: true.
"""

import json
import logging
import os
import re

from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from claude_agent_sdk import ClaudeAgentOptions

from kagent.claude import ClaudeAgentExecutorConfig, KAgentApp

logger = logging.getLogger("kagent.claude.server")


def _env(key: str, default: str = "") -> str:
    """Read an environment variable with a default."""
    return os.environ.get(key, default).strip()


def _env_bool(key: str, default: bool = False) -> bool:
    """Read a boolean environment variable."""
    val = _env(key, str(default)).lower()
    return val in ("true", "1", "yes", "on")


def _env_int(key: str, default: int = 0) -> int:
    """Read an integer environment variable."""
    val = _env(key, str(default))
    try:
        return int(val)
    except ValueError:
        logger.warning(f"Invalid integer for {key}={val!r}, using default {default}")
        return default


def _env_float(key: str, default: float = 0.0) -> float:
    """Read a float environment variable."""
    val = _env(key, str(default))
    try:
        return float(val)
    except ValueError:
        logger.warning(f"Invalid float for {key}={val!r}, using default {default}")
        return default


def _parse_tools(val: str) -> list[str]:
    """Parse a comma-separated tool list."""
    if not val:
        return ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
    return [t.strip() for t in val.split(",") if t.strip()]


# Matches $VAR_NAME or ${VAR_NAME} (not escaped with $$)
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _interpolate_env_vars(value):
    """Recursively resolve $VAR and ${VAR} references against os.environ.

    Works on strings, lists, and nested dicts. Non-string leaves are
    returned unchanged. A literal ``$$`` is collapsed to ``$``.
    """
    if isinstance(value, str):
        # Collapse escaped $$
        result = value.replace("$$", "\x00")
        # Replace $VAR / ${VAR} with env value (empty string if unset)
        result = _ENV_VAR_PATTERN.sub(
            lambda m: os.environ.get(m.group(1) or m.group(2), ""), result
        )
        return result.replace("\x00", "$")
    if isinstance(value, dict):
        return {k: _interpolate_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env_vars(item) for item in value]
    return value


def _parse_mcp_servers(val: str) -> dict | None:
    """Parse MCP server config from JSON with env var interpolation.

    Returns a dict suitable for ``ClaudeAgentOptions(mcp_servers=...)``,
    or None if no MCP servers are configured.

    String values containing ``$VAR`` or ``${VAR}`` are resolved against
    the pod environment. This lets secrets stay in Kubernetes Secrets:

        CLAUDE_MCP_SERVERS='{"github": {"command": "npx",
          "args": ["@modelcontextprotocol/server-github"],
          "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}}}'

    The ``GITHUB_TOKEN`` env var is injected by the controller from a
    Secret, and the MCP config picks it up at startup.
    """
    if not val:
        return None
    try:
        raw = json.loads(val)
        if not isinstance(raw, dict):
            logger.warning("CLAUDE_MCP_SERVERS must be a JSON object, got %s", type(raw).__name__)
            return None
        resolved = _interpolate_env_vars(raw)
        logger.info("MCP servers configured: %s", list(resolved.keys()))
        return resolved
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("Failed to parse CLAUDE_MCP_SERVERS: %s", e)
        return None


def _parse_skills(val: str) -> list[AgentSkill]:
    """Parse skills from JSON or return a sensible default."""
    if not val:
        return [
            AgentSkill(
                id="general",
                name="General assistance",
                description="A general-purpose Claude agent for coding, analysis, and research",
                tags=["coding", "analysis", "research"],
                examples=[
                    "What files are in this directory?",
                    "Find all TODO comments in the codebase",
                    "Explain how the authentication module works",
                ],
            )
        ]

    try:
        raw = json.loads(val)
        if not isinstance(raw, list):
            raw = [raw]
        skills = []
        for item in raw:
            skills.append(
                AgentSkill(
                    id=item.get("id", "skill"),
                    name=item.get("name", "Skill"),
                    description=item.get("description", ""),
                    tags=item.get("tags", []),
                    examples=item.get("examples", []),
                )
            )
        return skills
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        logger.warning(f"Failed to parse AGENT_SKILLS: {e}. Using default skill.")
        return _parse_skills("")


def build_app() -> KAgentApp:
    """Build a KAgentApp from environment variables."""
    # --- Claude SDK options ---
    tools = _parse_tools(_env("CLAUDE_TOOLS"))
    system_prompt = _env("CLAUDE_SYSTEM_PROMPT") or None
    max_turns = _env_int("CLAUDE_MAX_TURNS", 25)

    options_kwargs: dict = {"allowed_tools": tools}
    if system_prompt:
        options_kwargs["system_prompt"] = system_prompt
    if max_turns > 0:
        options_kwargs["max_turns"] = max_turns

    # MCP servers
    mcp_servers = _parse_mcp_servers(_env("CLAUDE_MCP_SERVERS"))
    if mcp_servers:
        options_kwargs["mcp_servers"] = mcp_servers
        # Auto-approve MCP tools. CLAUDE_ALLOWED_MCP_TOOLS can be:
        #   - empty/unset: auto-approve all tools from all configured servers (mcp__name__*)
        #   - comma-separated: explicit tool patterns (e.g., "mcp__fetch__*,mcp__github__list_issues")
        mcp_tool_patterns = _env("CLAUDE_ALLOWED_MCP_TOOLS")
        if mcp_tool_patterns:
            mcp_tools = [t.strip() for t in mcp_tool_patterns.split(",") if t.strip()]
        else:
            # Default: wildcard for every configured server
            mcp_tools = [f"mcp__{name}__*" for name in mcp_servers]
        options_kwargs["allowed_tools"] = tools + mcp_tools

    # Skills — discovered from .claude/skills/ in CLAUDE_CWD (default: /app)
    # Mount skill files via ConfigMap at /app/.claude/skills/<name>/SKILL.md
    claude_cwd = _env("CLAUDE_CWD", "/app")
    enable_skills = _env_bool("CLAUDE_SKILLS", False)
    if enable_skills:
        options_kwargs["cwd"] = claude_cwd
        options_kwargs["setting_sources"] = ["project"]
        # Enable all discovered skills, or a specific comma-separated list
        skills_filter = _env("CLAUDE_SKILLS_FILTER")
        if skills_filter:
            options_kwargs["skills"] = [s.strip() for s in skills_filter.split(",") if s.strip()]
        else:
            options_kwargs["skills"] = "all"

    options = ClaudeAgentOptions(**options_kwargs)

    # --- Executor config ---
    enable_hitl = _env_bool("CLAUDE_HITL", False)
    enable_streaming = _env_bool("CLAUDE_STREAMING", True)

    # Use HITL-specific timeout if HITL is enabled and no explicit timeout set
    if enable_hitl and not _env("CLAUDE_TIMEOUT"):
        timeout = _env_float("CLAUDE_HITL_TIMEOUT", 600.0)
    else:
        timeout = _env_float("CLAUDE_TIMEOUT", 300.0)

    executor_config = ClaudeAgentExecutorConfig(
        execution_timeout=timeout,
        enable_streaming=enable_streaming,
        enable_hitl=enable_hitl,
    )

    # --- Agent card ---
    agent_name = _env("AGENT_NAME", "claude-agent")
    agent_description = _env(
        "AGENT_DESCRIPTION", "Claude-powered agent running on kagent"
    )

    # Try to get version from package metadata
    try:
        from kagent.claude import __version__

        default_version = __version__
    except Exception:
        default_version = "0.0.0"
    agent_version = _env("AGENT_VERSION", default_version)

    skills = _parse_skills(_env("AGENT_SKILLS"))
    port = _env_int("AGENT_PORT", 8080)

    agent_card = AgentCard(
        name=agent_name,
        description=agent_description,
        url=f"http://localhost:{port}/",
        version=agent_version,
        capabilities=AgentCapabilities(streaming=enable_streaming),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=skills,
    )

    enable_tracing = _env_bool("AGENT_TRACING", True)

    app = KAgentApp(
        options=options,
        agent_card=agent_card,
        executor_config=executor_config,
        tracing=enable_tracing,
    )

    # Log the configuration for visibility
    mcp_names = list(mcp_servers.keys()) if mcp_servers else []
    skills_info = options_kwargs.get("skills", "disabled")
    logger.info(
        f"kagent-claude server configured: "
        f"name={agent_name} tools={tools} hitl={enable_hitl} "
        f"streaming={enable_streaming} timeout={timeout}s "
        f"max_turns={max_turns} tracing={enable_tracing} "
        f"mcp_servers={mcp_names} skills={skills_info}"
    )

    return app


def main():
    """Entry point for the golden image."""
    port = _env_int("AGENT_PORT", 8080)
    app = build_app()
    app.run(port=port)


if __name__ == "__main__":
    main()

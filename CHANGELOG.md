# Changelog

All notable changes to `kagent-claude` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Golden image** (`ghcr.io/ganttastic/kagent-claude`) — fully env-configurable Claude agent server. Deploy to kagent with zero Python, zero Docker builds — just a YAML file.
- `CLAUDE_MCP_SERVERS` env var for configuring MCP servers via JSON with `$VAR` interpolation — secrets stay in Kubernetes Secrets. Supports both stdio (command/args) and remote HTTP/SSE (type/url/headers) transports.
- `CLAUDE_ALLOWED_MCP_TOOLS` env var for controlling which MCP tools are auto-approved. Defaults to wildcard for all configured servers.
- `CLAUDE_SKILLS` env var to enable Claude Agent SDK skill discovery from `.claude/skills/`. Mount skills via Kubernetes ConfigMap at `/app/.claude/skills/<name>/SKILL.md`.
- `CLAUDE_SKILLS_FILTER` env var to enable only specific skills by name.
- `CLAUDE_CWD` env var to set the working directory for skill discovery.
- `kagent-claude-server` console script and `kagent.claude.server` module for the golden image entrypoint
- `server.py` module with `build_app()` for env-var-driven configuration
- `Dockerfile` at repo root for building the golden image
- `.dockerignore` for clean build context
- `examples/agent-hitl.yaml` — zero-code HITL agent CRD
- GitHub Actions CI: lint + test on PR, build and push golden image to GHCR on main/tags
- `SessionStore` protocol for pluggable session persistence (Redis, database, etc.)
- LRU eviction on `ClaudeSessionStore` (default 1024 sessions) to prevent unbounded memory growth
- Max concurrent HITL queries guard (`MAX_CONCURRENT_HITL_QUERIES = 100`)
- Tests for streaming execution path, HITL execution path, and session store LRU behavior
- Shared `conftest.py` with reusable test fixtures
- `CHANGELOG.md`

### Changed
- **Breaking:** `ClaudeExecutorConfig` renamed to `ClaudeAgentExecutorConfig` for ecosystem consistency with `kagent-crewai` and `kagent-langgraph`
- **Breaking:** Deprecated `enable_hitl` kwarg removed from `KAgentApp` constructor — use `executor_config=ClaudeAgentExecutorConfig(enable_hitl=True)` instead
- `ClaudeAgentExecutor.session_store` now typed against `SessionStore` protocol instead of concrete `ClaudeSessionStore`
- HITL wait loop replaced with `asyncio.wait()` instead of 50ms polling (reduced CPU overhead)
- `cancel()` no longer does partial cleanup before raising `NotImplementedError`
- Options copying uses `_public_attrs()` helper instead of raw `__dict__` spreading (filters out private attributes)
- Error metadata keys normalized to `kagent.claude.*` namespace (was `kagent.*` in `_error_mappings.py`)
- `__version__` sourced from `importlib.metadata` instead of hardcoded string

### Fixed
- `import asyncio` moved to top of `_error_mappings.py` (was at bottom behind `# noqa: E402`)
- `a2a-sdk` pinned to `<1.0.0` — v1.x breaks `kagent-core` compatibility (removed `A2AStarletteApplication`, renamed `DataPart`)

## [0.2.0] - 2026-06-01

### Added
- `ClaudeExecutorConfig` dataclass for runtime behavior configuration
- Execution timeout with `asyncio.wait_for()` (default 300s)
- Streaming intermediate events (tool calls, tool results) to kagent dashboard
- Graceful shutdown via `ClaudeAgentExecutor.shutdown()`
- Rich metadata utilities (`_metadata_utils.py`) for A2A events
- Error classification module (`_error_mappings.py`) with user-friendly messages
- Ask-user answer extraction support
- `py.typed` PEP 561 marker
- Comprehensive examples: `basic.py`, `hitl.py`, `custom_config.py`
- Makefile with development task targets

### Changed
- Consolidated `deploy/` directory into `examples/`
- Switched to kagent-core HITL utilities and constants
- Updated BYO Agent CRD to `v1alpha2` format

## [0.1.0] - 2026-05-15

### Added
- Initial release
- `KAgentApp` entrypoint for A2A server assembly
- `ClaudeAgentExecutor` implementing A2A `AgentExecutor` interface
- `ClaudeSessionStore` for contextId to session_id mapping
- Human-in-the-Loop (HITL) tool approval via `HitlBridge`
- OpenTelemetry tracing integration
- Kubernetes deployment with Dockerfile and Agent CRD
- Unit tests for session store, executor, and text extraction

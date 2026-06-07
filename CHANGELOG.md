# Changelog

All notable changes to `kagent-claude` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.15] - 2026-06-07

### Added
- **Golden image** (`ghcr.io/ganttastic/kagent-claude`) — fully env-configurable Claude agent server. Deploy to kagent with zero Python, zero Docker builds — just a YAML file.
- **HITL via PreToolUse hooks** — replaces broken `can_use_tool` approach. Works with the CLI subprocess transport. Respects `allowed_tools` (auto-approves known tools, only prompts for unknown ones).
- **Dashboard tool call cards** — PreToolUse/PostToolUse hooks emit `function_call` and `function_response` DataParts that the kagent dashboard renders as live tool execution cards.
- **Artifact history** — final `TaskArtifactUpdateEvent` includes accumulated tool call/result parts, enabling page refresh to show full execution history.
- `CLAUDE_MCP_SERVERS` env var for configuring MCP servers via JSON with `$VAR` interpolation. Supports both stdio (command/args) and remote HTTP/SSE (type/url/headers) transports.
- `CLAUDE_ALLOWED_MCP_TOOLS` env var for controlling which MCP tools are auto-approved. Defaults to wildcard for all configured servers.
- `CLAUDE_SKILLS` env var to enable Claude Agent SDK skill discovery. Mount skills via Kubernetes ConfigMap at `/app/.claude/skills/<name>/SKILL.md`.
- `CLAUDE_SKILLS_FILTER` and `CLAUDE_CWD` env vars for skill configuration.
- `kagent-claude-server` console script and `kagent.claude.server` module for the golden image entrypoint.
- `Dockerfile` at repo root with `VERSION` build-arg for hatch-vcs.
- `.dockerignore` for clean build context.
- `examples/agent-hitl.yaml` — zero-code HITL agent CRD.
- GitHub Actions CI: lint + test on PR, build and push image to GHCR on main/tags, publish to PyPI on version tags (Trusted Publisher/OIDC).
- `SessionStore` protocol for pluggable session persistence (Redis, database, etc.).
- LRU eviction on `ClaudeSessionStore` (default 1024 sessions).
- Max concurrent HITL queries guard (`MAX_CONCURRENT_HITL_QUERIES = 100`).
- Tests for streaming, HITL execution, session store LRU, and protocol conformance (83 tests total).
- Shared `conftest.py` with reusable test fixtures.
- `CHANGELOG.md`.

### Changed
- **Breaking:** `ClaudeExecutorConfig` renamed to `ClaudeAgentExecutorConfig` for ecosystem consistency.
- **Breaking:** Deprecated `enable_hitl` kwarg removed from `KAgentApp` constructor — use `executor_config=ClaudeAgentExecutorConfig(enable_hitl=True)` instead.
- `ClaudeAgentExecutor.session_store` typed against `SessionStore` protocol instead of concrete class.
- HITL implementation uses PreToolUse hooks (not `can_use_tool` which requires `AsyncIterable` prompt incompatible with CLI transport).
- HITL resume path does not emit premature `working` event — keeps A2A event queue open for the next `input_required` or `completed`.
- `hitl_event` cleared before re-entering wait loop on resume to prevent stale phantom approvals.
- DataPart metadata uses prefixed keys (`kagent_type`, `kagent_is_long_running`) matching kagent dashboard expectations.
- `cancel()` no longer does partial cleanup before raising `NotImplementedError`.
- Options copying uses `_public_attrs()` helper instead of raw `__dict__` spreading.
- Error metadata keys normalized to `kagent.claude.*` namespace.
- `__version__` sourced from `importlib.metadata`; package version derived from git tags via `hatch-vcs`.
- Upper-bound version pin restored on `a2a-sdk` (`<1.0.0`) due to incompatible v1.x changes.

### Fixed
- `import asyncio` moved to top of `_error_mappings.py`.
- `a2a-sdk` pinned to `<1.0.0` — v1.x breaks `kagent-core` (removed `A2AStarletteApplication`, renamed `DataPart`).
- Docker build passes `VERSION` build-arg via `SETUPTOOLS_SCM_PRETEND_VERSION` for hatch-vcs without `.git`.
- Removed `[tool.uv.sources]` workspace directive that broke CI installs.

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

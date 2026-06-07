from importlib.metadata import PackageNotFoundError, version

from ._a2a import KAgentApp
from ._executor import ClaudeAgentExecutor, ClaudeAgentExecutorConfig
from ._hitl import ApprovalDecision, HitlBridge
from ._session_store import ClaudeSessionStore, SessionStore
from ._tracing import trace_query

__all__ = [
    "KAgentApp",
    "ClaudeAgentExecutor",
    "ClaudeAgentExecutorConfig",
    "ClaudeSessionStore",
    "SessionStore",
    "HitlBridge",
    "ApprovalDecision",
    "trace_query",
]

try:
    __version__ = version("kagent-claude")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

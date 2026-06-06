"""KAgent Claude Agent SDK A2A Server Integration."""

import faulthandler
import logging

import httpx
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import AgentCard
from claude_agent_sdk import ClaudeAgentOptions
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from kagent.core import KAgentConfig, configure_logging, configure_tracing
from kagent.core.a2a import (
    KAgentRequestContextBuilder,
    KAgentTaskStore,
    get_a2a_max_content_length,
)

from ._executor import ClaudeAgentExecutor
from ._session_store import ClaudeSessionStore

logger = logging.getLogger(__name__)


def _health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


def _thread_dump(request: Request) -> PlainTextResponse:
    import tempfile

    with tempfile.TemporaryFile(mode="w+") as tmp:
        faulthandler.dump_traceback(file=tmp, all_threads=True)
        tmp.seek(0)
        return PlainTextResponse(tmp.read())


class KAgentApp:
    """
    Builds an A2A-compliant HTTP server wrapping the Claude Agent SDK.

    Usage:
        app = KAgentApp(
            options=ClaudeAgentOptions(allowed_tools=["Bash", "Read"]),
            agent_card=AgentCard(...),
            config=KAgentConfig(),  # reads from KAGENT_URL, KAGENT_NAME, KAGENT_NAMESPACE env vars
        )
        app.run()
    """

    def __init__(
        self,
        *,
        options: ClaudeAgentOptions,
        agent_card: AgentCard,
        config: KAgentConfig = None,
        tracing: bool = True,
        enable_hitl: bool = False,
    ):
        self._options = options
        self.agent_card = AgentCard.model_validate(agent_card)
        self.config = config or KAgentConfig()
        self._enable_tracing = tracing
        self._enable_hitl = enable_hitl
        self._session_store = ClaudeSessionStore()

    def build(self) -> FastAPI:
        """Construct and return the FastAPI ASGI application."""
        http_client = httpx.AsyncClient(base_url=self.config.url)

        agent_executor = ClaudeAgentExecutor(
            options=self._options,
            session_store=self._session_store,
            app_name=self.config.app_name,
            enable_hitl=self._enable_hitl,
        )

        task_store = KAgentTaskStore(http_client)
        request_context_builder = KAgentRequestContextBuilder(task_store=task_store)
        request_handler = DefaultRequestHandler(
            agent_executor=agent_executor,
            task_store=task_store,
            request_context_builder=request_context_builder,
        )

        max_content_length = get_a2a_max_content_length()
        a2a_app = A2AStarletteApplication(
            agent_card=self.agent_card,
            http_handler=request_handler,
            max_content_length=max_content_length,
        )

        faulthandler.enable()
        app = FastAPI(
            title=f"KAgent Claude: {self.config.app_name}",
            description=f"Claude Agent SDK with KAgent integration: {self.agent_card.description}",
            version=self.agent_card.version,
        )

        configure_logging()

        if self._enable_tracing:
            try:
                configure_tracing(self.config.name, self.config.namespace, app)
            except Exception:
                logger.exception("Failed to configure tracing")

        app.add_route("/health", methods=["GET"], route=_health_check)
        app.add_route("/thread_dump", methods=["GET"], route=_thread_dump)
        a2a_app.add_routes_to_app(app)

        return app

    def run(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Start the uvicorn server. Blocks until shutdown."""
        import uvicorn

        uvicorn.run(self.build(), host=host, port=port)

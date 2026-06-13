"""OpenTelemetry tracing for the Claude Agent SDK executor."""

from contextlib import asynccontextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import StatusCode

TRACER_NAME = "kagent.claude"

_tracer = trace.get_tracer(TRACER_NAME)


@asynccontextmanager
async def trace_query(
    prompt: str,
    session_id: str | None,
    context_id: str | None,
    app_name: str,
    model: str | None = None,
):
    """
    Creates a span around the full Claude Agent SDK query() call.

    Attributes follow OpenTelemetry semantic conventions for GenAI:
    https://opentelemetry.io/docs/specs/semconv/gen-ai/
    """
    request_model = model or "claude-agent-sdk"
    with _tracer.start_as_current_span(
        "claude.query",
        kind=trace.SpanKind.CLIENT,
        attributes={
            "gen_ai.system": "claude",
            "gen_ai.operation.name": "query",
            "gen_ai.request.model": request_model,
            "kagent.app_name": app_name,
            "kagent.context_id": context_id or "",
            "kagent.session.resume": session_id or "",
            "gen_ai.prompt": prompt[:1000],  # truncate for safety
        },
    ) as span:
        try:
            yield span
        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            span.record_exception(e)
            raise


def record_message_event(span: trace.Span, message: Any, index: int) -> None:
    """Record a Claude SDK message as a span event."""
    msg_type = type(message).__name__
    attributes: dict[str, Any] = {
        "message.index": index,
        "message.type": msg_type,
    }

    if hasattr(message, "subtype"):
        attributes["message.subtype"] = message.subtype

    if hasattr(message, "result") and message.result:
        # Truncate result in span event to avoid blowing up trace storage
        attributes["message.result_length"] = len(message.result)
        attributes["message.result_preview"] = message.result[:200]

    span.add_event(f"claude.message.{msg_type}", attributes=attributes)


def record_completion(
    span: trace.Span,
    session_id: str | None,
    total_messages: int,
    result_length: int,
    model: str | None = None,
) -> None:
    """Record completion metrics on the query span."""
    response_model = model or "claude-agent-sdk"
    span.set_attributes({
        "gen_ai.response.model": response_model,
        "kagent.session.id": session_id or "",
        "kagent.messages.total": total_messages,
        "kagent.result.length": result_length,
    })
    span.set_status(StatusCode.OK)

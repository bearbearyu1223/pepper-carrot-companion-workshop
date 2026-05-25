"""Chat orchestration — assembles retrieval + prompt + a streamed model call.

`ChatOrchestrator.stream_response()` is the single entry point: it yields
SSE-shaped `token` / `done` / `error` events and generates the follow-up
suggestion chips. (Post 6 answered in one shot; Post 7 made it stream.)
"""

from app.orchestration.chat import ChatOrchestrator, SessionNotFoundError

__all__ = ["ChatOrchestrator", "SessionNotFoundError"]

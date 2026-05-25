"""Chat orchestration — assembles retrieval + prompt + model call into an answer.

`ChatOrchestrator` is the single entry point. Post 6 answers in one shot
(`answer()`); Post 7 turns this into a token stream and adds suggestion chips.
"""

from app.orchestration.chat import AnswerResult, ChatOrchestrator, SessionNotFoundError

__all__ = ["AnswerResult", "ChatOrchestrator", "SessionNotFoundError"]

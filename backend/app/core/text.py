"""Markdown-stripping for text on its way into a chat prompt.

The page descriptions written by the `ingest-from-images` skill and the wiki
seed articles are both markdown-heavy at the source — they carry `**bold**` for
proper nouns, `### headers`, `- bullets`, and so on. Small chat models mirror
whatever formatting they see in context, so an essay question reliably comes
back as a four-section essay. We strip the formatting characters before the
model sees them; the text content survives, only the markers disappear. The
frontend separately renders any markdown the model *does* emit as a safety net
(Post 8), so the discipline is in both places.

Lives in `core/` (not `orchestration/`) because two callers apply it — the chat
orchestrator during prompt assembly and the retrieval text-fetch
(`retrieval.service.fetch_chunk_text`) — and `service.py` cannot import from
`orchestration/` without an import cycle.
"""

from __future__ import annotations

import re

_MARKDOWN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\*\*([^*\n]+?)\*\*"), r"\1"),                # **bold**
    (re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)"), r"\1"),       # *italic*
    (re.compile(r"__([^_\n]+?)__"), r"\1"),                    # __bold__
    (re.compile(r"(?<!_)_([^_\n]+?)_(?!_)"), r"\1"),           # _italic_
    (re.compile(r"`([^`\n]+?)`"), r"\1"),                      # `code`
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),             # # headers
    (re.compile(r"^\s*[-*•]\s+", re.MULTILINE), ""),           # - bullets
    (re.compile(r"^\s*\d+\.\s+", re.MULTILINE), ""),           # 1. numbered
    (re.compile(r"^\s*>\s?", re.MULTILINE), ""),               # > blockquotes
    (re.compile(r"^\s*-{3,}\s*$", re.MULTILINE), ""),          # --- rules
    (re.compile(r"\n{3,}"), "\n\n"),                           # collapse blank runs
)


def strip_markdown(text: str) -> str:
    """Remove markdown formatting so the chat model sees plain prose.

    Applied to every piece of text that ends up in the user-turn prompt:
    `episode.plot_summary`, `page.visual_description`, `page.ocr_text`, each
    retrieved page's description, and each retrieved wiki article's content.
    """
    for pattern, replacement in _MARKDOWN_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()

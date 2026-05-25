"""System prompts for the chat companion.

Every chat system prompt lives here. Never inline a prompt in a route or a
service (CLAUDE.md convention 3) — keeping them in one module makes the
behavior easy to read, diff, and tune.

Post 6 ships a single prompt, `PAGE_MODE_SYSTEM`, for page-grounded questions.
Post 7 adds `WIKI_MODE_SYSTEM` (and reuses the shared blocks below), and Post 8
expands both with the stricter formatting rules the production prompts carry.
The prompt is deliberately short here: this post is about the *retrieval*
boundary, and the prompt's spoiler rule is a backstop, not the enforcement.
"""

from __future__ import annotations

_SHARED_VOICE = """\
You are a warm, slightly playful reading companion for *Pepper&Carrot*, the \
open-source webcomic by David Revoy. You read along with the user like a \
thoughtful friend — not a corporate AI assistant.
"""

_SPOILER_DISCIPLINE = """\
The user is on episode {episode_number}, page {current_page} (titled \
"{episode_title}"). Never reveal events from later pages or later episodes, \
even if asked directly. If the user pushes for what happens next, gently say \
you'd rather not spoil it and suggest they read on.

You don't have to police this alone: the retrieval layer underneath you only \
ever hands you pages the reader has already passed. If a detail isn't in your \
notes, the reader hasn't reached it yet.
"""

_GROUNDING_CONTRACT = """\
The notes in the user message — the "Current page" and "Reference context" \
sections — are your only source of truth about *Pepper&Carrot*. You may have \
seen this comic during training; ignore that. If a character, place, or event \
isn't in the notes, say the comic hasn't shown it rather than inventing a \
plausible-sounding answer. Admitting "the page doesn't show that" is always \
better than making something up.
"""

_RESPONSE_FORMAT = """\
Keep answers short and conversational: at most four sentences, plain prose, no \
headers or bullet lists, and no "Certainly!"-style preamble. Lead with the \
answer itself.
"""


PAGE_MODE_SYSTEM = (
    _SHARED_VOICE
    + "\n"
    + _SPOILER_DISCIPLINE
    + "\n"
    + _GROUNDING_CONTRACT
    + "\n"
    + _RESPONSE_FORMAT
)


def render_system_prompt(
    *,
    episode_number: int,
    episode_title: str,
    current_page: int,
) -> str:
    """Render `PAGE_MODE_SYSTEM` with the reader's current position interpolated.

    Post 7 grows a `mode` parameter here when wiki mode arrives; for now there
    is one mode, so the signature stays flat.
    """
    return PAGE_MODE_SYSTEM.format(
        episode_number=episode_number,
        episode_title=episode_title,
        current_page=current_page,
    )

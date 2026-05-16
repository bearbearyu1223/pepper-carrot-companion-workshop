"""Vision client interface and implementations.

Used by the ingestion pipeline to obtain a `PageDescription` for each page.

Page descriptions are sourced from JSON files written next to each page image
by the `ingest-from-images` Claude Code skill (see
`.claude/skills/ingest-from-images/SKILL.md`). The skill walks the model
through reading each image and writing a structured `PageDescription` JSON
that this client then loads into the pipeline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class DialogueLine(BaseModel):
    speaker: str | None  # canonical character name if identifiable
    text: str


class PageDescription(BaseModel):
    """Structured description of one page, populated upstream by the skill."""

    visual_description: str  # 3-5 sentences of flowing prose
    dialogue: list[DialogueLine]
    characters_present: list[str]
    locations_or_concepts: list[str]
    mood_tags: list[str]


class VisionClient(Protocol):
    async def describe_page(
        self,
        image_path: Path,
        previous_page_description: str | None,
        cast_list: list[str],
    ) -> PageDescription:
        """Return the description for the page at `image_path`."""
        ...

    async def answer_about_page(
        self,
        image_path: Path,
        prompt: str,
    ) -> str:
        """One-shot multimodal answer about an image. Optional capability."""
        ...


# ─────────────────────────────────────────────────────────────────────────────
#                       JSON file implementation (skill-fed)
# ─────────────────────────────────────────────────────────────────────────────


class JsonFileVisionClient:
    """Reads pre-written `PageDescription` JSON files from disk.

    For each image at `path/page_NNN.jpg` (or any extension), expects a
    sibling file at `path/page_NNN.json` containing a serialised
    `PageDescription` (visual_description, dialogue, characters_present,
    locations_or_concepts, mood_tags). Works as a drop-in vision provider
    so the rest of the ingestion pipeline (image processing, storage,
    DB upsert, Chroma, plot summary) is unchanged.

    The companion JSON files are produced by the `ingest-from-images`
    Claude Code skill — Claude reads each page image visually and writes
    the structured description out as JSON, which this client then
    consumes. This keeps page-description quality high without depending
    on a local VLM or paying for a vision API.

    Ingestion-only: `answer_about_page` raises NotImplementedError because
    runtime page-Q&A would need a real model behind it. The chat layer
    today doesn't need it (it operates purely on retrieved text); if that
    ever changes, add a separate provider for runtime vision.
    """

    def __init__(self) -> None:
        # No state — descriptions live next to their images on disk.
        pass

    async def aclose(self) -> None:
        # No resources to release.
        pass

    async def describe_page(
        self,
        image_path: Path,
        previous_page_description: str | None,
        cast_list: list[str],
    ) -> PageDescription:
        # cast_list and previous_page_description are part of the Protocol
        # contract but unused here — the JSON file is the source of truth.
        del previous_page_description, cast_list

        json_path = image_path.with_suffix(".json")
        if not json_path.is_file():
            raise FileNotFoundError(
                f"No description JSON found at {json_path}. "
                f"JsonFileVisionClient expects each image to have a sibling .json "
                f"file containing a serialised PageDescription. Run the "
                f"`ingest-from-images` Claude Code skill against this episode "
                f"first to generate them."
            )
        try:
            return PageDescription.model_validate_json(json_path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise RuntimeError(
                f"Description at {json_path} did not validate against PageDescription: "
                f"{exc}"
            ) from exc

    async def answer_about_page(self, image_path: Path, prompt: str) -> str:
        raise NotImplementedError(
            "JsonFileVisionClient is for ingestion only — it has no model behind it. "
            "Runtime page Q&A would need a separate vision provider; the chat layer "
            "today operates on retrieved text and doesn't call this method."
        )

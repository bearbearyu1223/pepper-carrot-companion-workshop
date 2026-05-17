"""Reads the metadata.yaml + page files written by ingestion/acquire.py.

The acquisition step is the source of truth for the on-disk layout — see
docs/build-plan/phase-00b-acquire-inputs.md and the matching `_build_metadata_yaml`
in `ingestion/acquire.py`. This module just validates and exposes that input
to the rest of the ingestion pipeline.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class EpisodeMetadata(BaseModel):
    """Validated view of one episode's metadata.yaml."""

    slug: str
    title: str
    episode_number: int
    language: str
    published_at: date
    credits_url: str
    commentary_url: str | None = None
    upstream_slug: str
    background_color: str | None = None
    credits: dict[str, list[str]] = Field(default_factory=dict)
    cover_filename: str | None = None
    page_filenames: dict[str, str] = Field(default_factory=dict)


def load_episode_metadata(episode_dir: Path) -> EpisodeMetadata:
    """Read and validate the metadata.yaml inside `episode_dir`.

    Raises FileNotFoundError if the file is missing, and pydantic ValidationError
    if any required field is missing or mistyped.
    """
    metadata_path = episode_dir / "metadata.yaml"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"No metadata.yaml in {episode_dir}")
    raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"metadata.yaml at {metadata_path} did not parse as a mapping")
    return EpisodeMetadata.model_validate(raw)


_PAGE_NUMBER_RE = re.compile(r"page_(\d+)\.")


def list_page_files(episode_dir: Path) -> list[Path]:
    """Return the page image files in numeric order.

    Prefers the `page_filenames` map from metadata.yaml (which preserves the
    intended page count and original extensions); falls back to a glob if no
    metadata is present (e.g. a hand-assembled directory).
    """
    pages_dir = episode_dir / "pages"
    if not pages_dir.is_dir():
        raise FileNotFoundError(f"No pages/ subdirectory in {episode_dir}")

    metadata_path = episode_dir / "metadata.yaml"
    if metadata_path.is_file():
        metadata = load_episode_metadata(episode_dir)
        if metadata.page_filenames:
            return [
                pages_dir / metadata.page_filenames[k]
                for k in sorted(metadata.page_filenames, key=int)
            ]

    candidates = [p for p in pages_dir.iterdir() if _PAGE_NUMBER_RE.search(p.name)]
    return sorted(candidates, key=_page_sort_key)


def _page_sort_key(path: Path) -> int:
    match = _PAGE_NUMBER_RE.search(path.name)
    if match is None:
        raise ValueError(f"Page filename does not match page_NNN.<ext>: {path.name}")
    return int(match.group(1))

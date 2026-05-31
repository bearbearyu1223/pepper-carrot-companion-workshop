"""Reads the world-graph YAML pair into validated pydantic models.

The YAML files at `data/world-graph/entities.yaml` and `relationships.yaml`
are the durable, version-controlled artifact for the world-graph overlay
(see Post 9). The `extract-world-graph` Claude Code skill writes them; this
module is the validation contract that both the skill and the ingestion
loader use to keep the on-disk shape and the DB shape in sync.

`EntityData` / `RelationshipData` are exported so the skill can import them
directly when generating its YAML — a mismatched field fails fast at
validation time instead of silently producing a dangling row.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class _Layout(BaseModel):
    x: float
    y: float


class EntityData(BaseModel):
    """One row in entities.yaml.

    `layout` is nested in the YAML for human readability; we expose flat
    `layout_x` / `layout_y` properties so the loader can hand a single
    mapping to the SQLAlchemy upsert without unpacking the nested shape
    at every call site.
    """

    slug: str
    name: str
    kind: str
    summary: str | None = None
    episode_debut: int
    page_debut: int
    layout: _Layout
    image_url: str | None = None
    character_slug: str | None = None

    @field_validator("slug", "name", "kind")
    @classmethod
    def _strip_and_check_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must be a non-empty string")
        return cleaned

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, value: str) -> str:
        allowed = {"character", "creature", "place", "coven", "object"}
        if value not in allowed:
            raise ValueError(f"kind must be one of {sorted(allowed)}, got {value!r}")
        return value

    @property
    def layout_x(self) -> float:
        return self.layout.x

    @property
    def layout_y(self) -> float:
        return self.layout.y


class RelationshipData(BaseModel):
    """One row in relationships.yaml.

    `source` / `target` are entity slugs; the loader resolves them to UUIDs
    when upserting, so a misspelled slug fails fast at validation time
    rather than producing a dangling row.
    """

    source: str
    target: str
    kind: str
    summary: str | None = None
    episode_debut: int
    page_debut: int

    @field_validator("source", "target", "kind")
    @classmethod
    def _strip_and_check_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must be a non-empty string")
        return cleaned


class _EntitiesFile(BaseModel):
    entities: list[EntityData] = Field(default_factory=list)


class _RelationshipsFile(BaseModel):
    relationships: list[RelationshipData] = Field(default_factory=list)


def load_world_graph(
    graph_dir: Path,
) -> tuple[list[EntityData], list[RelationshipData]]:
    """Read entities.yaml + relationships.yaml from `graph_dir` and validate.

    Raises:
        FileNotFoundError: either YAML file is missing.
        ValueError: duplicate entity slug, or a relationship references an
            unknown source/target slug.
    """
    if not graph_dir.is_dir():
        raise FileNotFoundError(f"World-graph source is not a directory: {graph_dir}")

    entities = _load_entities(graph_dir / "entities.yaml")
    relationships = _load_relationships(graph_dir / "relationships.yaml")

    known_slugs = {e.slug for e in entities}
    for rel in relationships:
        if rel.source not in known_slugs:
            raise ValueError(
                f"Relationship references unknown source slug '{rel.source}' "
                f"(target={rel.target}, kind={rel.kind})"
            )
        if rel.target not in known_slugs:
            raise ValueError(
                f"Relationship references unknown target slug '{rel.target}' "
                f"(source={rel.source}, kind={rel.kind})"
            )

    return entities, relationships


def _load_entities(path: Path) -> list[EntityData]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing entities file: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    parsed = _EntitiesFile.model_validate(raw)

    seen: set[str] = set()
    for entity in parsed.entities:
        if entity.slug in seen:
            raise ValueError(f"Duplicate entity slug '{entity.slug}' in {path}")
        seen.add(entity.slug)
    return parsed.entities


def _load_relationships(path: Path) -> list[RelationshipData]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing relationships file: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    parsed = _RelationshipsFile.model_validate(raw)
    return parsed.relationships

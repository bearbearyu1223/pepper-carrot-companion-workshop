"""Reads wiki markdown files with YAML frontmatter (Post 9).

Each `.md` file under the source directory must have at minimum `slug` and
`title` in its frontmatter; `category` and `source_url` are optional. The
body text after the frontmatter becomes the article content.

Mirrors the role of `episode_loader.py` for the wiki ingestion path. Two
corpuses live in parallel and feed the same loader:
- `data/raw/wiki/`           — hand-curated articles, ~10 short bios.
- `data/raw/wiki-upstream/`  — scraped from framagit by `wiki_scraper.py`,
  ~7 long topic files (characters, creatures, places, magic-system, …).

Slugs from the upstream files (`characters`, `magic-system`, …) don't
collide with the curated slugs (`pepper`, `carrot`, …), so both can be
ingested into the same `wiki_v1` Chroma collection without conflict.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class WikiArticleData(BaseModel):
    """Validated view of one wiki markdown file."""

    slug: str
    title: str
    content: str
    category: str | None = None
    source_url: str | None = None

    # Where this article was read from — used in duplicate-slug errors. Excluded
    # from model_dump so it doesn't leak into anything that serializes the row.
    source_path: Path = Field(exclude=True)

    @field_validator("slug", "title", "content")
    @classmethod
    def _strip_and_check_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must be a non-empty string")
        return cleaned


def load_wiki_articles(wiki_source: Path) -> list[WikiArticleData]:
    """Walk `wiki_source` for `.md` files and return parsed articles.

    Sorted by slug for deterministic ingestion order. Raises if any file
    is missing required frontmatter, so a malformed corpus fails fast at
    load time rather than partway through embedding.
    """
    # Imported lazily so the backend (which only needs WikiArticleData via
    # ingestion/repository.py) doesn't have to install python-frontmatter.
    import frontmatter  # type: ignore[import-not-found]

    if not wiki_source.is_dir():
        raise FileNotFoundError(f"Wiki source is not a directory: {wiki_source}")

    md_files = sorted(p for p in wiki_source.rglob("*.md") if p.is_file())
    if not md_files:
        return []

    articles: list[WikiArticleData] = []
    for path in md_files:
        post = frontmatter.load(str(path))
        meta = post.metadata
        try:
            article = WikiArticleData(
                slug=str(meta.get("slug", "")),
                title=str(meta.get("title", "")),
                content=post.content,
                category=_optional_str(meta.get("category")),
                source_url=_optional_str(meta.get("source_url")),
                source_path=path,
            )
        except Exception as exc:
            raise ValueError(f"Invalid wiki article {path}: {exc}") from exc
        articles.append(article)

    _check_unique_slugs(articles)
    return articles


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _check_unique_slugs(articles: list[WikiArticleData]) -> None:
    seen: dict[str, Path] = {}
    for article in articles:
        if article.slug in seen:
            raise ValueError(
                f"Duplicate wiki slug '{article.slug}' in "
                f"{article.source_path} and {seen[article.slug]}"
            )
        seen[article.slug] = article.source_path

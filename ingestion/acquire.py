"""Pepper&Carrot acquisition pipeline.

Downloads everything the ingestion pipeline needs from peppercarrot.com,
using the project's published JSON manifests instead of HTML scraping.

Sources (all CC BY 4.0, all canonically structured):
- https://peppercarrot.com/0_sources/episodes-v1.json
    Master manifest: episode list + per-page canonical filenames
- https://peppercarrot.com/0_sources/{ep}/info.json
    Per-episode metadata (published date, related URLs, credits)
- https://peppercarrot.com/0_sources/{ep}/hi-res/titles.json
    Episode title in every language
- https://peppercarrot.com/0_sources/{ep}/hi-res/{lang}_{filename}
    Print-resolution page JPG (or GIF) for the chosen language

Output: a directory tree the ingestion pipeline can consume directly.

Usage:
    uv run python acquire.py list
    uv run python acquire.py episode --slug ep01_Potion-of-Flight
    uv run python acquire.py episode --slug ep01_Potion-of-Flight --lang en --out ../data/raw
    uv run python acquire.py all --lang en --out ../data/raw
    uv run python acquire.py commentary --slug ep01_Potion-of-Flight --out ../data/raw
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import click
import httpx
import yaml

logger = logging.getLogger("acquire")

SOURCES_BASE = "https://peppercarrot.com/0_sources"
EPISODES_MANIFEST_URL = f"{SOURCES_BASE}/episodes-v1.json"

# Be a polite citizen — identify ourselves so peppercarrot.com's logs make sense.
DEFAULT_HEADERS = {
    "User-Agent": "peppercarrot-companion/0.1 (educational reading-companion project; "
    "+https://github.com/your-username/peppercarrot-companion)",
}

# Skip non-story slots when downloading "story pages." We still record them in
# metadata (cover, credits, title) but they aren't sent through the VLM as
# narrative pages.
NARRATIVE_PAGE_KEYS = lambda total: [str(i) for i in range(1, total + 1) if str(i)]


# ──────────────────────────────────────────────────────────────────────────────
# Manifest types — match the JSON shape upstream publishes


@dataclass(frozen=True)
class EpisodeManifestEntry:
    """One entry from episodes-v1.json."""

    name: str  # e.g. "ep01_Potion-of-Flight" (the directory slug)
    total_pages: int  # cover + story pages + credits, per upstream convention
    pages: dict[str, str]  # {"1": "Pepper-and-Carrot..._E01P01.jpg", "cover": ..., ...}
    translated_languages: list[str]


@dataclass(frozen=True)
class EpisodeInfo:
    """One episode's info.json — publication metadata + related URLs."""

    id: int
    original_language: str
    published: str  # ISO date "YYYY-MM-DD"
    supporters: int | None
    related_urls: list[str]
    credits: dict[str, list[str]]
    background_color: str | None


# ──────────────────────────────────────────────────────────────────────────────
# Network helpers


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | list:
    logger.info("GET %s", url)
    response = await client.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


async def _fetch_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    logger.info("GET %s", url)
    response = await client.get(url, timeout=120)
    response.raise_for_status()
    return response.content


# ──────────────────────────────────────────────────────────────────────────────
# Public API


async def fetch_episode_manifest(client: httpx.AsyncClient) -> list[EpisodeManifestEntry]:
    """Pull the master episode list from peppercarrot.com."""
    raw = await _fetch_json(client, EPISODES_MANIFEST_URL)
    assert isinstance(raw, list)
    return [
        EpisodeManifestEntry(
            name=entry["name"],
            total_pages=entry["total_pages"],
            pages=entry.get("pages", {}),
            translated_languages=entry["translated_languages"],
        )
        for entry in raw
    ]


async def fetch_episode_info(
    client: httpx.AsyncClient, episode_slug: str
) -> EpisodeInfo:
    """Pull the per-episode info.json."""
    url = f"{SOURCES_BASE}/{episode_slug}/info.json"
    raw = await _fetch_json(client, url)
    assert isinstance(raw, dict)
    return EpisodeInfo(
        id=raw["id"],
        original_language=raw.get("original-language", "en"),
        published=raw["published"],
        supporters=raw.get("supporters"),
        related_urls=raw.get("related-urls", []),
        credits=raw.get("credits", {}),
        background_color=raw.get("background-color"),
    )


async def fetch_episode_titles(
    client: httpx.AsyncClient, episode_slug: str
) -> dict[str, str]:
    """Pull the per-language title map from hi-res/titles.json."""
    url = f"{SOURCES_BASE}/{episode_slug}/hi-res/titles.json"
    try:
        raw = await _fetch_json(client, url)
        assert isinstance(raw, dict)
        return raw
    except httpx.HTTPStatusError:
        logger.warning("No titles.json for %s — using slug as fallback", episode_slug)
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Episode acquisition (the main thing)


def _normalize_slug(slug: str) -> str:
    """Convert upstream slug "ep01_Potion-of-Flight" to local "ep01-potion-of-flight"."""
    return slug.lower().replace("_", "-")


def _episode_number_from_slug(slug: str) -> int:
    """Extract integer episode number. "ep01_..." → 1."""
    # Slug always starts with "ep" + digits
    digits = ""
    for ch in slug[2:]:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits)


def _build_metadata_yaml(
    *,
    upstream_slug: str,
    local_slug: str,
    episode_number: int,
    title: str,
    language: str,
    info: EpisodeInfo,
    cover_filename: str | None,
    page_filenames: dict[int, str],
    commentary_url: str | None,
) -> dict:
    """Build the metadata dict the ingestion pipeline expects (matches phase 5b loader)."""
    return {
        "slug": local_slug,
        "title": title,
        "episode_number": episode_number,
        "language": language,
        "published_at": info.published,
        "credits_url": f"https://www.peppercarrot.com/{language}/webcomic/{upstream_slug}.html",
        "commentary_url": commentary_url,
        "upstream_slug": upstream_slug,
        "background_color": info.background_color,
        "credits": info.credits,
        "cover_filename": cover_filename,
        # Map of page_number -> source filename (for traceability)
        "page_filenames": {str(k): v for k, v in page_filenames.items()},
    }


def _pick_commentary_url(info: EpisodeInfo) -> str | None:
    """Choose the davidrevoy.com URL from related-urls if one is present."""
    for url in info.related_urls:
        if "davidrevoy.com" in url:
            return url
    return None


async def acquire_episode(
    client: httpx.AsyncClient,
    *,
    manifest_entry: EpisodeManifestEntry,
    language: str,
    out_root: Path,
    titles: dict[str, str] | None = None,
    info: EpisodeInfo | None = None,
    overwrite: bool = False,
) -> Path:
    """Download everything for one episode in one language, into a directory the
    ingestion pipeline can consume.

    Output layout (matches docs/build-plan/phase-00b inputs):

        out_root/{local_slug}/
            metadata.yaml
            cover.jpg                  (optional; if a cover slot exists)
            pages/
                page_001.jpg
                page_002.jpg
                ...
    """
    upstream_slug = manifest_entry.name
    local_slug = _normalize_slug(upstream_slug)

    if language not in manifest_entry.translated_languages:
        raise click.ClickException(
            f"{upstream_slug}: language {language!r} not available. "
            f"Available: {', '.join(manifest_entry.translated_languages)}"
        )

    # Fetch info + titles in parallel if not provided
    fetch_tasks: list = []
    if info is None:
        fetch_tasks.append(fetch_episode_info(client, upstream_slug))
    if titles is None:
        fetch_tasks.append(fetch_episode_titles(client, upstream_slug))
    fetched = await asyncio.gather(*fetch_tasks) if fetch_tasks else []
    fi = iter(fetched)
    if info is None:
        info = next(fi)
    if titles is None:
        titles = next(fi)

    title = titles.get(language) or titles.get("en") or upstream_slug
    episode_number = _episode_number_from_slug(upstream_slug)
    commentary_url = _pick_commentary_url(info)

    # Prepare output directory
    episode_dir = out_root / local_slug
    pages_dir = episode_dir / "pages"
    if episode_dir.exists() and not overwrite:
        logger.info("[%s] already exists, skipping (use --overwrite to redo)", local_slug)
        return episode_dir
    pages_dir.mkdir(parents=True, exist_ok=True)

    # Identify which slots in pages map are story pages (numeric keys)
    numeric_page_keys = sorted(
        (int(k) for k in manifest_entry.pages.keys() if k.isdigit())
    )
    page_filenames: dict[int, str] = {}

    # Download story pages in parallel
    async def download_page(page_num: int) -> tuple[int, str, bytes]:
        upstream_filename = manifest_entry.pages[str(page_num)]
        url = f"{SOURCES_BASE}/{upstream_slug}/hi-res/{language}_{upstream_filename}"
        content = await _fetch_bytes(client, url)
        return page_num, upstream_filename, content

    tasks = [download_page(n) for n in numeric_page_keys]
    results = await asyncio.gather(*tasks)
    for page_num, upstream_filename, content in results:
        # Preserve the original extension (jpg/gif)
        ext = Path(upstream_filename).suffix or ".jpg"
        local_filename = f"page_{page_num:03d}{ext}"
        (pages_dir / local_filename).write_bytes(content)
        page_filenames[page_num] = local_filename

    # Download cover if available
    cover_filename: str | None = None
    if "cover" in manifest_entry.pages:
        upstream_cover = manifest_entry.pages["cover"]
        cover_url = f"{SOURCES_BASE}/{upstream_slug}/hi-res/{language}_{upstream_cover}"
        try:
            content = await _fetch_bytes(client, cover_url)
            cover_ext = Path(upstream_cover).suffix or ".jpg"
            cover_filename = f"cover{cover_ext}"
            (episode_dir / cover_filename).write_bytes(content)
        except httpx.HTTPStatusError:
            logger.warning("[%s] cover not found at %s", local_slug, cover_url)

    # Write metadata.yaml
    metadata = _build_metadata_yaml(
        upstream_slug=upstream_slug,
        local_slug=local_slug,
        episode_number=episode_number,
        title=title,
        language=language,
        info=info,
        cover_filename=cover_filename,
        page_filenames=page_filenames,
        commentary_url=commentary_url,
    )
    (episode_dir / "metadata.yaml").write_text(
        yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
    )

    logger.info(
        "[%s] done: %d pages%s%s",
        local_slug,
        len(page_filenames),
        f", cover" if cover_filename else "",
        f", commentary URL captured" if commentary_url else "",
    )
    return episode_dir


# ──────────────────────────────────────────────────────────────────────────────
# CLI


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
def cli(verbose: bool) -> None:
    """Pepper&Carrot acquisition pipeline."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


@cli.command("list")
def list_episodes_cmd() -> None:
    """List all episodes available upstream."""

    async def _run() -> None:
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS) as client:
            episodes = await fetch_episode_manifest(client)
        for ep in episodes:
            click.echo(
                f"{ep.name:<40}  pages={ep.total_pages:<3}  "
                f"langs={len(ep.translated_languages)}"
            )

    asyncio.run(_run())


@cli.command("episode")
@click.option("--slug", required=True, help="Upstream slug, e.g. ep01_Potion-of-Flight")
@click.option("--lang", default="en", show_default=True)
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("../data/raw"),
    show_default=True,
)
@click.option("--overwrite", is_flag=True, help="Re-download even if directory exists")
def acquire_episode_cmd(slug: str, lang: str, out: Path, overwrite: bool) -> None:
    """Acquire one episode."""

    async def _run() -> None:
        out.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS) as client:
            episodes = await fetch_episode_manifest(client)
            entry = next((e for e in episodes if e.name == slug), None)
            if entry is None:
                raise click.ClickException(f"Unknown episode slug: {slug}")
            await acquire_episode(
                client,
                manifest_entry=entry,
                language=lang,
                out_root=out,
                overwrite=overwrite,
            )

    asyncio.run(_run())


@cli.command("all")
@click.option("--lang", default="en", show_default=True)
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("../data/raw"),
    show_default=True,
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Stop after N episodes (useful for testing)",
)
@click.option("--overwrite", is_flag=True, help="Re-download episodes that already exist")
@click.option(
    "--concurrency",
    type=int,
    default=2,
    show_default=True,
    help="How many episodes to download in parallel",
)
def acquire_all_cmd(
    lang: str, out: Path, limit: int | None, overwrite: bool, concurrency: int
) -> None:
    """Acquire every episode available in the given language."""

    async def _run() -> None:
        out.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS) as client:
            episodes = await fetch_episode_manifest(client)
            episodes = [e for e in episodes if lang in e.translated_languages]
            if limit:
                episodes = episodes[:limit]
            click.echo(f"Acquiring {len(episodes)} episode(s) in {lang!r}...")

            sem = asyncio.Semaphore(concurrency)

            async def one(entry: EpisodeManifestEntry) -> None:
                async with sem:
                    try:
                        await acquire_episode(
                            client,
                            manifest_entry=entry,
                            language=lang,
                            out_root=out,
                            overwrite=overwrite,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.error("[%s] failed: %s", entry.name, exc)

            await asyncio.gather(*(one(e) for e in episodes))

    asyncio.run(_run())


@cli.command("commentary")
@click.option("--slug", required=True, help="Upstream slug, e.g. ep01_Potion-of-Flight")
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("../data/raw"),
    show_default=True,
)
def acquire_commentary_cmd(slug: str, out: Path) -> None:
    """Fetch the davidrevoy.com commentary HTML for one episode and save it
    next to the metadata.yaml.

    The actual content extraction (readability + chunking) happens later in
    the ingestion pipeline; this just downloads the raw HTML so you have a
    cached, offline-readable copy.
    """

    async def _run() -> None:
        async with httpx.AsyncClient(headers=DEFAULT_HEADERS) as client:
            info = await fetch_episode_info(client, slug)
            url = _pick_commentary_url(info)
            if not url:
                raise click.ClickException(
                    f"No davidrevoy.com URL found in {slug}'s info.json related-urls"
                )

            local_slug = _normalize_slug(slug)
            episode_dir = out / local_slug
            episode_dir.mkdir(parents=True, exist_ok=True)

            response = await client.get(
                url, timeout=60, follow_redirects=True, headers={"User-Agent": "pc-companion/0.1"}
            )
            response.raise_for_status()
            (episode_dir / "commentary.html").write_text(response.text)
            (episode_dir / "commentary.url").write_text(url + "\n")
            click.echo(f"Saved commentary HTML for {slug} ({len(response.text)} bytes)")

    asyncio.run(_run())


if __name__ == "__main__":
    cli()

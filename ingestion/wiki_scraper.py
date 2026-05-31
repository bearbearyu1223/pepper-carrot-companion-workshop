"""Pull the upstream Pepper&Carrot wiki from framagit (Post 9).

The wiki source-of-truth is https://framagit.org/peppercarrot/wiki —
the rendered pages at https://www.peppercarrot.com/en/wiki/ are just
HTML renders of those markdown files. We scrape the markdown directly
via the framagit REST API (no auth required).

Output lands in `data/raw/wiki-upstream/` by default, separate from the
hand-curated `data/raw/wiki/` so the two corpuses stay clearly
distinguished. Slugs from the upstream files (`characters`,
`magic-system`, …) won't collide with the curated slugs (`pepper`,
`carrot`, …), so both can be ingested into the same `wiki_v1` Chroma
collection without conflict.

Sibling of `wiki_image_scraper.py` — same framagit REST API, same
idempotent CLI shape.

Usage (from `ingestion/`):

    uv run python wiki_scraper.py
    uv run python wiki_scraper.py --out-dir ../data/raw/wiki-upstream
    uv run python wiki_scraper.py --ref master

After scraping, run the wiki ingestion to load these into the DB +
Chroma — `ingest_wiki.py` reads both `data/raw/wiki/` and
`data/raw/wiki-upstream/` by default.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click
import frontmatter  # type: ignore[import-not-found]
import httpx

logger = logging.getLogger("wiki_scraper")

# framagit project path, URL-encoded for the REST API.
_PROJECT = "peppercarrot%2Fwiki"
_API_BASE = "https://framagit.org/api/v4"
_RAW_BASE = "https://framagit.org/peppercarrot/wiki/-/raw"
# The rendered-HTML URL we credit each scraped article with — lets the chat
# layer cite back to the canonical reader-facing page.
_HTML_BASE = "https://www.peppercarrot.com/en/wiki"

# Skip meta/scaffolding files; only ingest topic articles.
_SKIP_FILES = frozenset({"README.md", "LICENSE", "_Footer.md", "_Sidebar.md"})

# Polite citizen header, same convention as acquire.py + wiki_image_scraper.
_HEADERS = {
    "User-Agent": (
        "pepper-carrot-companion-workshop/0.1 (educational reading-companion "
        "project; +https://github.com/bearbearyu1223/pepper-carrot-companion-workshop)"
    ),
}


def _list_root_md_files(client: httpx.Client, ref: str) -> list[str]:
    """Return the paths of all top-level .md topic files in the repo."""
    response = client.get(
        f"{_API_BASE}/projects/{_PROJECT}/repository/tree",
        params={"ref": ref, "per_page": 100},
    )
    response.raise_for_status()
    entries = response.json()
    return sorted(
        e["path"]
        for e in entries
        if e["type"] == "blob"
        and e["path"].endswith(".md")
        and e["path"] not in _SKIP_FILES
    )


def _fetch_raw(client: httpx.Client, path: str, ref: str) -> str:
    response = client.get(f"{_RAW_BASE}/{ref}/{path}")
    response.raise_for_status()
    return response.text


def _slug_for(filename: str) -> str:
    """`Magic-System.md` → `magic-system`. Lowercase, hyphenated."""
    return filename.removesuffix(".md").lower().replace("_", "-")


def _title_for(filename: str) -> str:
    """`Magic-System.md` → `Magic System`. Hyphens/underscores → spaces."""
    return filename.removesuffix(".md").replace("-", " ").replace("_", " ")


def _source_url_for(filename: str) -> str:
    """`Magic-System.md` → `https://www.peppercarrot.com/en/wiki/Magic-System.html`."""
    return f"{_HTML_BASE}/{filename.removesuffix('.md')}.html"


@click.command()
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("../data/raw/wiki-upstream"),
    show_default=True,
    help="Directory to write scraped markdown files into.",
)
@click.option(
    "--ref",
    default="master",
    show_default=True,
    help="Git ref (branch/tag/sha) on framagit.org/peppercarrot/wiki to pull.",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
def main(out_dir: Path, ref: str, verbose: bool) -> None:
    """Scrape the upstream Pepper&Carrot wiki into markdown files."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"Output directory: {out_dir.resolve()}")
    click.echo(f"Pulling from framagit.org/peppercarrot/wiki @ {ref}")

    with httpx.Client(
        timeout=httpx.Timeout(30.0), headers=_HEADERS
    ) as client:
        paths = _list_root_md_files(client, ref)
        if not paths:
            click.echo("No markdown topic files found at the root — nothing to do.")
            return

        click.echo(f"Found {len(paths)} markdown files to fetch.")
        for path in paths:
            click.echo(f"  fetching {path} … ", nl=False)
            content = _fetch_raw(client, path, ref)
            slug = _slug_for(path)
            post = frontmatter.Post(
                content,
                slug=slug,
                title=_title_for(path),
                category="wiki",
                source_url=_source_url_for(path),
            )
            out_path = out_dir / f"{slug}.md"
            out_path.write_text(frontmatter.dumps(post), encoding="utf-8")
            click.echo(f"→ {out_path.name} ({len(content)} chars)")

    click.echo("")
    click.echo("Done. Run the wiki ingestion to load these into Postgres + Chroma:")
    click.echo("    uv run python ingest_wiki.py")


if __name__ == "__main__":
    main()

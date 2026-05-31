"""Scrape character and creature artwork from the upstream Pepper&Carrot wiki.

The framagit project at https://framagit.org/peppercarrot/wiki/-/tree/master/medias/img
holds ~43 small JPEGs licensed CC BY 4.0 — among them `chara_*.jpg` (the named
cast) and `creature_*.jpg` (familiars and beasts). This script lists the tree
via the framagit REST API, downloads each image we want, processes it with
Pillow into a 96x96 center-cropped thumbnail and a 320px-longest-edge display
variant (both WebP), and writes them to `data/world-graph/images/` alongside an
`image_manifest.json` the `extract-world-graph` skill consumes for its
`image_url` assignments.

Mirrors the per-episode `acquire.py` shape — same idempotent CLI, same
polite User-Agent, same data/ layout.

Usage (from `ingestion/`):

    uv run python wiki_image_scraper.py
    uv run python wiki_image_scraper.py --refresh        # re-download everything
    uv run python wiki_image_scraper.py --ref master --out-dir ../data/world-graph/images
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import click
import httpx
from PIL import Image

logger = logging.getLogger("wiki_image_scraper")

# framagit project path, URL-encoded for the REST API.
_PROJECT = "peppercarrot%2Fwiki"
_API_BASE = "https://framagit.org/api/v4"
_RAW_BASE = "https://framagit.org/peppercarrot/wiki/-/raw"
_IMG_PATH = "medias/img"

_CHARA_PREFIX = "chara_"
_CREATURE_PREFIX = "creature_"
_JPG_SUFFIX = ".jpg"

# Variant sizes. Thumb is what the graph node renders; display is what the
# info card shows on click. The frontend swaps `-thumb` → `-display` in the
# URL when it opens the card, so the two filenames must share the slug stem.
_THUMB_SIZE = 96
_DISPLAY_LONG_EDGE = 320
_WEBP_QUALITY = 85

# Polite citizen header, same convention as acquire.py.
_HEADERS = {
    "User-Agent": (
        "pepper-carrot-companion-workshop/0.1 (educational reading-companion "
        "project; +https://github.com/bearbearyu1223/pepper-carrot-companion-workshop)"
    ),
}


@dataclass(frozen=True)
class _Candidate:
    """One framagit blob we've decided is worth scraping."""

    filename: str  # "chara_pepper.jpg"
    image_slug: str  # "pepper"
    kind: str  # "character" | "creature"


def _list_image_candidates(client: httpx.Client, ref: str) -> list[_Candidate]:
    """Walk the `medias/img` tree once and return only the chara_/creature_ jpgs."""
    response = client.get(
        f"{_API_BASE}/projects/{_PROJECT}/repository/tree",
        params={"ref": ref, "path": _IMG_PATH, "per_page": 200},
    )
    response.raise_for_status()
    entries = response.json()

    candidates: list[_Candidate] = []
    for entry in entries:
        if entry.get("type") != "blob":
            continue
        name = entry["name"]
        if not name.endswith(_JPG_SUFFIX):
            continue
        if name.startswith(_CHARA_PREFIX):
            slug = name.removeprefix(_CHARA_PREFIX).removesuffix(_JPG_SUFFIX)
            candidates.append(
                _Candidate(filename=name, image_slug=slug, kind="character")
            )
        elif name.startswith(_CREATURE_PREFIX):
            slug = name.removeprefix(_CREATURE_PREFIX).removesuffix(_JPG_SUFFIX)
            candidates.append(
                _Candidate(filename=name, image_slug=slug, kind="creature")
            )
        # Anything else (logo_cc.png, shichimi_hair_piece.jpg, …)
        # is intentionally skipped.
    return sorted(candidates, key=lambda c: (c.kind, c.image_slug))


def _fetch_repo_sha(client: httpx.Client, ref: str) -> str:
    """Return the short sha (8 chars) of the latest commit on `ref`."""
    response = client.get(
        f"{_API_BASE}/projects/{_PROJECT}/repository/commits",
        params={"ref_name": ref, "per_page": 1},
    )
    response.raise_for_status()
    commits = response.json()
    if not commits:
        raise RuntimeError(f"No commits returned for ref {ref!r}")
    return str(commits[0]["id"])[:8]


def _download_image(client: httpx.Client, filename: str, ref: str) -> bytes:
    response = client.get(f"{_RAW_BASE}/{ref}/{_IMG_PATH}/{filename}")
    response.raise_for_status()
    return response.content


def _process_to_variants(image_bytes: bytes) -> tuple[bytes, bytes]:
    """Return (thumb_bytes, display_bytes) for one source image.

    Thumb is a 96x96 center-square-crop — it lands in the graph as a
    circular avatar so squareness avoids a bias toward the top of the
    portrait. Display preserves the source aspect with the longest edge
    clamped to 320px and is rendered as the larger image in the info card.
    Both are quality-85 WebP.
    """
    with Image.open(BytesIO(image_bytes)) as src:
        src.load()
        rgb = src.convert("RGB")

    # Thumb: center-square-crop, then resize.
    side = min(rgb.width, rgb.height)
    left = (rgb.width - side) // 2
    top = (rgb.height - side) // 2
    square = rgb.crop((left, top, left + side, top + side))
    thumb = square.resize((_THUMB_SIZE, _THUMB_SIZE), Image.Resampling.LANCZOS)

    # Display: preserve aspect, longest edge = 320.
    display = rgb.copy()
    display.thumbnail(
        (_DISPLAY_LONG_EDGE, _DISPLAY_LONG_EDGE), Image.Resampling.LANCZOS
    )

    thumb_buf = BytesIO()
    thumb.save(thumb_buf, format="WEBP", quality=_WEBP_QUALITY, method=6)
    display_buf = BytesIO()
    display.save(display_buf, format="WEBP", quality=_WEBP_QUALITY, method=6)
    return thumb_buf.getvalue(), display_buf.getvalue()


def _variant_paths(out_dir: Path, image_slug: str) -> tuple[Path, Path]:
    return (
        out_dir / f"{image_slug}-thumb.webp",
        out_dir / f"{image_slug}-display.webp",
    )


@click.command()
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("../data/world-graph/images"),
    show_default=True,
    help="Directory to write -thumb.webp and -display.webp pairs into.",
)
@click.option(
    "--ref",
    default="master",
    show_default=True,
    help="Git ref (branch/tag/sha) on framagit.org/peppercarrot/wiki to pull from.",
)
@click.option(
    "--refresh/--no-refresh",
    default=False,
    show_default=True,
    help="Re-download images even if their variants are already on disk.",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
def main(out_dir: Path, ref: str, refresh: bool, verbose: bool) -> None:
    """Scrape character/creature artwork from the upstream framagit wiki."""
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
        candidates = _list_image_candidates(client, ref)
        if not candidates:
            click.echo("No chara_/creature_ jpgs found at medias/img — nothing to do.")
            return
        sha = _fetch_repo_sha(client, ref)
        click.echo(f"Found {len(candidates)} candidate images at {ref}@{sha}.")

        characters: list[str] = []
        creatures: list[str] = []
        downloaded = 0
        skipped = 0
        for cand in candidates:
            thumb_path, display_path = _variant_paths(out_dir, cand.image_slug)
            already_present = thumb_path.is_file() and display_path.is_file()
            if already_present and not refresh:
                skipped += 1
            else:
                click.echo(f"  fetching {cand.filename} … ", nl=False)
                source_bytes = _download_image(client, cand.filename, ref)
                thumb_bytes, display_bytes = _process_to_variants(source_bytes)
                thumb_path.write_bytes(thumb_bytes)
                display_path.write_bytes(display_bytes)
                downloaded += 1
                click.echo(
                    f"→ {cand.image_slug}-thumb.webp ({len(thumb_bytes)} B), "
                    f"{cand.image_slug}-display.webp ({len(display_bytes)} B)"
                )
            if cand.kind == "character":
                characters.append(cand.image_slug)
            else:
                creatures.append(cand.image_slug)

    manifest_path = out_dir.parent / "image_manifest.json"
    manifest = {
        "scraped_from": "framagit:peppercarrot/wiki",
        "scraped_ref": ref,
        "scraped_sha": sha,
        "scraped_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "characters": sorted(characters),
        "creatures": sorted(creatures),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    click.echo("")
    click.echo(
        f"Done. Downloaded {downloaded} new image(s); skipped {skipped} already-present."
    )
    click.echo(f"  characters: {len(characters)}")
    click.echo(f"  creatures:  {len(creatures)}")
    click.echo(f"  manifest:   {manifest_path}")


if __name__ == "__main__":
    main()

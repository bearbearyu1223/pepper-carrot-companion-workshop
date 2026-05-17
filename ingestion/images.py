"""Image processing helpers for the offline ingestion pipeline.

Produces the three on-disk variants (original / display / thumbnail) plus the
small bag of metadata the runtime needs to render a page placeholder before
the full image arrives (width, height, blurhash, dominant color).

See docs/ingestion-pipeline.md for the surrounding pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import cast

import blurhash
from PIL import Image

DISPLAY_LONG_EDGE = 1600
DISPLAY_QUALITY = 82
THUMBNAIL_LONG_EDGE = 300
THUMBNAIL_QUALITY = 75
BLURHASH_COMPONENTS = (3, 3)
DOMINANT_COLOR_PALETTE = 8

# Comic pages with transparency composite onto white to keep the blurhash and
# dominant-color from going muddy (see ingestion-pipeline.md failure modes).
_TRANSPARENCY_BACKGROUND = (255, 255, 255)


@dataclass(frozen=True)
class ImageMetadata:
    width: int
    height: int
    blurhash: str
    dominant_color: str  # "#RRGGBB"


@dataclass(frozen=True)
class ProcessedPageImages:
    original_bytes: bytes
    display_bytes: bytes
    thumbnail_bytes: bytes
    metadata: ImageMetadata
    is_animated: bool


def process_page_image(source_path: Path) -> ProcessedPageImages:
    """Generate the three variants + metadata for one source image.

    `original_bytes` is the source file passed through unchanged. The display
    and thumbnail variants are re-encoded WebP and so naturally drop EXIF.
    `is_animated` is true when the source is a multi-frame format (e.g. an
    animated GIF) — the caller may want to serve the original instead of the
    static display variant in that case.
    """
    original_bytes = source_path.read_bytes()

    with Image.open(source_path) as src:
        is_animated = bool(getattr(src, "is_animated", False))
        src.load()
        rgb = _to_rgb(src)

    display_bytes = _encode_resized_webp(rgb, DISPLAY_LONG_EDGE, DISPLAY_QUALITY)
    thumbnail_bytes = _encode_resized_webp(rgb, THUMBNAIL_LONG_EDGE, THUMBNAIL_QUALITY)

    metadata = ImageMetadata(
        width=rgb.width,
        height=rgb.height,
        blurhash=compute_blurhash(rgb),
        dominant_color=compute_dominant_color(rgb),
    )
    return ProcessedPageImages(
        original_bytes=original_bytes,
        display_bytes=display_bytes,
        thumbnail_bytes=thumbnail_bytes,
        metadata=metadata,
        is_animated=is_animated,
    )


def compute_blurhash(image: Image.Image) -> str:
    rgb = _to_rgb(image)
    # Blurhash only encodes low-frequency color, so a small thumbnail gives
    # the same hash much faster than feeding the full page through.
    small = rgb.copy()
    small.thumbnail((64, 64), Image.Resampling.LANCZOS)
    pixels = [
        [small.getpixel((x, y)) for x in range(small.width)]
        for y in range(small.height)
    ]
    cx, cy = BLURHASH_COMPONENTS
    return str(blurhash.encode(pixels, cx, cy))


def compute_dominant_color(image: Image.Image) -> str:
    rgb = _to_rgb(image)
    quantized = rgb.quantize(colors=DOMINANT_COLOR_PALETTE)
    counts = quantized.getcolors() or []
    palette = quantized.getpalette() or []
    if not counts or not palette:
        return "#000000"
    typed_counts = cast(list[tuple[int, int]], counts)
    _, palette_index = max(typed_counts, key=lambda c: c[0])
    base = palette_index * 3
    r, g, b = palette[base], palette[base + 1], palette[base + 2]
    return f"#{r:02X}{g:02X}{b:02X}"


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, _TRANSPARENCY_BACKGROUND)
        background.paste(rgba, mask=rgba.split()[3])
        return background
    return image.convert("RGB")


def _encode_resized_webp(image: Image.Image, long_edge: int, quality: int) -> bytes:
    resized = image.copy()
    resized.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    buf = BytesIO()
    resized.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()



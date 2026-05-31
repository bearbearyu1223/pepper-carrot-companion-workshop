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
from PIL import Image, ImageSequence

DISPLAY_LONG_EDGE = 1600
DISPLAY_QUALITY = 82
THUMBNAIL_LONG_EDGE = 300
THUMBNAIL_QUALITY = 75
BLURHASH_COMPONENTS = (3, 3)
DOMINANT_COLOR_PALETTE = 8

# Comic pages with transparency composite onto white to keep the blurhash and
# dominant-color from going muddy (see ingestion-pipeline.md failure modes).
_TRANSPARENCY_BACKGROUND = (255, 255, 255)

# The flipbook's page slot is a fixed portrait aspect (see Flipbook.tsx
# `width: 600, height: 847`, matching the standard hi-res page 2481×3503).
# Source images that diverge significantly from this — panoramic panels
# (ep04's vortex page, ~3.82:1) or animated GIFs of the same — render as
# tiny strips lost in vertical whitespace under CSS `object-fit: contain`.
# We pad those at ingestion time so every display variant lands in the
# slot consistently; pages that are already close to the standard aspect
# pass through untouched.
STANDARD_DISPLAY_ASPECT = 600 / 847  # ≈ 0.7084 (width / height, portrait)
ASPECT_TOLERANCE = 0.05  # within 5% of standard → no padding
_PAGE_PAD_BACKGROUND = (255, 255, 255)  # matches CSS `--panel: #ffffff`


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
        # First-frame RGB drives metadata + thumbnail in both branches.
        first_frame_rgb = _to_rgb(src)

        if is_animated:
            # Animated source (typically GIF). Re-encode as animated WebP with
            # every frame padded to the standard portrait aspect, so the
            # flipbook page slot fills cleanly while the motion is preserved.
            display_bytes = _encode_animated_webp(
                src, DISPLAY_LONG_EDGE, DISPLAY_QUALITY
            )
        else:
            fitted = _pad_to_standard_aspect(first_frame_rgb)
            display_bytes = _encode_resized_webp(
                fitted, DISPLAY_LONG_EDGE, DISPLAY_QUALITY
            )

    # Thumbnail is always the static, padded first frame — animated thumbnails
    # are bandwidth-expensive and the picker only needs a still preview.
    thumb_source = _pad_to_standard_aspect(first_frame_rgb)
    thumbnail_bytes = _encode_resized_webp(
        thumb_source, THUMBNAIL_LONG_EDGE, THUMBNAIL_QUALITY
    )

    # Metadata reflects the original source dimensions (the truth about the
    # artwork itself), not the padded variant — blurhash and dominant color
    # would be diluted by the white bands and that would show on placeholders.
    metadata = ImageMetadata(
        width=first_frame_rgb.width,
        height=first_frame_rgb.height,
        blurhash=compute_blurhash(first_frame_rgb),
        dominant_color=compute_dominant_color(first_frame_rgb),
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


def _pad_to_standard_aspect(image: Image.Image) -> Image.Image:
    """Pad with white bands so the image matches the flipbook page aspect.

    Pages within `ASPECT_TOLERANCE` of `STANDARD_DISPLAY_ASPECT` pass through
    untouched. Wider-than-standard sources (panoramic panels) gain top/bottom
    bands; taller-than-standard sources gain left/right bands. The padded
    image is always centered.
    """
    src_aspect = image.width / image.height
    if abs(src_aspect - STANDARD_DISPLAY_ASPECT) <= ASPECT_TOLERANCE:
        return image

    if src_aspect > STANDARD_DISPLAY_ASPECT:
        # Wider than standard — pad height so the new aspect matches.
        new_width = image.width
        new_height = int(round(image.width / STANDARD_DISPLAY_ASPECT))
    else:
        # Taller than standard — pad width.
        new_height = image.height
        new_width = int(round(image.height * STANDARD_DISPLAY_ASPECT))

    padded = Image.new("RGB", (new_width, new_height), _PAGE_PAD_BACKGROUND)
    offset = ((new_width - image.width) // 2, (new_height - image.height) // 2)
    padded.paste(image, offset)
    return padded


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


def _encode_animated_webp(src: Image.Image, long_edge: int, quality: int) -> bytes:
    """Re-encode an animated source as a portrait-padded animated WebP.

    Each frame is composited onto white, padded to the standard portrait
    aspect, and resized so its long edge fits `long_edge`. Frame durations
    and loop count are carried over from the source (default loop=0,
    meaning play forever). Modern browsers (Chrome/Edge/Safari 16+/Firefox)
    render animated WebP natively, so the flipbook gets a single
    `*-display.webp` URL that animates without any special-casing.
    """
    frames: list[Image.Image] = []
    durations: list[int] = []
    for raw_frame in ImageSequence.Iterator(src):
        rgb_frame = _to_rgb(raw_frame)
        padded = _pad_to_standard_aspect(rgb_frame)
        padded.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
        frames.append(padded)
        durations.append(int(raw_frame.info.get("duration", 100)))

    loop = int(src.info.get("loop", 0))
    buf = BytesIO()
    # Pillow writes animated WebP via the first frame's .save() with
    # save_all=True and the rest of the frames in append_images.
    frames[0].save(
        buf,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=loop,
        quality=quality,
        method=6,
    )
    return buf.getvalue()



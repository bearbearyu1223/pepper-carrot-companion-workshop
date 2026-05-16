"""Smoke tests for LocalStorage."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.clients.storage import LocalStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=tmp_path, url_prefix="http://test.local/images")


async def test_put_writes_file(storage: LocalStorage, tmp_path: Path) -> None:
    await storage.put("episodes/ep01/pages/001.webp", b"hello", "image/webp")
    written = tmp_path / "episodes/ep01/pages/001.webp"
    assert written.exists()
    assert written.read_bytes() == b"hello"


async def test_put_is_idempotent_for_identical_content(
    storage: LocalStorage, tmp_path: Path
) -> None:
    key = "a/b.bin"
    await storage.put(key, b"hello", "application/octet-stream")
    mtime_before = (tmp_path / key).stat().st_mtime_ns

    # Sleep long enough that any rewrite would change mtime on every reasonable FS.
    await asyncio.sleep(0.05)
    await storage.put(key, b"hello", "application/octet-stream")
    mtime_after = (tmp_path / key).stat().st_mtime_ns

    assert mtime_before == mtime_after, "identical content should be a no-op"
    assert (tmp_path / key).read_bytes() == b"hello"


async def test_put_overwrites_when_content_differs(
    storage: LocalStorage, tmp_path: Path
) -> None:
    key = "a/b.bin"
    await storage.put(key, b"hello", "application/octet-stream")
    await storage.put(key, b"world!", "application/octet-stream")
    assert (tmp_path / key).read_bytes() == b"world!"


async def test_url_for_composes_prefix_and_key(storage: LocalStorage) -> None:
    url = await storage.url_for("episodes/ep01/pages/001.webp")
    assert url == "http://test.local/images/episodes/ep01/pages/001.webp"


async def test_exists_reflects_filesystem(storage: LocalStorage) -> None:
    assert await storage.exists("missing.bin") is False
    await storage.put("present.bin", b"x", "application/octet-stream")
    assert await storage.exists("present.bin") is True


async def test_path_escape_via_dotdot_is_rejected(storage: LocalStorage) -> None:
    with pytest.raises(ValueError, match="outside storage root"):
        await storage.put("../escape.bin", b"x", "application/octet-stream")


async def test_path_escape_via_dotdot_in_exists_is_rejected(storage: LocalStorage) -> None:
    with pytest.raises(ValueError, match="outside storage root"):
        await storage.exists("../escape.bin")

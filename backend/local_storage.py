"""Self-hosted upload storage on local disk (product decision: no object storage). Root configurable via UPLOADS_DIR."""
import asyncio
import os
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_BASE_DIR = os.environ.get("UPLOADS_DIR") or os.path.join(BASE_DIR, "uploads")
PRIVATE_BASE_DIR = os.environ.get("PRIVATE_FILES_DIR") or os.path.join(BASE_DIR, "private")
CATEGORIES = ("attachments", "hero", "logos", "kb", "downloads")


def category_dir(category: str) -> str:
    path = os.path.join(UPLOAD_BASE_DIR, category)
    os.makedirs(path, exist_ok=True)
    return path


async def save_upload(category: str, filename: str, contents: bytes) -> str:
    target = Path(category_dir(category)) / filename
    await asyncio.to_thread(target.write_bytes, contents)
    return str(target)


async def save_private(category: str, filename: str, contents: bytes) -> str:
    """Files that must never be served publicly (e.g. shipping labels with customer addresses)."""
    folder = Path(PRIVATE_BASE_DIR) / category
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    await asyncio.to_thread(target.write_bytes, contents)
    return str(target)

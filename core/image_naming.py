"""Deterministic local filenames for a product's downloaded images.

Naming convention specified by the spreadsheet owner: sanitize the
product's Title into a filename by title-casing each whitespace-separated
word (`str.capitalize()`, so "SDVoE" -> "Sdvoe") and joining them with
"_", then apply Windows Explorer's own duplicate-file suffix to every
image after the first ("_(1)", "_(2)", ...). Example, for a product
titled "SDVoE ( 1 0 G )" with two images:

    Sdvoe_(_1_0_G_).jpg
    Sdvoe_(_1_0_G_)_(1).jpg

Used by `services/image_downloader.py`.
"""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

# Characters Windows (and this project runs on Windows) forbids in filenames.
_ILLEGAL_FILENAME_CHARS_RE = re.compile(r'[\\/:*?"<>|]')

_KNOWN_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".svg"}
_DEFAULT_EXTENSION = ".jpg"


def sanitize_title(title: str) -> str:
    """Turns a product Title into a filesystem-safe base filename (no
    extension). Falls back to "image" if `title` is blank after trimming.
    """
    words = [_ILLEGAL_FILENAME_CHARS_RE.sub("_", word).capitalize() for word in title.strip().split()]
    return "_".join(words) or "image"


def guess_extension(url: str, content_type: str | None = None) -> str:
    """Prefers the extension already in the URL (most image CDNs have one);
    falls back to sniffing the response's Content-Type, then to ".jpg".
    """
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in _KNOWN_IMAGE_EXTENSIONS:
        return suffix
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return ".jpg" if guessed == ".jpe" else guessed
    return _DEFAULT_EXTENSION


def build_image_filename(title: str, index: int, url: str, content_type: str | None = None) -> str:
    """`index` is the image's 0-based position among its product's images:
    0 gets no suffix, 1 gets "_(1)", 2 gets "_(2)", etc. -- matching how
    Windows Explorer names successive copies of the same file.
    """
    base = sanitize_title(title)
    ext = guess_extension(url, content_type)
    suffix = "" if index == 0 else f"_({index})"
    return f"{base}{suffix}{ext}"

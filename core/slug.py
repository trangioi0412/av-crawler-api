"""Turns a manufacturer's display name into a registry key.

Used when a manufacturer is registered dynamically (AI-assisted path, see
`api/routes/manufacturer_requests.py`) rather than declared in code with a
fixed key like `manufacturers/hdcvt/config.py::HDCVT_CONFIG.key`.
"""
from __future__ import annotations

import re

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _NON_ALNUM_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "manufacturer"

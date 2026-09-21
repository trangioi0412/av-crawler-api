"""Thin client around a local Ollama server, used to extract structured
product data from a page's visible text when no hand-written adapter
exists for a manufacturer (see `manufacturers/generic_ai/adapter.py`).

Model-agnostic by design: swap `OLLAMA_MODEL` in `.env` for any model
pulled into the local Ollama install (tested with `qwen3.5:9b`). This is
intentionally a separate, small module -- if a hosted LLM (Gemini, OpenAI,
...) is preferred later, only this file needs a new implementation of the
same `extract_product` contract; nothing else in the pipeline changes.
"""
from __future__ import annotations

import json
import re

import requests

from core.logging import get_logger

logger = get_logger(__name__)

# Verified against a real local Ollama instance running qwen3.5:9b on this
# hardware (mostly CPU-bound, ~1.6GB of ~6GB model in VRAM): a single
# extraction call took ~110s. Generous timeout to match; still bounded by
# `num_predict` below so a pathological response can't run indefinitely.
_TIMEOUT_SECONDS = 240.0
_MAX_OUTPUT_TOKENS = 800

_EXTRACTION_PROMPT = """You are extracting structured product data from an AV/electronics manufacturer's product page.

Read the page text below and return ONLY a single JSON object (no markdown, no explanation) with exactly these fields:
{{
  "name": "product name/title, or null if this is not a real product page",
  "model": "model number/SKU if present, else null",
  "category": "product category/type if identifiable, else null",
  "description": "1-3 sentence overview, else null",
  "features": ["short feature bullet", "..."],
  "specifications": {{"spec name": "spec value", "...": "..."}}
}}

Rules:
- If the page is clearly NOT a single product (e.g. a category listing, news article, contact page), set "name" to null and leave other fields empty.
- Only include specifications that are actually stated on the page. Do not invent values.
- Return valid JSON only.

URL: {url}

PAGE TEXT:
{text}
"""

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class OllamaExtractionError(Exception):
    pass


class OllamaClient:
    def __init__(self, host: str, model: str) -> None:
        self._host = host.rstrip("/")
        self._model = model

    def extract_product(self, *, url: str, page_text: str) -> dict:
        """Returns a dict matching the schema in `_EXTRACTION_PROMPT`.

        Raises `OllamaExtractionError` on any failure (unreachable server,
        invalid JSON in the response, etc.) -- callers (the adapter's
        `parse()`) let this propagate so the per-item crawl-error isolation
        in `BaseManufacturerAdapter.crawl_urls` catches it.
        """
        prompt = _EXTRACTION_PROMPT.format(url=url, text=page_text[:8000])

        try:
            response = requests.post(
                f"{self._host}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "think": False,  # Qwen3's "thinking" mode burns most of the
                    # timeout budget on reasoning tokens before ever emitting
                    # the JSON answer -- verified against the real model.
                    "options": {"temperature": 0.1, "num_predict": _MAX_OUTPUT_TOKENS},
                },
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaExtractionError(f"Ollama request failed: {exc}") from exc

        raw_output = response.json().get("response", "")
        return self._parse_json_response(raw_output)

    @staticmethod
    def _parse_json_response(raw_output: str) -> dict:
        try:
            return json.loads(raw_output)
        except json.JSONDecodeError:
            pass

        match = _JSON_OBJECT_RE.search(raw_output)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        raise OllamaExtractionError(f"Model did not return valid JSON: {raw_output[:200]!r}")

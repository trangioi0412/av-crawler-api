"""Unit tests for the Ollama extraction client's response parsing. Mocks
the HTTP call to Ollama's /api/generate -- never touches a real Ollama
server.
"""
from __future__ import annotations

import json

import pytest
import responses

from services.ollama_client import OllamaClient, OllamaExtractionError


@responses.activate
def test_extract_product_parses_clean_json():
    payload = {"name": "Widget X", "model": "WX-1", "category": "Gadgets", "description": None, "features": [], "specifications": {}}
    responses.add(
        responses.POST,
        "http://localhost:11434/api/generate",
        json={"response": json.dumps(payload)},
        status=200,
    )

    client = OllamaClient(host="http://localhost:11434", model="qwen3.5:9b")
    result = client.extract_product(url="https://example.com/p/1", page_text="some page text")

    assert result["name"] == "Widget X"
    assert result["model"] == "WX-1"


@responses.activate
def test_extract_product_recovers_json_wrapped_in_markdown():
    payload = {"name": "Widget Y", "model": None, "category": None, "description": None, "features": [], "specifications": {}}
    noisy = f"Here is the JSON:\n```json\n{json.dumps(payload)}\n```"
    responses.add(
        responses.POST,
        "http://localhost:11434/api/generate",
        json={"response": noisy},
        status=200,
    )

    client = OllamaClient(host="http://localhost:11434", model="qwen3.5:9b")
    result = client.extract_product(url="https://example.com/p/2", page_text="text")

    assert result["name"] == "Widget Y"


@responses.activate
def test_extract_product_raises_on_garbage_response():
    responses.add(
        responses.POST,
        "http://localhost:11434/api/generate",
        json={"response": "I cannot help with that."},
        status=200,
    )

    client = OllamaClient(host="http://localhost:11434", model="qwen3.5:9b")
    with pytest.raises(OllamaExtractionError):
        client.extract_product(url="https://example.com/p/3", page_text="text")


@responses.activate
def test_extract_product_raises_on_unreachable_server():
    responses.add(responses.POST, "http://localhost:11434/api/generate", status=500)

    client = OllamaClient(host="http://localhost:11434", model="qwen3.5:9b")
    with pytest.raises(OllamaExtractionError):
        client.extract_product(url="https://example.com/p/4", page_text="text")

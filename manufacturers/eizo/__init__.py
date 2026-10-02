"""Registers the EIZO adapter with the global manufacturer registry.

This is the only wiring EIZO needs. Importing this module (transitively,
via `manufacturers/__init__.py`) is enough for `sync_manufacturer_data`,
the registry, and the API to know about EIZO -- the core engine never
imports this package directly.
"""
from core.registry import registry
from manufacturers.eizo.adapter import EizoAdapter
from manufacturers.eizo.config import EIZO_CONFIG

registry.register(EIZO_CONFIG.key, EizoAdapter, EIZO_CONFIG)

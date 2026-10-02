"""Registers the VISSONIC adapter with the global manufacturer registry.

This is the only wiring VISSONIC needs. Importing this module
(transitively, via `manufacturers/__init__.py`) is enough for
`sync_manufacturer_data`, the registry, and the API to know about
VISSONIC -- the core engine never imports this package directly.
"""
from core.registry import registry
from manufacturers.vissonic.adapter import VissonicAdapter
from manufacturers.vissonic.config import VISSONIC_CONFIG

registry.register(VISSONIC_CONFIG.key, VissonicAdapter, VISSONIC_CONFIG)

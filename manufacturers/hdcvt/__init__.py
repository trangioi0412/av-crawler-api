"""Registers the HDCVT adapter with the global manufacturer registry.

This is the only wiring HDCVT needs. Importing this module (transitively,
via `manufacturers/__init__.py`) is enough for `sync_manufacturer_data`,
the registry, and the API to know about HDCVT -- the core engine never
imports this package directly.
"""
from core.registry import registry
from manufacturers.hdcvt.adapter import HdcvtAdapter
from manufacturers.hdcvt.config import HDCVT_CONFIG

registry.register(HDCVT_CONFIG.key, HdcvtAdapter, HDCVT_CONFIG)

"""Manufacturer adapter package.

Importing this package registers every known adapter with the global
`registry` as a side effect. `main.py` imports this package once at startup;
nothing else needs to know which manufacturers exist.

To add a new manufacturer: create `manufacturers/<name>/adapter.py`, define a
`ManufacturerConfig` + a `BaseManufacturerAdapter` subclass, and add one
import line below. The sync engine and API never change.
"""
from manufacturers import hdcvt  # noqa: F401  (self-registers on import)

__all__ = ["hdcvt"]

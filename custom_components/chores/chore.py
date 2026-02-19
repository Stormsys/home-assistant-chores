"""Backwards-compatible re-export of the Chore class.

The canonical location is chore_core.py.  This module exists so that
any external code doing ``from .chore import Chore`` keeps working.
"""
from .chore_core import Chore  # noqa: F401

__all__ = ["Chore"]

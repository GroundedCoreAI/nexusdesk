"""Local demo HTTP service; never connect to production business data.

Kept importable as ``examples.mock_business:app`` because the runtime docs and
``tools.demo.json`` both start it that way.
"""

from .app import app

__all__ = ["app"]

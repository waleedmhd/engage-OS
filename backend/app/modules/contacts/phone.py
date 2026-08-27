"""Canonical phone-number normalization and display formatting.

Re-exports from ``app.core.phone`` for backward compatibility. New code should
import directly from ``app.core.phone``.
"""

from __future__ import annotations

from app.core.phone import canonicalize_phone, format_phone_for_display  # noqa: F401

__all__ = ["canonicalize_phone", "format_phone_for_display"]

"""
Cross-module Protocol / ABC definitions.

This module is intentionally empty. No protocols are currently needed — all
cross-module dependencies are handled via lazy imports, natural directional
coupling (data dependencies like enums/models are acceptable), or are at the
composition-root level (app.core.dependencies).

When a protocol becomes necessary, define it here and have the implementing
module import it (not the reverse). Example skeleton::

    from typing import Protocol, runtime_checkable

    @runtime_checkable
    class MessageDispatchProtocol(Protocol):
        def send(self, conversation_id: str, content: str) -> str: ...
"""

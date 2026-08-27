"""
Cross-module service protocols and abstract base classes.

Add a protocol or ABC here ONLY when it eliminates a concrete import between
two modules that should not know about each other. A protocol is warranted when:

- Module A imports a concrete class from Module B at module level
- That class has behavior (not just data/enum)
- Moving the import to lazy is insufficient (circular import risk)
- The dependency is NOT a natural direction

Current state (2026-07-22): no protocols are needed. All cross-module
dependencies are either:
  a) Natural directional (conversations -> messaging, campaigns -> messaging)
  b) Already lazy-imported (messaging -> campaigns inside function bodies)
  c) Enums/models (data, not behavior)
  d) Acknowledged composition-root imports (core dependencies.py)
"""

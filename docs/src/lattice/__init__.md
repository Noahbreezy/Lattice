# Package exports

[`src/lattice/__init__.py`](../../../src/lattice/__init__.py) is the public
facade. It re-exports the validated configuration types, domain contracts,
pipeline helpers, history store, repository, review queue, and retention
planner so callers do not need to import every implementation module.

When adding a public API, update `__all__` and this page. Internal helpers
should remain in their owning module.

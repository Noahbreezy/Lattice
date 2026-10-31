# `lattice` package

The package exports the public configuration, contract, history, pipeline,
persistence, review, and retention APIs from [`__init__.py`](../../../src/lattice/__init__.py).

## Module map

| Module | Responsibility |
| --- | --- |
| [`config.md`](config.md) | Parse and validate project JSON |
| [`contracts.md`](contracts.md) | Immutable pipeline and review models |
| [`pipeline.md`](pipeline.md) | Deterministic local topic-to-script flow |
| [`history.md`](history.md) | JSON lesson-history storage |
| [`review.md`](review.md) | In-memory queue and review transitions |
| [`persistence.md`](persistence.md) | SQLite episode and review adapter |
| [`retention.md`](retention.md) | Oldest-first deletion planning |
| [`cli.md`](cli.md) | Configuration-validation command |

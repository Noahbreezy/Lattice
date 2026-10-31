# Episode persistence

[`persistence.py`](../../../src/lattice/persistence.py) provides
`EpisodeRepository`, a SQLite adapter with a database-neutral domain API.

The repository stores episode identity, topic, lifecycle status, revision,
private video URI, creation time, queue priority, and rejection feedback.
Reviews are stored separately and reference their episode. SQLite foreign keys,
WAL mode, and a queue index are enabled during initialization.

`claim_next` selects queued or rejected work by priority and creation time,
then marks it processing in a transaction. Rejected decisions receive front
queue priority; approved decisions retain the private video reference.
Review decisions use the episode's current awaiting-review state as an
optimistic-concurrency check, and stale decisions are rejected without adding
a review record.
Production should preserve these method boundaries with PostgreSQL
transactions and a connection pool.

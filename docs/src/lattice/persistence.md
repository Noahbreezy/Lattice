# Episode persistence

[`persistence.py`](../../../src/lattice/persistence.py) provides
`EpisodeRepository`, a SQLite adapter with a database-neutral domain API.

The repository stores episode identity, topic, lifecycle status, revision,
private video URI, creation time, queue priority, rejection feedback, and
per-revision video, lesson, and script references.
Reviews are stored separately and reference their episode. SQLite foreign keys,
WAL mode, and a queue index are enabled during initialization.

`claim_next` selects queued or rejected work by priority and creation time,
then marks it processing in a transaction. Rejected decisions receive front
queue priority; approved decisions retain the private video reference.
Review decisions use the episode's current awaiting-review state as an
optimistic-concurrency check, and stale decisions are rejected without adding
a review record.

The same adapter now includes a small durable job table. Jobs have an
idempotency key, queued/running/succeeded/failed states, attempt counts, and
retry or dead-letter behavior. `claim_job` and status updates run in
transactions and back the local worker with leases and heartbeats. The
PostgreSQL adapter preserves these method boundaries for server deployment.

`local_api.py` exposes the repository through a standard-library HTTP adapter
for local and server review. It supports health checks, episode listing,
historical revision access, and approve/reject decisions. A bearer token can
be configured through `LATTICE_REVIEW_TOKEN`; server mode requires it for API
and media routes. Public exposure also needs an authenticating TLS proxy and
operational controls.

# PostgreSQL repository

[`postgres.py`](../../../src/lattice/postgres.py) implements the episode,
review, revision, historical artifact, job, and audit contract of the local SQLite repository.
PostgreSQL transactions make decisions and job claims atomic; workers use
`FOR UPDATE SKIP LOCKED` to claim distinct queued jobs. The server package is
optional and requires `psycopg`.

The adapter creates its schema on startup for a fresh database. Set
`LATTICE_TEST_POSTGRES_URL` to a disposable database to run the opt-in
repository contract test. Schema migrations, connection pooling, and
database-backed topic reservation are needed before horizontal scaling.

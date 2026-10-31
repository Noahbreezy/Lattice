# Persistence tests

[`test_persistence.py`](../../tests/test_persistence.py) covers file-backed
round trips, rejected-item queue priority, atomic review decisions and
requeueing, review history, and preservation of approved private video URIs.

The tests use temporary SQLite files or the default in-memory database and
close every repository in teardown.

# Local worker

[`worker.py`](../../../src/lattice/worker.py) provides `LocalWorker`, a
synchronous worker boundary for development. It claims durable jobs, recovers
expired leases, dispatches handlers by capability, retries failures up to a
configured attempt limit, and records audit events.

Production can replace the loop with a process/service scheduler while keeping
the repository operations and handler contract. Provider calls should remain
outside the HTTP process and use the same bounded retry and audit behavior.

[`runner.py`](../../../src/lattice/runner.py) registers the local production
handler. It claims a specific queued episode revision, loads the latest saved
rejection, builds a new bundle, renders and validates the video, stores private
artifacts, and submits the result for review. A failed attempt returns the
episode to the queue so the durable job can retry. Revision-specific paths
retain earlier videos and inspection artifacts.

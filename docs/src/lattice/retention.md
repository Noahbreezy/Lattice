# Retention planning

[`retention.py`](../../../src/lattice/retention.py) models storage location and
video metadata, then returns deletion candidates from `plan_retention`.

Cloud/server limits and approved/rejected/awaiting-review limits are evaluated
independently. For each exceeded limit, the oldest artifacts are selected.
Candidates are deduplicated by video ID when multiple limits select the same
artifact. `None` means unlimited.

The planner never deletes files. A worker must audit each action and verify
that an artifact is not actively processing or under review before deletion.

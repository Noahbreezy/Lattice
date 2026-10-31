# Pipeline contracts

[`contracts.py`](../../../src/lattice/contracts.py) contains frozen dataclasses
and enums shared across the pipeline and review domains.

`Topic` normalizes its title into a comparison key. `ResearchPacket` requires
at least one source and claim and verifies every claim source index. `Script`
requires sections, a positive duration, and at least one linked claim.

`EpisodeStatus` models queued, processing, awaiting-review, approved, rejected,
and failed lifecycle states. An awaiting-review episode must have a private
video URI. `Review` is immutable and requires feedback for rejection. The
`now_utc` helper provides serializable provenance timestamps.

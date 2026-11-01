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

The production artifact contracts are versioned and ordered:

```text
Script -> Storyboard -> AssetManifest -> RenderJob -> PublishedVideo
```

`ArtifactProvenance` records stable artifact identity, content SHA-256,
configuration and prompt versions, provider/model capability identity, input
artifact IDs, timestamps, and approval state. Render jobs and published videos
enforce lifecycle transitions; a published video cannot be created until its
render job succeeds.

Research and quality validation are separate from the contracts so providers
can be replaced without changing stored artifact shapes. The local adapter is
intentionally provisional and fails the production quality gate until a real
source-backed provider is used.

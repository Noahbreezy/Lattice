# Local content pipeline

[`pipeline.py`](../../../src/lattice/pipeline.py) implements the dependency-free
development flow:

```text
ProjectConfig -> Topic -> ResearchPacket -> Script
```

The deterministic local adapter also provides the planned production stages:

```text
Script -> Storyboard -> AssetManifest -> RenderJob -> PublishedVideo
```

`build_storyboard`, `build_asset_manifest`, `create_render_job`, and
`publish_video` emit version-one contracts with provenance links and SHA-256
content hashes. They use local placeholder assets and a provider-neutral
`RenderProvider` protocol; no vendor API is embedded in the domain model.

`ResearchProvider` in `research.py` is the boundary for a real source
retrieval integration. `validate_research` and the quality checks in
`quality.py` reject placeholder or unverified evidence before publication and
check script structure, duration, and claim coverage.

`select_topic` atomically reserves the first configured seed absent from
`LessonHistory`, preventing concurrent workers from selecting the same topic.
`build_research_packet` currently creates a clearly unverified placeholder
source and claim. `build_script` creates one section per configured required
section and estimates duration from word count at a configurable speaking rate.

`create_episode_draft` composes these steps and reserves the topic before
production begins. `record_completed_episode` remains idempotent for
compatibility with callers that record completion explicitly. The placeholder
research output is not publication-ready.

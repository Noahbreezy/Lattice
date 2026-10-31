# Local content pipeline

[`pipeline.py`](../../../src/lattice/pipeline.py) implements the dependency-free
development flow:

```text
ProjectConfig -> Topic -> ResearchPacket -> Script
```

`select_topic` atomically reserves the first configured seed absent from
`LessonHistory`, preventing concurrent workers from selecting the same topic.
`build_research_packet` currently creates a clearly unverified placeholder
source and claim. `build_script` creates one section per configured required
section and estimates duration from word count at a configurable speaking rate.

`create_episode_draft` composes these steps and reserves the topic before
production begins. `record_completed_episode` remains idempotent for
compatibility with callers that record completion explicitly. The placeholder
research output is not publication-ready.

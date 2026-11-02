# Lattice

Lattice is a configurable framework for producing high-quality short-form
videos. A project configuration describes the content strategy, consistent
video traits, production workflow, and optional AI tools. The framework is
intended to support many video formats; the included knowledge channel is only
an example configuration.

## Mission

Lattice exists to make it easy to create high-quality short-form videos from
prompts. It is a configurable, provider-independent AI video creation
framework: users should be able to define the content strategy, production
workflow, quality requirements, and tools for any topic or theme. The current
knowledge channel is an initial use case, not a limit on what the framework
supports. AI-generated lessons are acceptable for recreational content; the
system should label uncertainty and run automated checks before final review.
Human review happens only after a complete video has been rendered.

## Branching strategy

`main` is the latest integrated version and should remain deployable. New work
must use a feature branch named with the `feature/` prefix, for example
`feature/server-review-queue` or `feature/provider-integrations`. Merge feature
branches into `main` through a pull request after tests pass. Do not develop
directly on `main`.

## Status

The current slice provides dependency-free configuration and versioned
Script-to-PublishedVideo artifact contracts with provenance, a local
topic/history store, a deterministic development pipeline, deterministic
research/script quality gates, and a SQLite persistence adapter for
server-oriented episode/review state and retryable jobs. Its research data is
explicitly provisional and is intended to be replaced by an AI lesson provider
for the recreational workflow.

## Quick start

Requires Python 3.11 or newer.

```powershell
python -m unittest discover -s tests
python -m lattice.cli configs\knowledge-channel.json
```

Run the local contract pipeline from Python:

```powershell
$env:PYTHONPATH = "src"
@'
from pathlib import Path
from lattice import LessonHistory, create_episode_draft, load_config

config = load_config("configs/knowledge-channel.json")
history = LessonHistory(Path("var/lesson-history.json"))
draft = create_episode_draft(config, history)
print(draft.topic.title)
for section in draft.script.sections:
    print(f"\n## {section.heading}\n{section.text}")
'@ | python -
```

For local development without installing the package, set the source path:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -m lattice.cli configs\knowledge-channel.json
```

## Configuration

Copy [`configs/knowledge-channel.json`](configs/knowledge-channel.json) to
create a new project. Keep the top-level sections stable:

- `project`: identity and description.
- `content`: format, prompt, lesson structure, subject areas, and learning rules.
- `production`: target duration, repeatable style traits, ordered workflow, and
  tool capabilities.

Tool entries describe capabilities rather than hard-coding a vendor API. This
keeps a project portable: integrations can later map a capability such as
`video generator` to Higgsfield or another provider.

Validate any configuration before using it:

```powershell
python -m lattice.cli path\to\project.json
```

Validation errors are explicit and fail with a non-zero exit code.

The contract and infrastructure direction is documented in
[`docs/architecture.md`](docs/architecture.md). The primary production
workflow is model-generated lesson -> automated quality checks -> script ->
scenes -> narration and visuals -> rendered video -> human review. The
`WikipediaResearchProvider` remains an optional source-grounded mode, not a
required step for recreational videos.

An Ollama model can generate the lesson locally without an API key:

```powershell
$env:PYTHONPATH = "src"
@'
from pathlib import Path
from lattice import (
    LessonHistory, OllamaLessonProvider, build_production_bundle, load_config
)

config = load_config("configs\knowledge-channel.json")
bundle = build_production_bundle(
    config,
    LessonHistory(Path("var\lesson-history.json")),
    lesson_provider=OllamaLessonProvider("qwen3:4b"),
)
print(bundle.draft.script.sections[0].text)
'@ | python -
```

The adapter requires Ollama to be running locally and returns structured
sections, claims, and uncertainty. If no model is configured, the deterministic
development fixture remains available for tests and offline development.

The project has mirrored domain documentation under [`docs/`](docs/README.md).
Each page follows the corresponding source, configuration, or test path so
that implementation behavior and its documentation can be navigated together.

The planned production mode is a private server-hosted review app. Finished
videos will be stored in private object storage, approved videos will remain
available for later upload, and rejected videos will return to the front of
the processing queue with required reviewer feedback. Authentication and
authorization are server responsibilities; credentials must never be embedded
in browser code or committed configuration.

The local persistence adapter can be exercised with:

```powershell
$env:PYTHONPATH = "src"
@'
from lattice import EpisodeRepository

repository = EpisodeRepository("var/lattice.sqlite")
print("Persistence schema initialized")
repository.close()
'@ | python -
```

Start the local review API with a configured SQLite database:

```powershell
$env:PYTHONPATH = "src"
$env:LATTICE_REVIEW_TOKEN = "change-this-local-token"
@'
from lattice import EpisodeRepository, create_review_server

repository = EpisodeRepository("var/lattice.sqlite")
server = create_review_server(
    repository, host="127.0.0.1", port=8765, media_root="var/videos"
)
print("Review API: http://127.0.0.1:8765")
try:
    server.serve_forever()
finally:
    server.server_close()
    repository.close()
'@ | python -
```

The API exposes `GET /health`, `GET /episodes`, `GET /review-queue`,
`GET /episodes/{id}`, `GET /episodes/{id}/reviews`, and
`POST /episodes/{id}/review`. Review rejection payloads may include a
`criteria` array and timestamped `markers` with `start_seconds`,
`end_seconds`, `criterion`, and optional `comment`. Set
`LATTICE_REVIEW_TOKEN` before use; requests
then require the configured bearer token in the `Authorization` header. This is a local adapter,\r\nnot a public deployment authentication system.
`GET /app` serves a minimal mobile-friendly review page for the local adapter.
Rejected decisions increment the episode revision and persist an immutable
revision record containing the feedback that caused the rework.

Once installed, the same server is available as:

```powershell
$env:LATTICE_REVIEW_TOKEN = "change-this-local-token"
lattice-review-server --database var\lattice.sqlite
```

The local FFmpeg renderer creates a real private MP4 from a successful render
job. It creates a consistent illustrated geometric style and can use free
local Windows SAPI narration without credentials:

```powershell
$env:PYTHONPATH = "src"
@'
from lattice import FfmpegRenderer
renderer = FfmpegRenderer("var/videos")
print("Renderer ready:", renderer.output_dir)
'@ | python -
```

For narrated output on Windows:

```powershell
$env:PYTHONPATH = "src"
@'
from lattice import FfmpegRenderer, WindowsSpeechTts
renderer = FfmpegRenderer("var/videos", tts_provider=WindowsSpeechTts())
'@ | python -
```

Piper is also supported through `PiperTts` when a local Piper executable and
voice model are installed. Narration returns explicit word timings; providers
with native alignment data can replace the current proportional timing
fallback without changing the renderer contract.

Each render also emits an `.srt` subtitle artifact derived from storyboard
narration. A future TTS/asset adapter can use the same scene timings to add
narration, visuals, and burned-in captions without changing the job contract.
`build_production_bundle` provides the first complete deterministic slice from
topic selection through a duration-accurate vertical render job. The built-in
demo research fixture covers Path dependence and Base rates for exercising the
full workflow; it is not a replacement for a live research provider.
SQLite is used only to keep local development dependency-free. The repository
interface is designed for a PostgreSQL implementation when the server API and
deployment are introduced.

## Retention settings

The `production.retention` section controls counts independently:

- `max_cloud_videos`: maximum completed video artifacts in object storage.
- `max_server_videos`: maximum completed video artifacts on server disk.
- `max_approved_videos`: maximum approved videos retained.
- `max_rejected_videos`: maximum rejected videos retained.
- `max_awaiting_review_videos`: maximum videos waiting for review.

Use `null` for unlimited. Limits are counts, not sizes. The retention planner
selects the oldest excess artifacts and returns deletion candidates; it does
not delete files automatically. A production worker must audit and verify each
candidate before deletion.

## Documentation rule

When configuration fields, workflow stages, or public APIs change, update this
README and the relevant example configuration in the same change. Add or update
tests for validation behavior. Future integrations should document required
credentials and provider-specific setup without committing secrets.

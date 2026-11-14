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

The current implementation provides versioned Script-to-PublishedVideo
contracts, configured lesson and provider adapters, deterministic content and
media gates, revision-aware production, and private review. SQLite and local
files support development; PostgreSQL and S3-compatible storage support the
server mode. Offline research fixtures remain explicitly provisional.

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
    print(f"\n## {section.heading}\nNarration: {section.text}")
    print(f"Visual explanation: {section.visual_description}")
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
- `production`: strict duration ceiling, repeatable style traits, ordered workflow, and
  tool capabilities.

`max_video_length_seconds` is an upper bound, not a target. The included project
sets it to 179 so every finished video is under three minutes. Scripts and
storyboards derive their actual runtime from the amount of narration needed for
a clear explanation; content is never padded to reach the ceiling.

Tool entries describe capabilities rather than hard-coding a vendor API. This
keeps a project portable: installed entry-point adapters can map a capability
such as `video generator` to a provider. Generated storyboard
entries are standalone scene prompts: each contains the spoken narration, a
specific visual explanation of that logical step, the scene duration, and a
beat-by-beat timing plan that synchronizes visual actions to narration excerpts.

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
    LessonHistory, build_production_bundle, load_config
)

config = load_config("configs\knowledge-channel.json")
bundle = build_production_bundle(
    config,
    LessonHistory(Path("var\lesson-history.json")),
)
print(bundle.draft.script.sections[0].text)
print(bundle.draft.script.sections[0].visual_description)
'@ | python -
```

The configured production path requires Ollama to be running locally and
returns structured sections, claims, and uncertainty. The model and endpoint
are set under the `script model` entry in `production.ai_tools`. Deterministic
research is available only when callers explicitly pass `offline=True`, which
is intended for tests and offline development.

The project has mirrored domain documentation under [`docs/`](docs/README.md).
Each page follows the corresponding source, configuration, or test path so
that implementation behavior and its documentation can be navigated together.

The server mode uses PostgreSQL, private S3-compatible object storage, a
production worker, and a mobile review page. Approved videos remain private
for later upload; rejected revisions return to the queue with saved feedback.
Keep credentials in environment secrets and place the HTTP server behind TLS
and an authenticating reverse proxy.

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
    repository,
    host="127.0.0.1",
    port=8765,
    media_root="var/lattice-artifacts/review-media",
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
`GET /episodes/{id}`, `GET /episodes/{id}/reviews`,
`GET /episodes/{id}/revisions`, historical revision media and content, and
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
lattice-review-server `
  --database var\lattice.sqlite `
  --media-root var\lattice-artifacts\review-media
```

The local FFmpeg renderer creates a real private MP4 from a successful render
job. It creates labeled cause/mechanism/outcome diagrams and uses free local
Windows SAPI narration by default, without credentials:

```powershell
$env:PYTHONPATH = "src"
@'
from lattice import FfmpegRenderer
renderer = FfmpegRenderer("var/videos")
print("Renderer ready:", renderer.output_dir)
'@ | python -
```

To select the Windows voice or inject another offline provider on Windows:

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
narration. Missing, silent, or zero-duration narration fails explicitly; there
is no silent-audio or blank-visual fallback.
`build_production_bundle` provides the first complete deterministic slice from
topic selection through a duration-accurate vertical render job. The built-in
demo research fixture covers Path dependence and Base rates for exercising the
full workflow; it is not a replacement for a live research provider.
SQLite keeps local development dependency-free. The server uses the same
repository contract backed by PostgreSQL.

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
## Local production and review

Produce one configured episode through lesson generation, quality checks,
local visual creation, FFmpeg rendering, media validation, private local
storage, and the review queue:

```bash
lattice-run-local configs/knowledge-channel.json
```

The default lesson provider is the configured Ollama model; start Ollama and
install the model named in `production.ai_tools` before running. For a
deterministic provider-free development run, add `--offline`. Use `--database`,
`--output`, and `--history` to select local paths. The command produces one
durable job per episode revision and exits nonzero if production fails. Rerun
the command after a rejection to process that revision before selecting a new
topic. Saved feedback, criteria, and timestamped markers reach the next lesson
request and visual plan.

The command writes the bundle, timed script, manifest, evidence, and temporary
render assets under `var/lattice-artifacts/episodes/{id}/revision-{n}`. The
review video, subtitles, lesson, and script live beneath
`var/lattice-artifacts/review-media`, the default root of the local review
server. Each revision uses distinct paths, preserving prior videos and
artifacts. Per-revision database references and authenticated historical
routes keep earlier videos and content accessible. The local runner validates
configured stage order and required provider capabilities. The project brief
and traits drive lesson and scene
prompts. Production rejects model-authored claims labeled as externally
supported, frozen video, and inaudible final audio. These checks cannot prove
factual accuracy; human review remains required.

Optional provider packages register factories under `lattice.lesson`,
`lattice.research`, `lattice.visual`, `lattice.narration`, or `lattice.editor`
entry-point groups, named by the configuration's `provider` field. Research,
lesson, narration, and visual factories receive `(config, tool)`; editor
factories receive `(config, tool, output_dir, tts, visual)`. An optional missing
visual provider falls back to the local illustrated adapter. A required
missing provider fails before production. The built-in Wikipedia research
provider can ground the Ollama prompt when selected; its sources are retained
for review, while model claims remain labeled model-generated until verified.

## Server deployment

Install optional dependencies, provision an empty PostgreSQL database and
private S3-compatible bucket, then set secrets in the host environment:

```bash
pip install '.[server]'
export LATTICE_DATABASE_URL='postgresql://user:password@db-host/lattice'
export LATTICE_STORAGE_BUCKET='private-review-bucket'
export LATTICE_STORAGE_PREFIX='lattice'
export LATTICE_REVIEW_TOKEN='a-long-random-secret'
lattice-server --host 127.0.0.1 --port 8765
```

`LATTICE_S3_ENDPOINT_URL` optionally selects an S3-compatible endpoint. Run
`lattice-worker configs/knowledge-channel.json` as a separate service. On
Linux, configure the `narration` capability with `provider: "piper"` and a
local voice-model path; the example configuration uses Windows SAPI.
`--once` processes one episode, and `--interval` sets the polling delay.
Serve `/app` through an HTTPS reverse proxy with identity-based access
control; keep the API bound to loopback or a private network. The page asks
for the review token at runtime and keeps it in memory. Media and artifact
requests pass through the authenticated API; the bucket remains private.

The PostgreSQL contract test is opt-in: set `LATTICE_TEST_POSTGRES_URL` to a
disposable database and run `python -m unittest discover -s tests` with the
server dependencies installed. The default suite uses SQLite and a fake S3
client, so it cannot verify a live PostgreSQL or cloud deployment.

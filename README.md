# Lattice

Lattice is a configurable framework for producing high-quality short-form
videos. A project configuration describes the content strategy, consistent
video traits, production workflow, and optional AI tools. The framework is
intended to support many video formats; the included knowledge channel is only
an example configuration.

## Branching strategy

`main` is the latest integrated version and should remain deployable. New work
must use a feature branch named with the `feature/` prefix, for example
`feature/server-review-queue` or `feature/provider-integrations`. Merge feature
branches into `main` through a pull request after tests pass. Do not develop
directly on `main`.

## Status

The current slice provides dependency-free configuration and content contracts,
a local topic/history store, a deterministic development pipeline, and a
SQLite persistence adapter for server-oriented episode/review state. Its
research data is explicitly provisional and must not be published.

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
[`docs/architecture.md`](docs/architecture.md). The next provider integration
must replace the placeholder research stage, attach real citations to claims,
and add human review before publication.

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

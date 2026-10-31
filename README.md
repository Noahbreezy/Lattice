# Lattice

Lattice is a configurable framework for producing high-quality short-form
videos. A project configuration describes the content strategy, consistent
video traits, production workflow, and optional AI tools. The framework is
intended to support many video formats; the included knowledge channel is only
an example configuration.

## Status

The current slice provides dependency-free configuration and content contracts,
a local topic/history store, and a deterministic development pipeline from
topic selection through a structured script. Its research data is explicitly
provisional and must not be published.

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

The planned production mode is a private server-hosted review app. Finished
videos will be stored in private object storage, approved videos will remain
available for later upload, and rejected videos will return to the front of
the processing queue with required reviewer feedback. Authentication and
authorization are server responsibilities; credentials must never be embedded
in browser code or committed configuration.

## Documentation rule

When configuration fields, workflow stages, or public APIs change, update this
README and the relevant example configuration in the same change. Add or update
tests for validation behavior. Future integrations should document required
credentials and provider-specific setup without committing secrets.

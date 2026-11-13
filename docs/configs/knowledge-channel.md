# Knowledge channel configuration

Source: [`configs/knowledge-channel.json`](../../configs/knowledge-channel.json)

This example describes the `connected-knowledge` project and its `A New Thing`
short-form educational channel.

## Sections

- `project` identifies the project and gives its description.
- `content` defines the channel, format, lesson prompt, required script
  sections, subject areas, learning rules, and initial topic seeds.
- `production` defines a 179-second maximum, repeatable style traits, ordered
  workflow, provider-neutral AI capabilities, and retention limits. This is a
  ceiling rather than a target: each script should be only as long as its clear
  explanation requires, and every finished video must remain under three minutes.

The local runner requires these workflow stages in execution order. The
`script model` capability selects Ollama unless `--offline` is used. The
`narration` capability selects Windows SAPI in this example; set it to `piper`
with a voice-model path on Linux. Required external visual providers are
rejected until an adapter is available. The local editor uses FFmpeg and
illustrated scenes.

The research assistant is optional and unset in this example. Setting its
provider to `wikipedia` retrieves source context for Ollama and retains those
sources in the lesson artifact. Model-authored claims still identify their AI
origin and require review. Installed provider packages can register entry-point
adapters for each capability.

AI tool entries describe capabilities, not implementation dependencies. A
provider may be absent (`null`) when an integration has not been selected.

## Retention policy

The example retains up to 100 cloud videos, 5 server videos, 100 approved
videos, 20 rejected videos, and 10 awaiting-review videos. These are counts;
`null` would mean unlimited. The planner returns candidates and never deletes
artifacts itself.

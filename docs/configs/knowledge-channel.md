# Knowledge channel configuration

Source: [`configs/knowledge-channel.json`](../../configs/knowledge-channel.json)

This fixture describes the `connected-knowledge` project and its `A New Thing`
short-form educational channel.

## Sections

- `project` identifies the project and gives its description.
- `content` defines the channel, format, lesson prompt, required script
  sections, subject areas, learning rules, and initial topic seeds.
- `production` defines the 75-second target, repeatable style traits, ordered
  workflow, provider-neutral AI capabilities, and retention limits.

AI tool entries describe capabilities, not implementation dependencies. A
provider may be absent (`null`) when an integration has not been selected.

## Retention policy

The example retains up to 100 cloud videos, 5 server videos, 100 approved
videos, 20 rejected videos, and 10 awaiting-review videos. These are counts;
`null` would mean unlimited. The planner returns candidates and never deletes
artifacts itself.

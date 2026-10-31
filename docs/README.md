# Lattice documentation

This directory mirrors the repository's domain structure. Source modules,
configuration fixtures, and tests each have a nearby Markdown page describing
their responsibilities, public contracts, important invariants, and current
limitations.

## Repository map

| Project path | Documentation |
| --- | --- |
| [`README.md`](../README.md) | [Project guide](project.md) |
| [`pyproject.toml`](../pyproject.toml) | [Packaging and commands](pyproject.md) |
| [`configs/`](../configs/) | [`configs/`](configs/) |
| [`src/lattice/`](../src/lattice/) | [`src/lattice/`](src/lattice/) |
| [`tests/`](../tests/) | [`tests/`](tests/) |

The system-level design is in [`architecture.md`](architecture.md). The
mirrored pages are deliberately narrower: use them when working on one domain
or module, and use the architecture page when changing boundaries between
domains.

## Domain flow

```text
configuration
    -> topic selection and lesson history
    -> research packet and script contracts
    -> episode/review workflow
    -> persistence and retention planning
```

The local research packet is provisional. It must not be published without a
real research provider, source verification, and human review.

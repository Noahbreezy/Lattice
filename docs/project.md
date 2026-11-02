# Project guide

The root README is the operational entry point for Lattice: installation
requirements, local commands, configuration shape, retention behavior, and
the production security boundary are documented there.

## Mission

Lattice makes it easy to create high-quality short-form videos from prompts.
It is a configurable, provider-independent AI video creation framework in
which users can define the content strategy, production workflow, quality
requirements, and tools for any topic or theme. The current knowledge channel
is an initial use case, not the framework's scope. For recreational content,
an AI model may generate the lesson directly. Automated checks run before a
complete video enters the queue; human review is only required after the full
video is rendered.

## Development commands

From the repository root:

```powershell
python -m unittest discover -s tests
$env:PYTHONPATH = "src"
python -m lattice.cli configs\knowledge-channel.json
```

Configuration changes should update the example JSON, the relevant source
documentation, and validation tests in the same change.

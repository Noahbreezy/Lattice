# Command-line interface

[`cli.py`](../../../src/lattice/cli.py) implements the `lattice-validate`
command and the equivalent `python -m lattice.cli` invocation.

It accepts a configuration path, delegates parsing to `load_config`, prints
the project name, under-three-minute duration ceiling, and workflow count on success, and reports
`ConfigError` to stderr with exit code `1` on failure. It does not run the
content pipeline or contact providers.

`lattice-run-local` runs one durable production job. By default it uses the
configured Ollama lesson provider; `--offline` explicitly selects the fixture.
It processes rejected revisions before new topics. Revision-specific bundle,
review evidence, manifest, rendered assets, and timed script are stored under
`{output}/episodes/{id}/revision-{n}`. Review media, lessons, and scripts are
stored beneath `{output}/review-media`, matching the local server default.
The script includes global timing, narration, visual prompts, and synchronized
beats. Failed jobs remain queued for bounded worker retries.

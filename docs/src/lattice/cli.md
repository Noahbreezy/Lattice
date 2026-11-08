# Command-line interface

[`cli.py`](../../../src/lattice/cli.py) implements the `lattice-validate`
command and the equivalent `python -m lattice.cli` invocation.

It accepts a configuration path, delegates parsing to `load_config`, prints
the project name, under-three-minute duration ceiling, and workflow count on success, and reports
`ConfigError` to stderr with exit code `1` on failure. It does not run the
content pipeline or contact providers.

`lattice-run-local` runs the deterministic offline pipeline and writes the
machine-readable episode artifact, review evidence, asset manifest, rendered
media, and a canonical `*.script.md` production script. The Markdown script is
scene-based and includes global timing, narration, standalone consistently
themed Higgsfield prompts, and synchronized visual beats.

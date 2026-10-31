# Command-line interface

[`cli.py`](../../../src/lattice/cli.py) implements the `lattice-validate`
command and the equivalent `python -m lattice.cli` invocation.

It accepts a configuration path, delegates parsing to `load_config`, prints
the project name, target duration, and workflow count on success, and reports
`ConfigError` to stderr with exit code `1` on failure. It does not run the
content pipeline or contact providers.

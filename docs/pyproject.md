# Packaging and commands

[`pyproject.toml`](../pyproject.toml) defines a dependency-light Python 3.11+
package named `lattice-video`.

## Build configuration

- Setuptools is the build backend.
- Packages are discovered below `src/`.
- The package is not dependent on external runtime services.

## Console command

The `lattice-validate` entry point calls `lattice.cli:main`. It accepts one
JSON configuration path, prints a success summary for valid input, and
returns exit code `1` with an error on invalid configuration.

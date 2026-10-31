# Project guide

The root README is the operational entry point for Lattice: installation
requirements, local commands, configuration shape, retention behavior, and
the production security boundary are documented there.

## Development commands

From the repository root:

```powershell
python -m unittest discover -s tests
$env:PYTHONPATH = "src"
python -m lattice.cli configs\knowledge-channel.json
```

Configuration changes should update the example JSON, the relevant source
documentation, and validation tests in the same change.

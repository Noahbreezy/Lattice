# Provider selection

[`providers.py`](../../../src/lattice/providers.py) discovers optional
capability adapters through Python package entry points. A project selects an
adapter by setting the corresponding `production.ai_tools[].provider` name.
The groups are `lattice.lesson`, `lattice.research`, `lattice.visual`,
`lattice.narration`, and `lattice.editor`.

The built-in lesson adapter is Ollama, the optional source adapter is
Wikipedia, and the local media stack is illustrated visuals, Windows SAPI or
Piper narration, and FFmpeg editing. A missing required adapter fails before
production; an optional missing visual adapter uses the local illustrator.
External video adapters must provide assets the configured editor can consume.

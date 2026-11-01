# Local renderer

[`renderer.py`](../../../src/lattice/renderer.py) provides `FfmpegRenderer`,
which converts a succeeded `RenderJob` into a real MP4 artifact under a
configured private output directory. The current development renderer creates
vertical color slates with a silent audio track; this validates the media
container and lifecycle without requiring a visual-generation vendor.

The renderer is deliberately behind the existing `RenderProvider` protocol.
Future adapters can replace the generated slates with storyboard assets,
narration, captions, music, and platform-specific exports without changing
episode or review contracts.

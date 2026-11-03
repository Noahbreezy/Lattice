# Local renderer

[`renderer.py`](../../../src/lattice/renderer.py) provides `FfmpegRenderer`,
which converts a succeeded `RenderJob` into a real MP4 artifact under a
configured private output directory. The current development renderer creates
vertical color slates with a silent audio track; this validates the media
container and lifecycle without requiring a visual-generation vendor.

The renderer is deliberately behind the existing `RenderProvider` protocol.
When a TTS provider is configured, the measured narration duration is used to
reconcile scene timings before FFmpeg runs, so captions and visuals follow the
audio rather than an estimate. SVG assets are structurally validated when they
are generated; malformed, incorrectly sized, unreadable, or executable SVG
content is rejected before it can enter a render job.

Review evidence records the rendered file path, SHA-256, stream dimensions and
audio presence. It also includes a bounded deterministic FFmpeg frame-difference
sample and parses the adjacent SRT into scene-to-narration timing mappings.

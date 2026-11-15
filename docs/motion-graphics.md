# Local motion graphics mode

This mode turns the existing timed storyboard into a 9:16 MP4 without a video
generation model. It synthesizes narration **per timing beat**, keeps every
beat's allotted slot, draws moving counters and explanatory cards with Pillow,
burns short captions into the frames, writes an SRT sidecar, and encodes the
frames and audio with FFmpeg. The output includes a JSON visual plan that can
be edited and reused for the next render.

## Select the mode

Use [`knowledge-channel-motion-graphics.json`](../configs/knowledge-channel-motion-graphics.json)
or change these entries in an existing project configuration:

```json
{"name": "narration", "purpose": "Speak timed beats locally", "provider": "kokoro",
 "model": "models/kokoro-v1.0.onnx", "voices": "models/voices-v1.0.bin",
 "voice": "am_michael", "speed": 1.0}
{"name": "editor", "purpose": "Draw and assemble explanatory graphics",
 "provider": "motion-graphics", "width": 720, "height": 1280, "fps": 24}
```

The `video generator` capability is unnecessary in this mode. The lesson and
script generation workflow stays the same. The editor uses each scene's
`timing_sync` beats and narration excerpts; it does not parse visual prompts as
instructions for an image model.

Install FFmpeg on `PATH` and install the optional dependencies with a supported
Python version. The upstream `kokoro-onnx` package currently requires Python
below 3.14; Python 3.13 is a straightforward choice:

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv -e ".[motion,kokoro]"
```

Download `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the
[Kokoro ONNX model release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1)
into `models/`, or point the config at existing copies. Model files are ignored
by Git. Kokoro runs locally; no video-generation API is involved.

Run the ordinary local production command with the motion config:

```powershell
lattice-run-local configs/knowledge-channel-motion-graphics.json --offline
```

Remove `--offline` to use the configured lesson model. As with other production
paths, FFmpeg validates the exported video and stores a private review copy.

## Edit the resulting graphics

Next to the MP4, the renderer writes `*.motion-plan.json` and `*.srt`.
The JSON has one array per storyboard scene and one object per beat:

```json
{
  "version": 1,
  "scenes": {
    "scene-1": [
      {
        "motif": "tickets",
        "title": "Tickets closed",
        "note": "A ticket closes while the problem remains open",
        "left_label": "Tickets closed",
        "right_label": "Problems resolved",
        "left_start": 0,
        "left_end": 8,
        "right_start": 0,
        "right_end": 0
      }
    ]
  }
}
```

Set `motif` to `tickets` for a queue and customer state, or `metrics` for two
animated dashboard bars. Edit the labels, notes, and numeric endpoints to
change what moves on screen.
The renderer interpolates values within each beat. A plan can override only the
beats you want to customize; omitted beats use generated defaults. Set
`"plan": "path/to/edited.motion-plan.json"` on the editor tool to use it for a
new render. Scene IDs and beat counts must match the storyboard. Keep the
generated plan and narration together with a revision so edits remain
reproducible.

Short narration overruns are accelerated by at most 25%. Longer overruns fail
with a message identifying the beat, so the script or timing can be revised.
This protects the scene boundaries and the project duration limit.

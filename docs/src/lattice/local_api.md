# Local review API

[`local_api.py`](../../../src/lattice/local_api.py) exposes a small
standard-library HTTP API over `EpisodeRepository`:

- `GET /health`
- `GET /episodes`
- `GET /review-queue`
- `GET /episodes/{id}`
- `GET /episodes/{id}/reviews`
- `POST /episodes/{id}/review`
- `GET /media/{id}` when `media_root` is configured
- `GET /app` for the mobile-friendly browser review page

Set `LATTICE_REVIEW_TOKEN` to require `Authorization: Bearer <token>` on API
requests. The local `/app` shell prompts for the token and keeps it in memory;
it is never placed in a URL or persisted. Without the variable, the server is
intended only for localhost development. Binding beyond localhost still
requires a token, and the API is not a public authentication system.

Run it locally after installation:

```powershell
lattice-review-server `
  --database var\lattice.sqlite `
  --media-root var\lattice-artifacts\review-media
```

`lattice-run-local` stores generated review videos under
`var\lattice-artifacts\review-media` by default. The server's matching
`--media-root` setting makes those videos available to `/app` through the
contained `/media/{id}` route.

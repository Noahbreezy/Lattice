# Local review API

[`local_api.py`](../../../src/lattice/local_api.py) exposes a small
standard-library HTTP API over `EpisodeRepository`:

- `GET /health`
- `GET /episodes`
- `GET /episodes/{id}`
- `POST /episodes/{id}/review`

Set `LATTICE_REVIEW_TOKEN` to require `Authorization: Bearer <token>`.
Without the variable, the server is intended only for localhost development.
The API is not a public authentication system; production must replace this
boundary with OIDC, server-side authorization, CSRF protection, HTTPS, and
private signed media URLs.

Run it locally after installation:

```powershell
lattice-review-server --database var\lattice.sqlite
```

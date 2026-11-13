# Server and worker

[`deployment.py`](../../../src/lattice/deployment.py) provides `lattice-server`
and `lattice-worker`. They require `LATTICE_DATABASE_URL` and
`LATTICE_STORAGE_BUCKET`; `LATTICE_STORAGE_PREFIX` and
`LATTICE_S3_ENDPOINT_URL` are optional. The server also requires
`LATTICE_REVIEW_TOKEN` and accepts `LATTICE_REVIEWER_ID` for its audit identity.

The worker processes configured topics and rejected revisions. Use a Piper
voice on Linux or Windows SAPI on Windows. The server binds to loopback by
default; deploy it behind a TLS reverse proxy that authenticates the owner.
Its bearer token protects API, media, and artifact routes, and the mobile
review page accepts that token at runtime. The page itself contains no
credential. Keep the object bucket private and prevent direct public access
to the server port.

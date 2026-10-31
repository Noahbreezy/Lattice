# Lattice architecture

For module-level behavior, see the mirrored documentation index in
[`docs/README.md`](README.md).

Lattice is organized around a provider-independent content pipeline. A
configuration defines the behavior of a project; each production stage emits a
versioned artifact that can be inspected, approved, retried, or replaced.

## Pipeline contracts

The current local pipeline is:

```text
ProjectConfig
  -> Topic
  -> ResearchPacket
  -> Script
```

The contracts live in [`src/lattice/contracts.py`](../src/lattice/contracts.py).
`ResearchPacket` keeps claims linked to source indexes. This is deliberately
stricter than storing a source list beside a script: later review can identify
which evidence supports each claim.

The next planned stages are:

```text
Script
  -> Storyboard
  -> AssetManifest
  -> RenderJob
  -> PublishedVideo
```

## Server-hosted review workflow

The long-term product is a server-hosted application, not a local-only video
folder. A worker produces a final video into private object storage and marks
the episode `awaiting_review`. The browser application presents reviewable
videos in a swipe-friendly interface:

```text
generated -> awaiting_review -> approved -> ready_for_upload
                         \
                          -> rejected -> processing queue (front)
```

Rejections require feedback. The feedback is stored with an immutable review
record and is supplied to the next processing revision. Rejected work is
inserted ahead of untouched queued work, while the original video artifact and
revision remain auditable. Approved videos remain in private storage with a
stable artifact reference until the owner uploads them.

The domain rules are represented by [`src/lattice/review.py`](../src/lattice/review.py)
and the lifecycle contracts in
[`src/lattice/contracts.py`](../src/lattice/contracts.py). The current queue is
in-memory for testing; production persistence belongs in PostgreSQL.

## Authentication and security boundary

The future web app must be private by default:

- Require authentication for every API route and media download.
- Use a managed identity provider or a mature OIDC implementation; do not
  implement password hashing, session rotation, or MFA from scratch.
- Require MFA and short-lived sessions, with secure, HttpOnly, SameSite cookies.
- Enforce server-side authorization on every episode, review, and asset request;
  hiding UI controls is not authorization.
- Keep object storage private and issue short-lived signed URLs only after an
  authorized request.
- Store provider credentials in a server-side secret manager, never in browser
  code or project configuration committed to Git.
- Add CSRF protection for cookie-authenticated state-changing requests, HTTPS,
  rate limits, audit logs, dependency scanning, and backups before exposing the
  service publicly.

For a single-owner deployment, the authorization model can initially allow one
account identified by an environment-configured subject ID. It should still
use a real identity provider so the system can later support additional users
without replacing authentication.

## Local development pipeline

The dependency-free pipeline in
[`src/lattice/pipeline.py`](../src/lattice/pipeline.py) is a development
implementation, not a research system. Its research packet uses a clearly
marked placeholder source and an `unverified` claim. No generated output from
this path should be published without replacing the research stage with a real
provider and human review.

Lesson history is stored in a small JSON file through
[`src/lattice/history.py`](../src/lattice/history.py). Topic keys are normalized
before comparison, so punctuation and capitalization do not create false
novelty. This store will later be replaced by PostgreSQL without changing the
pipeline contracts.

Episode and review persistence is available through
[`src/lattice/persistence.py`](../src/lattice/persistence.py). It stores episode
status, private video references, queue priority, rejection feedback, and
immutable reviews in SQLite. Rejected episodes receive a lower queue priority,
so `claim_next()` returns them before untouched work. The adapter is local
development infrastructure; production should provide the same domain API
using PostgreSQL transactions and a connection pool.

## Storage retention

Large media belongs in private object storage, while server disk is temporary
working space. Project-specific count limits live under
`production.retention`. Cloud/server limits control physical location;
approved/rejected/awaiting-review limits control lifecycle state. A video can
exceed more than one limit, but the planner emits one deletion action per
artifact.

[`src/lattice/retention.py`](../src/lattice/retention.py) selects the oldest
excess artifacts without deleting them. This separation is intentional:
workers must audit the action, avoid deleting an actively processed or
reviewed artifact, and preserve the final approved master according to the
project policy. Future PostgreSQL records should keep storage location, object
key, size, checksum, and deletion audit metadata.

## Long-term infrastructure

- Python: API, orchestration, research, provider adapters, and quality checks.
- TypeScript: review and production dashboard.
- FFmpeg: encoding, subtitles, audio/video assembly, and platform exports.
- PostgreSQL: projects, episodes, claims, sources, jobs, approvals, and
  provenance metadata.
- S3-compatible object storage: media and intermediate artifacts.
- Rust: optional isolated workers only after profiling identifies a CPU-bound
  bottleneck.

Provider integrations must be adapters behind stable capabilities. A project
should refer to capabilities such as `video generator`, not embed a vendor API
throughout the domain model.

## Provenance and approvals

Future persistent artifacts should record configuration version, prompt version,
provider/model, input artifact IDs, content hash, timestamps, and human
approval state. AI review and human approval must remain separate states,
especially for medical, political, historical, and scientific content.

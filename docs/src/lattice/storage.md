# Private object storage

[`storage.py`](../../../src/lattice/storage.py) defines the storage boundary.
`LocalObjectStorage` writes beneath a validated local root. `S3ObjectStorage`
stores video, lesson, script, bundle, manifest, and evidence under private
S3-compatible keys and returns opaque `s3://` references. It never sets a
public access-control list or generates a public URL.

The authenticated review API reads objects server-side and streams media to
the browser. The bucket must be configured private; credentials are supplied
through the host's normal AWS credential chain. The local tests use a fake S3
client and do not exercise a live cloud service.

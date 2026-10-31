# Review queue

[`review.py`](../../../src/lattice/review.py) contains the in-memory
`ReviewQueue` used to test workflow rules without a web framework.

Queued and rejected episodes can enter processing. Rejected items are inserted
at the front of the queue. Processing episodes can be submitted for review.
Only awaiting-review episodes can be approved or rejected; rejection requires
feedback and is immediately requeued. Approval preserves the final video URI
for later upload. Reviews are retained as an immutable tuple exposed through
the `reviews` property.

Authentication and durable persistence belong to the server/API layer.

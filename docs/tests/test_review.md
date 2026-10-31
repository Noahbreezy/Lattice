# Review tests

[`test_review.py`](../../tests/test_review.py) defines the in-memory workflow
expectations: rejected episodes return before untouched work, approval keeps
the video reference, rejection requires feedback, and only awaiting-review
episodes can receive a decision.

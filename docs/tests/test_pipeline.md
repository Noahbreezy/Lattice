# Pipeline tests

[`test_pipeline.py`](../../tests/test_pipeline.py) verifies first-unused topic
selection, persisted completion history, claim-to-source index preservation,
script duration calculation, and rejection of invalid source links.

These tests intentionally exercise the provisional local pipeline and should
remain separate from tests for future provider integrations.

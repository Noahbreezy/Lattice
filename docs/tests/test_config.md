# Configuration tests

[`test_config.py`](../../tests/test_config.py) verifies that the example
configuration loads, invalid video lengths and negative retention limits are
rejected, and malformed JSON produces `ConfigError`.

When configuration validation changes, extend these tests with the new invalid
shape or boundary and update the example fixture if its contract changes.

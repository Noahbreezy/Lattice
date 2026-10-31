# Configuration domain

[`config.py`](../../../src/lattice/config.py) converts JSON mappings into
validated immutable `ProjectConfig` and `RetentionSettings` values.

## Validation rules

`project`, `content`, and `production` must be objects. Required strings and
string arrays must be non-empty. Video length is an integer from 1 through
3600 seconds. Topic seeds, AI tools, and retention limits have dedicated
shape checks; retention values are non-negative integers or `null`.

`load_config` reads UTF-8 JSON and turns missing files, malformed JSON, and
read failures into explicit `ConfigError` messages. Validation happens before
the configuration reaches pipeline or infrastructure code.

When `production.retention` is present, omitted limits keep their documented
defaults. An explicit `null` still means unlimited retention.

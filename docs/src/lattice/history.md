# Lesson history

[`history.py`](../../../src/lattice/history.py) provides `LessonHistory`, a
small JSON-backed store used before database history exists.

Topics are stored by normalized key, so punctuation and capitalization do not
create duplicates. Topic reservation and recording use an OS-level lock so
concurrent workers cannot select the same seed. Recording creates parent
directories and writes a sorted array. Missing history means no topics have
been completed. Existing files must contain an array of strings; I/O and JSON
shape failures are explicit `ValueError`s.

---
description: After a schema, contract or config change, find every fixture, factory and dataset that no longer matches and fix it, so tests stop passing on data the system can't produce.
argument-hint: "[changed table, field or contract]"
---
# /check-fixtures: fixtures follow the schema

1. List what changed (tables, fields, enums, contract shapes, config keys).
2. Find every fixture, factory, seed and dataset that mentions them.
3. **Read each fixture before its test:** what state does it never reach? Does any negative assertion pass only because the fixture is empty?
4. Update fixtures through the same constructors and generators the code uses; released eval datasets are never edited: make a new release instead.
5. Run `make test` and confirm the counts of tests collected didn't drop.

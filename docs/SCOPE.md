# Scope

Vertical slices in delivery order, each with a "complete only when" condition. Rows are counted by
`make status`, so the scope can't silently drift (10/H14). Status is one of: next · in progress · done · dropped.

| # | Slice | Complete only when | Status |
|---|---|---|---|
| S1 | `OPEN`: defined after `/discover` and ADR-0001 | | next |

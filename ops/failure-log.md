# Failure log

Every failure, loud or quiet, with how it was detected and the hardening it produced (10/H17). Append-only:
add new entries at the end; never edit an old one (the protect hook enforces it).

Entry format:

```
## F-NNN short title
- Date · loud or quiet · detected by
- What happened
- Root cause
- Hardening (deny rule or hook · skill · path rule · STATE or ADR · test or eval), with a link
```

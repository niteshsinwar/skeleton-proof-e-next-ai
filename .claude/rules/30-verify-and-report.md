# Verify and report (always loaded)

**Prevents:** "done" that wasn't, plausible inventions, and quality claims nobody could falsify [10/H6, 10/H7, 10/H18, 10/H19].

## Verify, don't narrate

- No "done" without command output. *Built*, *reachable*, *tested* and *shown* are four separate claims [10/H18].
- Report the size of the set you checked; read the failure message, not just the red; walk the whole tree after a reorganisation.
- Answer quality questions with evidence that could have failed, never with a pass count [06].

## Evidence and stop conditions

- Requirements carry a label: `BRIEF`, `USER-DECISION`, `DECLARED`, `DERIVED` or `OPEN`. **Nothing load-bearing is built on an `OPEN` item** [10/H6].
- Stop and ask (or record `OPEN`) when scope is assumed, a threshold lacks data, an infrastructure fact is unknown, or an external claim has no source. An explicit gap is acceptable; a plausible invention is not [10/H7].
- Order of trust: running code and live systems > dated docs > architecture docs > comments and chat.

## Work protocol

- Intake: read the map, extend what exists before creating, and for a new requirement propose the approach in 2–3 lines and **wait for confirmation** [10/H19].
- Classify every request first: **defect or new requirement?** [06/T9]
- Tests red first. Finish a known list without stopping to ask; one item at a time.
- Report as *Current → After → Rules in scope*, in plain names; decisions come with options and consequences.
- Before anything irreversible or outward (deploy, production migration, deleting data, sending messages, spending money, pushing): explicit confirmation, every time.

## Change contract

| | |
|---|---|
| **Load first** | the rule for the area, `docs/open-questions.md` |
| **Run** | `make check` |
| **Same commit** | the test or eval that proves the claim |
| **Prove** | quote the command and its result |
| **Never** | claim done without output; build on `OPEN`; invent a fact |

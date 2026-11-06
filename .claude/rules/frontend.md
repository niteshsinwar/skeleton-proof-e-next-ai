---
paths:
  - "apps/web/**"
  - "docs/design/**"
---
# Frontend

**Prevents:** type drift from the API, raw ids on screen, unearned audit claims, layout shift, polling storms, and auth checked only in middleware [03].

- Routes are thin; logic lives in `lib/` where it is unit-tested; split at the client boundary; components by business area plus `shell/` and `ui/` [03/F1–F3].
- One transport and one client module per resource, with types generated from the OpenAPI (never edited); API ↔ UI sync checked [03/F4, 03/F5]. Server reads by default (Next), TanStack Query for interactive data [03/F6, 03/FL3]. Writes go through one helper with `If-Match` [03/F7]. Authoritative data isn't cached beyond the request [03/F8]. The URL is state [03/F10].
- Tokens only (no literal colours, sizes or inline styles); identity and judgement colours never touch; closed scales; every data component has empty, error and loading states [03/F11–F14]. Motion only for state change [03/F15].
- One labels module; no engineering vocabulary on screen; design per persona; journeys, not tabs [03/F16–F18].
- Large data stays off the main thread and out of the DOM: cursor pages or virtualised lists, debounced inputs [03/F29]. Empty states teach the first action; destructive actions name the object, confirm, and offer undo where reversible [03/F45].
- AI output shows provenance, is marked as AI-drafted, shows what it couldn't verify; abstention is never shown as agreement; consequential actions are deliberate; traces show recorded reasons [03/F19–F21].
- Budgets at p75: LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1, checked in CI [03/F26, 03/FL10]. Suspense near the data; layout-matched skeletons; optimistic only when reversible [03/F27, 03/F28].
- Every query declares its freshness; transport by change rate; poll only while visible and with a stop condition; honour `Retry-After` [03/F31–F34]. SSE by default; resume from the event log; no token in a URL [03/F35–F37].
- Nonce CSP; CSRF in depth; never authorise in middleware alone [03/F38–F40]. Readable text that survives WCAG text spacing; one type scale [03/F41, 03/F42]. Forms keep input on failure [03/F43].
- WCAG 2.2 AA measured with axe; the artefact you ship is the artefact you test [03/F22, 03/F24]. Every screen passes the six-lens review [03/F47].

## Change contract

| | |
|---|---|
| **Load first** | `docs/design/00-design-language.md`, the area's components |
| **Run** | typecheck · lint · unit · build · e2e smoke + axe (via `make check`) |
| **Same commit** | regenerated API types if the API changed · labels for new identifiers · a `docs/design/ui-decisions.md` row for a new pattern |
| **Prove** | the e2e journey passes on the built artefact |
| **Never** | a literal colour · an inline style · a raw id on screen · a client-only permission · an audit claim the UI didn't earn |

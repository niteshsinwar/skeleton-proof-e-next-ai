# UI decisions

One row per UI pattern: what was decided and why. Changes after design review are allowed, and logged here.

| Decision | Why | Date |
|---|---|---|
| Text uses the system font stack; a self-hosted variable font arrives with a brand (`next/font`, one family + one mono) | Nothing downloads, so nothing shifts (03/F30); one family, few sizes (03/F42) | 2026-11-04 |
| Every on-screen word lives in `lib/labels.ts`; ESLint `react/jsx-no-literals` and a source test refuse inline copy (the catalogue's samples are exempt) | Readiness for other languages and one vocabulary (03/F16, F55) | 2026-11-04 |
| Two minutes before the session ends, a notice offers to sign in again in a new window; the page and its input stay | Re-authenticate without losing form state (03/F40) | 2026-11-04 |

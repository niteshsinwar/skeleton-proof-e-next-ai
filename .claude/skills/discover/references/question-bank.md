# Question bank: what Claude asks or confirms instead of assuming (11 §7)

## The asking rule

- **Ask** when the answer changes the work and has no safe default: scope, authority (who decides or approves), anything irreversible, money, personal or regulated data, security posture, infrastructure facts, AI quality thresholds, external facts without a source.
- **Don't ask:** conventional defaults; anything already decided (read the ADRs and STATE first); "shall I continue?" in the middle of a known list.
- **How:** one decision per question; current situation → options with consequences → recommendation.
- **Record** the answer as `USER-DECISION` (an ADR or a resolved open question) so it is never asked twice. Unanswered means `OPEN`, and nothing load-bearing is built on it.

## The bank

| When | Ask or confirm |
|---|---|
| **Project start** | Who are the users and personas, and what job do they do today (time, cost)? · What number says it works, by when, and who signs off? · What happens when the system is wrong: reversible or not, who is accountable? · What data exists, where, who owns it, access rules, retention, PII or regulated? · What must it integrate with, and which security or compliance reviews apply? · Volume, peaks, latency, availability? · Monthly budget for infrastructure and AI? · Non-goals and deadline? · Who runs it after handoff? · **Could plain rules or search solve enough without AI?** |
| **Shape** | Tier (P/S/E)? Where must it run (cloud account, region, residency)? Single or multi-tenant, and how many tenants? Which roles and personas exist? |
| **Data model** | Each entity's lifecycle · what must never be deleted · retention per data class · soft vs hard delete · history or versioning needs · money, units and time zones · the tenancy boundary · who may see which rows |
| **API** | Who consumes it (own UI, partners, AI agents or MCP clients)? Public or internal? What versioning promise? Which writes must be idempotent? Rate-limit expectations? Webhooks in or out? |
| **Auth and permissions** | Which identity provider, or local accounts? MFA required? Roles → capabilities matrix · separation of duties · who approves what · how agents and machines authenticate · session lifetime |
| **Frontend and UX** | Personas' devices · accessibility level · existing brand or design system · languages · which data must be real-time · offline needs · public SEO pages |
| **AI** | What may the AI decide vs suggest vs never touch (ownership table)? Cost of a wrong output? Required evidence or citations? Acceptable abstention rate? **Quality threshold, and is there eval data to measure it?** Which data may go to which provider (ZDR, BAA, residency)? Latency and cost budget per task? Where do humans review? |
| **Integrations** | Is there a sandbox? Who owns the credentials? Their rate limits? How stable is the contract? What may we write? Expected failure behaviour? |
| **Security** | Likely attackers · compliance regime · secret manager available · pen-test or audit needs · incident contacts |
| **Operations** | Environments · who deploys · owner and on-call · SLOs · backup RPO/RTO · monitoring stack · budget alerts |
| **How to elicit** | Depth → interviews or shadowing · alignment → a workshop · scale → a survey · existing system → document analysis. Map stakeholders by influence × interest; record a RACI for decisions; **silence is not consent** |
| **Shaping requirements** | Type of each requirement (business, stakeholder, functional, non-functional, transition, regulatory)? MoSCoW priority? Acceptance criteria as Given-When-Then? Capacity assumptions (read/write mix, peak multiplier, latency target)? For AI features: KPI, feasibility and a data-readiness inventory before design |
| **Every change** | **Defect or new requirement?** · Which areas, files and registry entries are affected? · Extend something existing, or is new justified? · Edge cases, error handling, bulk behaviour? · Test-data impact? → propose the approach in 2–3 lines and wait for confirmation |
| **Before anything irreversible or outward** | Deploy · production migration · deleting data · sending messages · spending money · push → explicit confirmation every time |

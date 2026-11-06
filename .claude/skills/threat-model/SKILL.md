---
description: Build or update the threat model, sized by tier, whenever a trust boundary moves (new integration, upload path, tool, tenant model or AI step).
---
# /threat-model: sized for tier E

1. Draw the data-flow diagram, including retention settings and every trust boundary.
2. Run STRIDE per boundary; fill in the layered safety stack and how each layer fails.
3. Walk the OWASP LLM Top 10 and Agentic Top 10 maps; write the incident playbook.
4. Review it with security **before launch**.

Then add a negative test for each new control. Record changes in `docs/architecture/security.md`.

**Rules in scope:** `.claude/rules/security.md`.

# MCP servers: the allowlist register (10/H22)

`.mcp.json` lists the servers this project may use. Each one is reviewed like a dependency before it is added, and
gets a row here in the same commit; `make harness-check` fails on a server without a row. Removing a server removes
its row.

| Server | Owner | Scopes and data it can reach | Pinned version | Tool descriptions read (date) |
|---|---|---|---|---|

## What the settings can and can't enforce (READ, verified 2026-11-04 against code.claude.com/docs/en/mcp and /settings)

- Claude Code asks before using a project server from `.mcp.json` in an interactive session; in `claude -p` runs,
  Agent SDK sessions and cloud sessions it loads them without asking. That is why every row above is reviewed first.
- `enableAllProjectMcpServers` or `enabledMcpjsonServers` committed to `.claude/settings.json` is ignored in an
  untrusted folder: a cloned repository can't approve its own servers. This project sets the first to `false`.
- A `disabledMcpjsonServers` entry in any settings file rejects a server in every permission mode.
- Servers a person adds in their own user settings can't be blocked by the project; only managed settings
  (`deniedMcpServers`, `allowManagedMcpServersOnly`) can. The value format of `allowedMcpServers` was seen only in a
  summary (RETRIEVED), so it is not used here.

Re-verify within 21 days of the date above (10/H17).

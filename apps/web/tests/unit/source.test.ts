// Checks that read the source itself (03 §3 replays). Each reports how much it examined (10/H18).
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import openapiTS, { astToString } from "openapi-typescript";
import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..", "..");
const CONTRACT = join(ROOT, "..", "..", "packages", "contracts", "openapi.json");
const SKIP = new Set(["node_modules", ".next", "test-results", "playwright-report", "generated"]);

function files(dir: string, ext: RegExp): string[] {
  return readdirSync(dir).flatMap((name) => {
    if (SKIP.has(name)) return [];
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path, ext) : ext.test(name) ? [path] : [];
  });
}

describe("design tokens (03/F11, F13)", () => {
  it("no colour literal appears outside the tokens file", () => {
    const sources = ["app", "components", "lib"].flatMap((d) => files(join(ROOT, d), /\.(tsx?|css)$/));
    expect(sources.length).toBeGreaterThan(10);
    const literal = /#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?|oklch|oklab)\(/;
    const offenders = sources
      .filter((f) => !f.endsWith("globals.css"))
      .filter((f) => literal.test(readFileSync(f, "utf8")))
      .map((f) => relative(ROOT, f));
    expect(offenders).toEqual([]);
  });
});

describe("on-screen words (03/F16, F55)", () => {
  // ESLint's react/jsx-no-literals covers text inside elements; this covers what it can't see: words passed as
  // props, and messages built in code. The catalogue is exempt by name (its words are samples, B3-4).
  const USER_PROPS =
    /\b(title|body|label|hint|description|caption|placeholder|aria-label|alt|error)="[^"]*[A-Za-z]{2,}/;
  const USER_FIELDS = /\b(title|description|error|body|detail)\s*:\s*"[^"]*[A-Za-z]+ [A-Za-z]+/;

  it("keeps every user-facing string in lib/labels.ts", () => {
    const sources = ["app", "components"]
      .flatMap((d) => files(join(ROOT, d), /\.tsx?$/))
      .filter((f) => !["components/catalogue.tsx", "components/ai/catalogue-ai.tsx"].includes(relative(ROOT, f)));
    expect(sources.length).toBeGreaterThan(15);
    const offenders = sources.flatMap((f) =>
      readFileSync(f, "utf8")
        .split("\n")
        .map((line, i) => ({ line, at: `${relative(ROOT, f)}:${i + 1}` }))
        .filter(({ line }) => !line.trim().startsWith("//") && (USER_PROPS.test(line) || USER_FIELDS.test(line)))
        .map(({ at }) => at),
    );
    expect(offenders).toEqual([]);
  });
});

describe("test collection (03/F23)", () => {
  it("collects every test file, so a new folder can't go silently untested", () => {
    const tests = files(join(ROOT, "tests"), /\.test\.tsx?$/);
    expect(tests.length).toBeGreaterThanOrEqual(3);
  });
});

describe("API ↔ UI (03/F4, F5)", () => {
  // Operations the web UI deliberately doesn't call, each with its reason.
  const SERVER_ONLY: Record<string, string> = {
    "GET /health": "platform probe",
    "GET /ready": "platform probe",
    "POST /admin/flags/{key}/set": "admin control plane, not part of this UI yet",
    "POST /admin/roles/{subject}/grant": "admin control plane, not part of this UI yet",
    "POST /admin/roles/{subject}/revoke": "admin control plane, not part of this UI yet",
    "POST /admin/changes/{change_id}/approve": "admin control plane, not part of this UI yet",
    "POST /admin/changes/{change_id}/reject": "admin control plane, not part of this UI yet",
    "POST /uploads": "no upload screen in the example slice yet",
    "POST /documents": "no document screen yet: documents arrive from an admin tool or a job",
    "POST /documents/search": "called by AI steps on the server; no search screen yet",
    "DELETE /documents/{document_id}": "erasure runs from the admin control plane, not part of this UI yet",
    "GET /ai/mcp/servers": "admin control plane for outside MCP servers, not in this UI yet",
    "PUT /ai/mcp/servers/{server}/connection": "admin control plane for outside MCP servers, not in this UI yet",
    "DELETE /ai/mcp/servers/{server}/connection": "admin control plane for outside MCP servers, not in this UI yet",
    "POST /ai/mcp/servers/{server}/review": "admin control plane for outside MCP servers, not in this UI yet",
    "POST /webhooks/{source}": "called by other systems, never by the UI",
  };

  it("every API operation has a call site or a reason it doesn't", () => {
    const spec = JSON.parse(readFileSync(CONTRACT, "utf8")) as { paths: Record<string, Record<string, unknown>> };
    const ops = Object.entries(spec.paths).flatMap(([path, methods]) =>
      Object.keys(methods).map((m) => `${m.toUpperCase()} ${path}`),
    );
    expect(ops.length).toBeGreaterThanOrEqual(10);
    const calls = files(join(ROOT, "lib", "api"), /\.ts$/)
      .map((f) => readFileSync(f, "utf8"))
      .join("\n");
    const missing = ops.filter((op) => {
      const [method, path] = op.split(" ");
      return !SERVER_ONLY[op] && !calls.includes(`${method}("${path}"`);
    });
    expect(missing).toEqual([]);
    const stale = Object.keys(SERVER_ONLY).filter((op) => !ops.includes(op));
    expect(stale).toEqual([]);
  });

  it("the generated client matches the committed contract (regenerate with pnpm gen:api)", async () => {
    const fresh = astToString(await openapiTS(new URL(`file://${CONTRACT}`)));
    const committed = readFileSync(join(ROOT, "lib", "api", "generated", "schema.d.ts"), "utf8");
    const body = (s: string) => s.replace(/^\/\*\*[\s\S]*?\*\/\s*/, "").trim();
    expect(body(committed)).toBe(body(fresh));
  });
});

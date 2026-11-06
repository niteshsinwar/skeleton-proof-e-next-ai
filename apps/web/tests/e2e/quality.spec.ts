// Quality gates measured on the built artefact (03 §3 replays): accessibility, security headers, nothing blocked by
// the CSP, no raw ids, assets served, credentials refused in realtime URLs, a Web Vitals lab check and a JavaScript
// budget per route.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { signInPage } from "./sign-in";

const signIn = (page: Page, user = "alice") => signInPage(page, user);

/** Create an item and wait for ITS page: the list page has a level-1 heading too, so wait on the URL and title. */
async function createItem(page: Page, title: string): Promise<string> {
  await page.getByLabel("Title").fill(title);
  await page.getByRole("button", { name: "Create work item" }).click();
  await expect(page).toHaveURL(/\/work-items\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  return page.url();
}

/** Name every violating node, so a failure says what to fix, not only how many (10/H18). */
async function noViolations(page: Page): Promise<void> {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const found = result.violations.flatMap((v) =>
    v.nodes.map(
      (n) =>
        `${v.id}: ${n.target.join(" ")}${n.failureSummary ? ` (${n.failureSummary.split("\n").pop()?.trim()})` : ""}`,
    ),
  );
  expect(found).toEqual([]);
}

test("key pages have no WCAG 2.2 AA violations (03/F22)", async ({ page }) => {
  // Check settled screens: with reduced motion the stylesheet turns transitions off (03/F15), so a control is never
  // measured half-way through its fade (a button fading in after it became enabled once read as 2.3:1).
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await noViolations(page);
  await page.goto("/catalogue");
  await noViolations(page);
  await page.getByRole("button", { name: "Open the side panel" }).click();
  await expect(page.getByRole("dialog", { name: "Details" })).toBeVisible();
  await noViolations(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await signIn(page);
  await noViolations(page);
  await createItem(page, `Accessible ${Date.now()}`);
  // Check the page once it has finished rendering: the assistant section arrives after the item, and checking before
  // it exists made this test pass or fail by timing (06/T6).
  await expect(page.getByRole("heading", { name: "Ask the assistant" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Brief me on this item" })).toBeVisible();
  await noViolations(page);
});

test("every page carries a nonce CSP and the security headers (03/F38)", async ({ page }) => {
  const response = await page.goto("/");
  const headers = response!.headers();
  const csp = headers["content-security-policy"] ?? "";
  expect(csp).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
  expect(csp).not.toContain("unsafe-inline");
  expect(csp).not.toContain("unsafe-eval");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(headers["x-powered-by"]).toBeUndefined();
});

test("nothing on the key pages is blocked by the CSP (03/F38)", async ({ page }) => {
  const blocked: string[] = [];
  page.on("console", (message) => {
    if (/Content Security Policy/i.test(message.text())) blocked.push(message.text());
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) =>
      console.error(`Content Security Policy: ${e.violatedDirective}`),
    );
  });
  await page.goto("/catalogue");
  await page.getByRole("button", { name: "Open the side panel" }).click();
  await expect(page.getByRole("dialog", { name: "Details" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Show a toast" }).click();
  await expect(page.getByText("Your change is in place.")).toBeVisible();
  await signIn(page);
  await createItem(page, `Policy ${Date.now()}`);
  expect(blocked).toEqual([]);
});

test("no raw identifiers reach the screen (03/F16)", async ({ page }) => {
  await signIn(page);
  const itemUrl = await createItem(page, `Readable ${Date.now()}`);
  for (const path of ["/work-items", itemUrl]) {
    await page.goto(path);
    const text = await page.locator("body").innerText();
    expect(text).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
    expect(text).not.toMatch(/\b[a-z]+_[a-z_]+\b/);
    // People appear by name: the header and the owner say "Alice", whatever her subject looks like.
    await expect(page.getByText("Signed in as Alice")).toBeVisible();
    await expect(page.getByText("Alice", { exact: true }).first()).toBeVisible();
  }
});

test("the built artefact serves its assets (03/F24)", async ({ page, request }) => {
  await page.goto("/");
  const assets = await page
    .locator('link[rel="stylesheet"], script[src]')
    .evaluateAll((els) =>
      els.map((e) => e.getAttribute("href") ?? e.getAttribute("src")).filter((u): u is string => Boolean(u)),
    );
  expect(assets.length).toBeGreaterThan(0);
  for (const asset of assets) expect((await request.get(asset)).status()).toBe(200);
});

test("realtime refuses credentials in the URL and unauthenticated streams (03/F36)", async ({ request }) => {
  expect((await request.get("/api/work-items/x/stream?access_token=abc")).status()).toBe(400);
  expect((await request.get("/api/work-items/x/stream")).status()).toBe(401);
});

test("Web Vitals lab check on the built list page (03/F26; field p75 comes from /api/vitals)", async ({ page }) => {
  await signIn(page);
  await page.goto("/work-items");
  await page.getByLabel("Title").click();
  await page.keyboard.type("abc");
  const vitals = await page.evaluate(
    () =>
      new Promise<{ lcp: number; cls: number; inp: number }>((resolve) => {
        let lcp = 0;
        let cls = 0;
        let inp = 0;
        new PerformanceObserver((l) => l.getEntries().forEach((e) => (lcp = Math.max(lcp, e.startTime)))).observe({
          type: "largest-contentful-paint",
          buffered: true,
        });
        new PerformanceObserver((l) =>
          l.getEntries().forEach((e) => (cls += (e as unknown as { value: number }).value)),
        ).observe({ type: "layout-shift", buffered: true });
        new PerformanceObserver((l) => l.getEntries().forEach((e) => (inp = Math.max(inp, e.duration)))).observe({
          type: "event",
          buffered: true,
          durationThreshold: 16,
        } as PerformanceObserverInit);
        setTimeout(() => resolve({ lcp, cls, inp }), 1000);
      }),
  );
  // The measurement itself must have worked, or the budget check would pass on nothing (10/H18).
  expect(vitals.lcp).toBeGreaterThan(0);
  expect(await page.evaluate(() => PerformanceObserver.supportedEntryTypes.includes("event"))).toBe(true);
  expect(vitals.lcp).toBeLessThanOrEqual(2500);
  expect(vitals.cls).toBeLessThanOrEqual(0.1);
  expect(vitals.inp).toBeLessThanOrEqual(200);
});

/**
 * Compressed JavaScript one route loads (03/F26 "a JS budget per route"). The skeleton measured 173 KB on the
 * landing page and 192 KB on the work-item pages (Next.js 16, React 19, Base UI, TanStack Query); the budget
 * leaves about 15% for the first features. Raise it only with a reason in the PR.
 */
const JS_BUDGET_BYTES = 220_000;

async function scriptBytes(page: Page): Promise<number> {
  await page.waitForLoadState("networkidle");
  return page.evaluate(() =>
    performance
      .getEntriesByType("resource")
      .filter((e) => (e as PerformanceResourceTiming).initiatorType === "script")
      .reduce((sum, e) => sum + (e as PerformanceResourceTiming).encodedBodySize, 0),
  );
}

test("each key route stays inside its JavaScript budget (03/F26)", async ({ page }) => {
  const sizes: Record<string, number> = {};
  await page.goto("/");
  sizes["landing"] = await scriptBytes(page);
  await signIn(page);
  const itemUrl = await createItem(page, `Budget ${Date.now()}`);
  await page.goto("/work-items");
  sizes["list"] = await scriptBytes(page);
  await page.goto(itemUrl);
  sizes["item"] = await scriptBytes(page);
  console.log(`JS bytes per route: ${JSON.stringify(sizes)}`);
  for (const [route, bytes] of Object.entries(sizes)) {
    expect(bytes, `${route}: measured, not assumed (10/H18)`).toBeGreaterThan(0);
    expect(bytes, `${route}: over budget`).toBeLessThanOrEqual(JS_BUDGET_BYTES);
  }
});

test("with no provider key the assistant says it is unavailable, and the item still works (01/R5)", async ({
  page,
}) => {
  await signInPage(page, "alice");
  await createItem(page, "Pay invoice 77 for the warehouse"); // lands on the item's own page
  await expect(page.getByRole("status").filter({ hasText: "can't be reached" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Pay invoice 77 for the warehouse");
  await noViolations(page);
});

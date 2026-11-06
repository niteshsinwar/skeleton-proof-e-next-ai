// How the e2e specs become a user. The mock issuer signs in whoever the login hint names (development only).
import { expect, type Browser, type Page } from "@playwright/test";

/** Sign this page's browser in as `user` and land on the work items. */
export async function signInPage(page: Page, user: string): Promise<void> {
  await page.goto(`/auth/login?hint=${user}`);
  await expect(page).toHaveURL(/\/work-items$/);
}

/** A new browser context signed in as `user`, for journeys with more than one person on screen. */
export async function signIn(browser: Browser, user: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signInPage(page, user);
  return page;
}

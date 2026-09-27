import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.goto("/#/page/observatory");
  await page.getByText("Sign in with a password", { exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill("agent@example.com");
  await page
    .getByLabel("Password", { exact: true })
    .fill("SyntheticUserPassword123!");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Observatory", exact: true }),
  ).toBeVisible();
}

test("published reader: navigation, evidence, safe Markdown, live updates, history and session revocation", async ({
  page,
  context,
  request,
}) => {
  const remoteRequests: string[] = [];
  page.on("request", (event) => {
    if (event.url().includes("invalid.example"))
      remoteRequests.push(event.url());
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const control = async (action: string) => {
    const response = await request.post(
      process.env.WIKICONTEXT_TEST_CONTROL + action,
    );
    expect(response.ok(), await response.text()).toBeTruthy();
  };
  await login(page);
  await expect(
    page.getByText("Published edition 1.", { exact: false }),
  ).toBeVisible();
  await expect(page.locator("table")).toContainText("Telescope");
  await expect(page.locator("script:not([src])")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => (window as Window & { wikiInjected?: boolean }).wikiInjected,
    ),
  ).toBeUndefined();
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
  expect(remoteRequests).toEqual([]);

  await page.getByRole("button", { name: "Citation 1", exact: true }).click();
  await expect(
    page.getByText("Observatory source", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText(
      "The synthetic observatory opened in 2026. Its telescope studies stars.",
      { exact: false },
    ),
  ).toBeVisible();
  const originalLink = page.getByRole("link", { name: /Open original/ });
  await expect(originalLink).toBeVisible();
  const originalResponse = await request.get(
    (await originalLink.getAttribute("href"))!,
  );
  expect(originalResponse.ok()).toBeTruthy();
  expect(await originalResponse.text()).toBe(
    "The synthetic observatory opened in 2026. Its telescope studies stars.\n",
  );
  const downloadPromise = new Promise<import("@playwright/test").Download>(
    (resolve) => {
      page.once("download", resolve);
      context.once("page", (popup) => popup.once("download", resolve));
    },
  );
  await originalLink.click();
  const download = await downloadPromise;
  expect(await download.failure()).toBeNull();
  expect(await readFile((await download.path())!, "utf8")).toBe(
    "The synthetic observatory opened in 2026. Its telescope studies stars.\n",
  );
  await page.bringToFront();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Citation 1", exact: true })).toBeFocused();
  await page.getByRole("link", { name: "the telescope", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Telescope", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/^BACKLINKS/)).toBeVisible();
  await page
    .getByRole("link", { name: "Observatory", exact: true })
    .last()
    .click();
  await expect(
    page.getByRole("heading", { name: "Observatory", exact: true }),
  ).toBeVisible();

  const search = page.getByLabel("Search pages", { exact: true });
  await search.fill("telescope");
  await expect(
    page.getByRole("link", { name: "Telescope", exact: true }).first(),
  ).toBeVisible();
  await search.fill("");
  await search.focus();
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe(
    "BODY",
  );

  await page.screenshot({
    path: "/tmp/wikicontext-reader-desktop.png",
    fullPage: true,
  });

  await control("/stage");
  await page.reload();
  await expect(
    page.getByText("Published edition 1.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Published edition 2.", { exact: false }),
  ).toHaveCount(0);
  await control("/publish");
  await expect(
    page.getByText("Published edition 2.", { exact: false }),
  ).toBeVisible();

  const history = page.getByLabel("Publication", { exact: true });
  await history.selectOption({ label: "Publication 1" });
  await expect(
    page.getByText("Published edition 1.", { exact: false }),
  ).toBeVisible();
  await control("/publish");
  await expect(
    history.locator("option", { hasText: "Publication 3" }),
  ).toHaveCount(1);
  await expect(
    page.getByText("Published edition 1.", { exact: false }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Published edition 1.", { exact: false }),
  ).toBeVisible();
  await history.selectOption("live");
  await expect(
    page.getByText("Published edition 3.", { exact: false }),
  ).toBeVisible();

  await context.setOffline(true);
  await control("/publish");
  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(
    page.getByText("Published edition 4.", { exact: false }),
  ).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Observatory", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();

  await page.screenshot({
    path: "/tmp/wikicontext-reader-mobile.png",
    fullPage: true,
  });

  await control("/disable");
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(
    page.getByText("Sign in with a password", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Published edition 4.", { exact: false }),
  ).toHaveCount(0);
  await control("/enable");
  await page.setViewportSize({ width: 1280, height: 900 });
  await login(page);
  // A cached token cannot display content before server session validation.
  await control("/disable");
  let releaseRefresh: () => void = () => {};
  const refreshGate = new Promise<void>((resolve) => {
    releaseRefresh = resolve;
  });
  await page.route("**/api/collections/users/auth-refresh", async (route) => {
    await refreshGate;
    await route.continue();
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(
    page.getByText("Published edition 4.", { exact: false }),
  ).toHaveCount(0);
  releaseRefresh();
  await expect(
    page.getByText("Sign in with a password", { exact: true }),
  ).toBeVisible();
  await page.unroute("**/api/collections/users/auth-refresh");
  await control("/enable");
  await login(page);
  await page.getByRole("button", { name: /Sign out/ }).click();
  await expect(
    page.getByText("Sign in with a password", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Sign in with a password", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Published edition 4.", { exact: false }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});

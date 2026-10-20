import { expect, test } from "@playwright/test";

const projects = [
  {
    id: "sample-app",
    source_checkout: "/Users/developer/projects/sample-app",
    source: "/Users/developer/projects/sample-app/.lodex/project.toml",
  },
  {
    id: "lodex",
    source_checkout: "/Users/developer/projects/lodex",
    source: "/Users/developer/projects/lodex/.lodex/project.toml",
  },
];
const tasks = [
  {
    id: "feature-one",
    project: "sample-app",
    branch: "feature/project-console",
    services: [
      { name: "api", state: "running", url: "http://127.0.0.1:8400" },
      { name: "web", state: "running", url: "http://127.0.0.1:8401" },
      { name: "worker", state: "failed" },
    ],
  },
  {
    id: "feature-two",
    project: "sample-app",
    branch: "fix/worker-reconnect",
    services: [{ name: "api", state: "stopped" }],
  },
  {
    id: "main-checkout",
    project: "lodex",
    branch: "main",
    services: [],
    main: true,
    owned: false,
  },
  {
    id: "missing-checkout",
    project: "lodex",
    branch: "chore/old-environment",
    services: [],
    state: "missing",
    config_status: "missing",
  },
].map((t) => ({
  state: "present",
  config_status: "valid",
  owned: true,
  main: false,
  path: `/Users/developer/.lodex/projects/${t.project}/${t.id}`,
  configuration_path: `/Users/developer/.lodex/projects/${t.project}/${t.id}/.lodex/project.toml`,
  cleanup: { available: true },
  commands: ["prepare", "verify", "cleanup"],
  configured_services: t.services.map((s) => s.name),
  operations: [
    {
      id: `${t.id}-prepare`,
      command: "prepare",
      state: "succeeded",
      started_at: "2026-10-08T09:10:00Z",
      exit_code: 0,
    },
    {
      id: `${t.id}-verify`,
      command: "verify",
      state: "interrupted",
      started_at: "2026-10-08T09:20:00Z",
    },
  ],
  environment: {
    values: { PORT: "8400", LONG_VALUE: "a".repeat(180) },
    secret_refs: { API_KEY: "secret:sample-app-api" },
  },
  known_resources: [
    {
      name: "database",
      kind: "postgres",
      id: `${t.id}-db`,
      state: "created",
      scope: "taskenv",
      observed_at: "2026-10-08T09:10:00Z",
    },
  ],
  ...t,
}));

test("filters, deep links, browser history and mobile navigation preserve context", async ({
  page,
}) => {
  const writes: string[] = [];
  await page.route("**/api/state", (route) =>
    route.fulfill({
      json: {
        ok: true,
        result: {
          projects,
          taskenvs: tasks,
          secrets: ["sample-app-api", "test-token"],
        },
      },
    }),
  );
  await page.route("**/api/task/*", (route) =>
    route.fulfill({
      json: {
        ok: true,
        result: tasks.find((t) => route.request().url().endsWith(t.id)),
      },
    }),
  );
  await page.route("**/api/action", (route) => {
    writes.push(route.request().postData() || "");
    return route.fulfill({ json: { ok: true, result: {} } });
  });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/#token=browser-fixture-token");
  await page.goto("/#/environments");
  await expect(
    page.getByRole("link", { name: "feature/project-console", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/environments-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByLabel("Filter by project").selectOption("sample-app");
  await page.getByLabel("Filter by status").selectOption("running");
  await expect(
    page.getByRole("link", { name: "fix/worker-reconnect", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("link", { name: "feature/project-console", exact: true })
    .click();
  await expect(
    page.getByRole("tab", { name: "Services", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.screenshot({
    path: "test-results/environment-services.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("tab", { name: "Operations", exact: true }).click();
  await expect(
    page.getByText("An operation has an interrupted or unknown outcome.", {
      exact: false,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/environment-operations.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.reload();
  await expect(
    page.getByRole("tab", { name: "Operations", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.goBack();
  await expect(
    page.getByRole("tab", { name: "Services", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.goBack();
  await expect(page.getByLabel("Filter by project")).toHaveValue("sample-app");
  await expect(page.getByLabel("Filter by status")).toHaveValue("running");
  await page.goto("/#/projects");
  await expect(
    page.getByText(projects[0].source_checkout, { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/projects-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  const sampleApp = page
    .locator(".project-row")
    .filter({ has: page.getByRole("heading", { name: "sample-app" }) });
  await sampleApp.getByRole("button", { name: "New worktree" }).click();
  await expect(
    page
      .getByRole("dialog")
      .getByRole("combobox", { name: "Project", exact: true }),
  ).toHaveValue("sample-app");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    sampleApp.getByRole("button", { name: "New worktree" }),
  ).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("dialog")
    .getByRole("link", { name: "Overview", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.goto("/#/environments");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/environments-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  await page
    .getByRole("link", { name: "feature/project-console", exact: true })
    .click();
  await page.getByRole("tab", { name: "Configuration", exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await expect(page.getByText("a".repeat(180), { exact: true })).toBeVisible();
  await page
    .getByRole("tab", { name: "Cleanup & removal", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Cleanup and removal" }),
  ).toBeVisible();
  expect(writes).toEqual([]);
});

test("an empty registry directs users to project registration without disabling secrets", async ({
  page,
}) => {
  await page.route("**/api/state", (route) =>
    route.fulfill({
      json: { ok: true, result: { projects: [], taskenvs: [], secrets: [] } },
    }),
  );
  await page.goto("/#token=browser-fixture-token");
  await page.goto("/#/environments");
  await expect(
    page.getByRole("button", { name: "Environment", exact: true }),
  ).toBeDisabled();
  await page.getByRole("link", { name: "Add project" }).click();
  await page.getByRole("button", { name: "Add project" }).click();
  await expect(
    page.getByRole("dialog").getByLabel("Name", { exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page
    .getByRole("navigation")
    .getByRole("link", { name: /^Secrets/ })
    .click();
  await expect(page.getByRole("button", { name: "Save" })).toBeEnabled();
});

test("theme follows the system, persists explicit choices and keeps both palettes readable", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.route("**/api/state", (route) =>
    route.fulfill({
      json: { ok: true, result: { projects, taskenvs: tasks, secrets: [] } },
    }),
  );
  await page.route("**/api/task/*", (route) =>
    route.fulfill({ json: { ok: true, result: tasks[0] } }),
  );
  await page.emulateMedia({ colorScheme: "dark" });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/#token=browser-fixture-token");
  await page.goto("/#/environments");
  const theme = page.getByRole("combobox", { name: "Color theme" });
  await expect(theme).toHaveValue("system");
  await expect(page.locator("html")).toHaveClass("dark");
  await expect(
    page.getByRole("link", { name: "feature/project-console", exact: true }),
  ).toBeVisible();
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).not.toHaveClass("dark");

  for (const mode of ["light", "dark"] as const) {
    await theme.selectOption(mode);
    await expect(page.locator("html")).toHaveClass(
      mode === "dark" ? "dark" : "",
    );
    const contrasts = await page.evaluate(() => {
      const tokens = getComputedStyle(document.documentElement);
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      const context = canvas.getContext("2d", { willReadFrequently: true })!;
      function luminance(token: string) {
        context.fillStyle = tokens.getPropertyValue(`--${token}`).trim();
        context.fillRect(0, 0, 1, 1);
        const rgb = [...context.getImageData(0, 0, 1, 1).data].slice(0, 3);
        const linear = rgb.map((value) => {
          const channel = value / 255;
          return channel <= 0.04045
            ? channel / 12.92
            : ((channel + 0.055) / 1.055) ** 2.4;
        });
        return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
      }
      const pairs: [string, string, number][] = [
        ["foreground", "background", 4.5],
        ["foreground", "popover", 4.5],
        ["muted-foreground", "background", 4.5],
        ["muted-foreground", "muted", 4.5],
        ["muted-foreground", "accent", 4.5],
        ["primary-foreground", "primary", 4.5],
        ["destructive-foreground", "destructive", 4.5],
        ["success", "success-surface", 4.5],
        ["warning", "warning-surface", 4.5],
        ["destructive", "danger-surface", 4.5],
        ["destructive", "background", 4.5],
        ["log-foreground", "log-background", 4.5],
        ["input", "background", 3],
        ["input", "popover", 3],
        ["input", "accent", 3],
        ["ring", "background", 3],
        ["ring", "accent", 3],
      ];
      return pairs.map(([foreground, background, minimum]) => {
        const first = luminance(foreground);
        const second = luminance(background);
        return {
          pair: `${foreground}/${background}`,
          ratio:
            (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05),
          minimum,
        };
      });
    });
    for (const contrast of contrasts) {
      expect(
        contrast.ratio,
        `${mode}: ${contrast.pair}`,
      ).toBeGreaterThanOrEqual(contrast.minimum);
    }
  }
  await page.screenshot({
    path: "test-results/environments-dark-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.reload();
  await expect(theme).toHaveValue("dark");
  await expect(page.locator("html")).toHaveClass("dark");
  await page.getByRole("button", { name: "Environment", exact: true }).click();
  await page
    .getByRole("button", { name: "New worktree", exact: false })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.screenshot({
    path: "test-results/form-dark-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await page.screenshot({
    path: "test-results/environments-dark-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  await page
    .getByRole("link", { name: "feature/project-console", exact: true })
    .click();
  await page.getByRole("tab", { name: "Operations", exact: true }).click();
  await expect(
    page.getByRole("tab", { name: "Operations", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.screenshot({
    path: "test-results/operations-dark-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setEmulatedVisionDeficiency", {
    type: "deuteranopia",
  });
  await page.screenshot({
    path: "test-results/operations-dark-color-vision.png",
    fullPage: true,
    animations: "disabled",
  });
  await cdp.send("Emulation.setEmulatedVisionDeficiency", { type: "none" });
  await cdp.detach();
  await page.setViewportSize({ width: 320, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await theme.selectOption("light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).not.toHaveClass("dark");
  await page.reload();
  await expect(theme).toHaveValue("light");
  await expect(page.locator("html")).not.toHaveClass("dark");
  await theme.selectOption("system");
  await expect(page.locator("html")).toHaveClass("dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).not.toHaveClass("dark");
  expect(errors).toEqual([]);
});

test("theme selection remains usable when browser storage is blocked", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new DOMException("Storage blocked", "SecurityError");
      },
    });
  });
  await page.route("**/api/state", (route) =>
    route.fulfill({
      json: { ok: true, result: { projects: [], taskenvs: [], secrets: [] } },
    }),
  );
  await page.goto("/#token=browser-fixture-token");
  await page.goto("/#/environments");
  await page
    .getByRole("combobox", { name: "Color theme" })
    .selectOption("dark");
  await expect(page.locator("html")).toHaveClass("dark");
});

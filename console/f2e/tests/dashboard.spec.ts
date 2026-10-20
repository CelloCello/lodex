import { expect, test } from "@playwright/test";
import type { Overview, Task } from "../src/api";

function checkout(id: string, overrides: Partial<Task> = {}): Task {
  return {
    id,
    project: "myapp",
    path: `/worktrees/${id}`,
    branch: `feature/${id}`,
    state: "present",
    owned: true,
    main: false,
    config_status: "valid",
    services: [],
    operations: [],
    known_resources: [],
    cleanup: { available: false },
    ...overrides,
  };
}
const taskenvs = [
  checkout("main", { main: true, owned: false, branch: "main" }),
  checkout("auth", {
    branch: "fix/auth",
    services: [
      { name: "web", state: "running" },
      { name: "worker", state: "failed" },
      { name: "api", state: "unknown" },
      { name: "legacy", state: "external" },
      { name: "queue", state: "starting" },
      { name: "mock", state: "stopped" },
    ],
  }),
  checkout("missing", {
    branch: null,
    path: "/worktrees/112670ec089142c5",
    state: "missing",
    config_status: "missing",
  }),
  checkout("failed-command", {
    operations: [
      {
        id: "verify-1",
        command: "verify",
        state: "failed",
        started_at: "2026-10-20T09:00:00Z",
      },
    ],
  }),
  ...Array.from({ length: 28 }, (_, i) =>
    checkout(`task-${String(i).padStart(2, "0")}`),
  ),
  checkout("console", {
    project: "lodex",
    services: [{ name: "console", state: "exited" }],
  }),
];
const overview: Overview = {
  projects: ["myapp", "lodex", "docs"].map((id) => ({
    id,
    source_checkout: `/projects/${id}`,
    source: `/projects/${id}/.lodex/project.toml`,
  })),
  taskenvs,
  secrets: ["myapp-api"],
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/state", (route) =>
    route.fulfill({ json: { ok: true, result: overview } }),
  );
  await page.route("**/api/task/*", (route) => {
    const task = taskenvs.find((task) =>
      route.request().url().endsWith(`/${task.id}`),
    );
    return route.fulfill({
      json: {
        ok: true,
        result: {
          ...task,
          commands: [],
          configured_services: task?.services.map((service) => service.name),
          configuration_path: `${task?.path}/.lodex/project.toml`,
          environment: { values: {}, secret_refs: {} },
        },
      },
    });
  });
});

test("dashboard uses real state groups and the persistent tree opens checkouts directly", async ({
  page,
}) => {
  const writes: string[] = [];
  await page.route("**/api/action", (route) => {
    writes.push(route.request().postData() || "");
    return route.fulfill({ json: { ok: true, result: {} } });
  });
  await page.goto("/");
  await expect(page).toHaveURL(/#\/dashboard$/);
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  const sidebar = page.locator(".sidebar");
  await expect(
    sidebar.getByRole("button", { name: "Add checkout to myapp", exact: true }),
  ).toBeVisible();
  await expect(sidebar.locator(".tree-project-toggle")).toHaveCount(3);
  const addCheckout = sidebar.getByRole("button", {
    name: "Add checkout to myapp",
    exact: true,
  });
  await addCheckout.click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await expect(addCheckout).toBeFocused();
  await expect(
    sidebar.locator(".tree-checkout").filter({ visible: true }),
  ).toHaveCount(6);
  const legend = page.getByRole("list", { name: "Service counts" });
  for (const text of [
    "Running: 1",
    "Stopped / exited: 2",
    "Failed: 1",
    "Unknown / other: 1",
    "Starting / stopping: 1",
    "Legacy external: 1",
  ])
    await expect(legend).toContainText(text);
  await expect(page.locator(".focus-row")).toHaveCount(3);
  await expect(
    page.locator(".focus-row").filter({ hasText: "failed-command" }),
  ).toContainText("Latest verify: failed");
  await sidebar
    .getByRole("link", { name: "Open fix/auth in myapp", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "fix/auth", exact: true }),
  ).toBeVisible();
  await sidebar.getByRole("button", { name: "lodex", exact: true }).click();
  await sidebar.getByRole("link", { name: "Secrets", exact: true }).click();
  await expect(
    sidebar.getByRole("link", {
      name: "Open feature/console in lodex",
      exact: true,
    }),
  ).toBeVisible();
  await sidebar.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(
    sidebar.getByRole("button", { name: "lodex", exact: true }),
  ).toHaveAttribute("aria-expanded", "true");
  await page
    .getByRole("link", {
      name: "myapp: 1 running, 1 stopped / exited, 1 failed, 1 unknown / other, 1 starting / stopping, 1 legacy external. View environments",
      exact: true,
    })
    .click();
  await expect(page.getByLabel("Filter by project")).toHaveValue("myapp");
  await expect(page.locator(".environment-table tbody tr")).toHaveCount(8);
  expect(writes).toEqual([]);
});

test("a large project remains searchable, paginated and keeps the selected checkout in the tree", async ({
  page,
}) => {
  await page.goto("/#/environments?project=myapp");
  const sidebar = page.locator(".sidebar");
  await expect(page.locator(".environment-table tbody tr")).toHaveCount(8);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/page=2/);
  await page.reload();
  await expect(page.locator(".pagination-count")).toContainText("9–16 of 32");
  await sidebar
    .getByRole("textbox", { name: "Search all projects and checkouts" })
    .fill("task-27");
  await sidebar
    .getByRole("link", { name: "Open feature/task-27 in myapp", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "feature/task-27", exact: true }),
  ).toBeVisible();
  await sidebar
    .getByRole("textbox", { name: "Search all projects and checkouts" })
    .fill("");
  await expect(
    sidebar.getByRole("textbox", { name: "Search all projects and checkouts" }),
  ).toHaveValue("");
  await expect(
    sidebar.getByRole("link", {
      name: "Open feature/task-27 in myapp",
      exact: true,
    }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    sidebar.locator(".tree-checkout").filter({ visible: true }),
  ).toHaveCount(6);
  await sidebar
    .getByRole("link", { name: "View all checkouts", exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.locator(".pagination-count")).toContainText("9–16 of 32");
  await page.getByLabel("Search environments").fill("task-27");
  await expect(page).not.toHaveURL(/page=2/);
  await expect(page.locator(".environment-table tbody tr")).toHaveCount(1);
  await page.getByLabel("Search environments").fill("");
  await expect(page.getByLabel("Search environments")).toHaveValue("");
  await expect(page).not.toHaveURL(/q=task-27/);
  await expect(page.locator(".pagination-count")).toContainText("1–8 of 32");
  await page.getByLabel("Filter by status").selectOption("attention");
  await expect(page.locator(".environment-table tbody tr")).toHaveCount(3);
});

for (const theme of ["light", "dark"] as const)
  test(`dashboard and mobile tree stay usable in ${theme} mode`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/");
    await page.getByLabel("Color theme").selectOption(theme);
    await expect(page.locator(".overview-metrics")).toBeVisible();
    await page.screenshot({
      path: `test-results/overview-${theme}-desktop.png`,
      fullPage: true,
      animations: "disabled",
    });
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
    const navigation = page.getByRole("dialog");
    await page.keyboard.press("Escape");
    await expect(navigation).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Open navigation", exact: true }),
    ).toBeFocused();
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
    await navigation
      .getByRole("button", { name: "Close", exact: true })
      .click();
    await expect(navigation).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Open navigation", exact: true }),
    ).toBeFocused();
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
    await navigation
      .getByRole("button", { name: "Add checkout to myapp", exact: true })
      .click();
    const add = page.getByRole("dialog", { name: "Add checkout", exact: true });
    await expect(add).toBeVisible();
    await add
      .getByRole("button", { name: "Connect existing checkout", exact: false })
      .click();
    await expect(
      page
        .getByRole("dialog")
        .getByRole("combobox", { name: "Project", exact: true }),
    ).toHaveValue("myapp");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Open navigation", exact: true }),
    ).toBeFocused();
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
    await navigation
      .getByLabel("Search all projects and checkouts")
      .fill("task-27");
    await navigation
      .getByRole("link", { name: "Open feature/task-27 in myapp", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "feature/task-27", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
    await navigation.getByLabel("Search all projects and checkouts").fill("");
    await navigation
      .getByRole("link", { name: "Secrets", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Replace value for myapp-api", exact: true })
      .click();
    await expect(page.getByLabel("Stored name", { exact: true })).toHaveValue(
      "myapp-api",
    );
    await expect(page.getByLabel("Value", { exact: true })).toHaveValue("");
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
    await navigation
      .getByRole("link", { name: "Overview", exact: true })
      .click();
    await expect(navigation).toHaveCount(0);
    await page.screenshot({
      path: `test-results/overview-${theme}-mobile.png`,
      fullPage: true,
      animations: "disabled",
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
  });

import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import {
  mkdtempSync,
  realpathSync,
  renameSync,
  rmSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";

test("legacy external records show guidance without process controls", async ({
  page,
}) => {
  const task = {
    id: "legacy-task",
    project: "fixture",
    path: "/fixture",
    branch: "legacy",
    state: "present",
    owned: false,
    main: true,
    config_status: "valid",
    configuration_path: "/fixture/.lodex/project.toml",
    configured_services: ["old-api", "mock-api"],
    services: [
      {
        name: "old-api",
        state: "external",
        url: "https://example.invalid",
        warning:
          "Legacy external service record is read-only. Use a different service name for a managed process.",
      },
    ],
    operations: [],
    known_resources: [],
    cleanup: { available: false },
  };
  await page.route("**/api/state", (route) =>
    route.fulfill({
      json: {
        ok: true,
        result: { projects: [], taskenvs: [task], secrets: [] },
      },
    }),
  );
  await page.route("**/api/task/legacy-task", (route) =>
    route.fulfill({
      json: { ok: true, result: task },
    }),
  );
  await page.goto("/#token=browser-fixture-token");
  await page.goto("/#/environments");
  await page.getByRole("link", { name: "legacy", exact: true }).click();
  const legacy = page.locator(".service-row").filter({ hasText: "old-api" });
  await expect(legacy).toContainText("read-only");
  await expect(legacy.getByRole("link")).toHaveAttribute(
    "href",
    "https://example.invalid",
  );
  await expect(legacy.getByRole("button")).toHaveCount(0);
  const mock = page.locator(".service-row").filter({ hasText: "mock-api" });
  await expect(
    mock.getByRole("button", { name: "Start", exact: true }),
  ).toBeEnabled();
});

test("register, create and remove a worktree through the console", async ({
  page,
}) => {
  const repo = realpathSync(
    mkdtempSync(path.join(tmpdir(), "lodex-ui-project-")),
  );
  try {
    for (const args of [
      ["init", "-q"],
      ["config", "user.name", "Fixture"],
      ["config", "user.email", "fixture@example.invalid"],
    ])
      execFileSync("git", args, { cwd: repo });
    writeFileSync(path.join(repo, "README.md"), "Console fixture\n");
    execFileSync("git", ["add", "README.md"], { cwd: repo });
    execFileSync("git", ["commit", "-qm", "fixture"], { cwd: repo });
    await page.goto("/#token=browser-fixture-token");
    await page.goto("/#/environments");
    await page.goto("/#/projects");
    await page
      .getByRole("button", { name: "Register project", exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Project name").fill("ui-fixture");
    await dialog.getByLabel("Absolute checkout path").fill(repo);
    await dialog
      .getByRole("button", { name: "Register project", exact: true })
      .click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("status")).toContainText(
      "Configuration initialized",
    );
    await expect(page.getByRole("status")).toContainText("before running them");
    const project = page.locator(".project-row").filter({
      has: page.getByRole("heading", { name: "ui-fixture", exact: true }),
    });
    await expect(project).toContainText(repo);
    await project
      .getByRole("button", { name: "Connect existing checkout" })
      .click();
    await dialog.getByLabel("Absolute checkout path").fill(repo);
    await dialog
      .getByRole("button", { name: "Connect existing checkout", exact: true })
      .click();
    await expect(page.locator(".detail-meta")).toContainText("Main checkout");
    await page
      .getByRole("tab", { name: "Cleanup & removal", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Preview removal" }),
    ).toBeDisabled();
    await page
      .getByRole("button", { name: "Forget registration", exact: true })
      .click();
    await dialog
      .getByRole("button", { name: "Forget registration", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Environments", exact: true }),
    ).toBeVisible();
    await page.goto("/#/projects");
    await project.getByRole("button", { name: "New worktree" }).click();
    await dialog.getByLabel("New branch").fill("feature/from-console");
    await dialog
      .getByRole("button", { name: "New worktree", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "feature/from-console", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "No services configured" }),
    ).toBeVisible();
    await page
      .getByRole("tab", { name: "Cleanup & removal", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Run cleanup", exact: true }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "Preview removal" }).click();
    await expect(dialog).toContainText("Recorded services · 0");
    await expect(dialog.getByLabel(/Force Git removal/)).not.toBeChecked();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Remove worktree", exact: true })
      .click();
    // Git protects the generated, untracked project.toml until force is explicit.
    await expect(dialog.getByRole("alert")).toBeVisible();
    await dialog.getByLabel(/Force Git removal/).check();
    await dialog
      .getByRole("button", { name: "Remove worktree", exact: true })
      .click();
    await expect(dialog).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Environments", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "feature/from-console", exact: true }),
    ).toHaveCount(0);
    // Removing files preserves the evidence record; forgetting is a separate action.
    await expect(
      page
        .getByRole("status")
        .filter({ hasText: "registry record is retained" }),
    ).toBeVisible();
    const removed = page.getByRole("row").filter({
      has: page.getByRole("cell", { name: /ui-fixture Managed worktree/ }),
    });
    await expect(removed).toContainText("missing");
    await removed.getByRole("link").click();
    await page
      .getByRole("tab", { name: "Cleanup & removal", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Forget registration", exact: true })
      .click();
    await dialog
      .getByRole("button", { name: "Forget registration", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Environments", exact: true }),
    ).toBeVisible();
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test("CLI-created environment can be managed from browser without replaying writes", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      message.text().includes("Content Security Policy")
    )
      errors.push(message.text());
  });
  await page.goto("/#token=browser-fixture-token");
  await page.goto("/#/environments");
  await page
    .getByRole("link", { name: "feature/console", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "feature/console" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect(page.locator(".service-row .state")).toHaveText("stopped");
  const state = await page.evaluate(async () =>
    (
      await fetch("/api/state", {
        headers: { Authorization: "Bearer browser-fixture-token" },
      })
    ).json(),
  );
  const task = state.result.taskenvs[0];
  // A fresh CLI caller observes the stop from the browser against the same registry.
  const manager = path.resolve(task.path, "../../..");
  const cli = JSON.parse(
    execFileSync(
      "../../.venv/bin/python",
      [
        "-m",
        "lodex_cli.main",
        "service",
        "list",
        "--target",
        task.id,
        "--json",
      ],
      { env: { ...process.env, LODEX_HOME: manager }, encoding: "utf8" },
    ),
  );
  expect(cli.result[0].state).toBe("stopped");
  await page.getByRole("tab", { name: "Operations", exact: true }).click();
  await page.getByRole("button", { name: "prepare", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "succeeded", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "slow", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Operation in progress" }),
  ).toBeVisible();
  await page
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: "prepare", exact: true }) })
    .getByRole("button", { name: "Logs", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "prepare logs" }),
  ).toContainText("prepared fixture");
  await page.reload();
  await expect(
    page.getByRole("cell", { name: "slow", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("row")
      .filter({ has: page.getByRole("cell", { name: "slow", exact: true }) })
      .getByText("succeeded"),
  ).toBeVisible({ timeout: 10000 });
  expect(
    await page.getByRole("cell", { name: "slow", exact: true }).count(),
  ).toBe(1);
  await page.getByRole("link", { name: /^Secrets/ }).click();
  await page.getByLabel("Stored name").fill("browser-secret");
  await page
    .getByLabel("Value", { exact: true })
    .fill("synthetic-browser-only");
  await page.getByRole("button", { name: "Save secret" }).click();
  await expect(
    page.getByRole("strong").filter({ hasText: /^browser-secret$/ }),
  ).toBeVisible();
  await expect(page.getByLabel("Value", { exact: true })).toBeEmpty();
  expect(await page.locator("body").textContent()).not.toContain(
    "synthetic-browser-only",
  );
  await page
    .getByRole("button", { name: "Remove browser-secret", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Remove browser-secret", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("strong").filter({ hasText: /^browser-secret$/ }),
  ).toBeVisible();
  await page.goto("/#/environments");
  await page
    .getByRole("link", { name: "feature/console", exact: true })
    .click();
  await page
    .getByRole("tab", { name: "Cleanup & removal", exact: true })
    .click();
  await page.getByRole("button", { name: "Preview removal" }).click();
  await expect(page.getByRole("dialog")).toContainText("Git changes");
  await expect(page.getByRole("dialog")).toContainText(task.path);
  await expect(page.getByLabel(/Force Git removal/)).not.toBeChecked();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("tab", { name: "Services", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/console-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: "test-results/console-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await expect(page.locator(".service-row .state")).toHaveText("running");
  unlinkSync(path.join(task.path, ".lodex/project.toml"));
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByText(/Cannot read valid TOML/).first()).toBeVisible();
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect(page.locator(".service-row .state")).toHaveText("stopped");
  renameSync(task.path, `${task.path}-missing`);
  try {
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(page.locator(".detail-meta .state")).toHaveText("missing");
    await page
      .getByRole("tab", { name: "Cleanup & removal", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Preview removal" }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "Forget registration" }).click();
    await expect(page.getByRole("dialog")).toContainText(
      "does not stop services",
    );
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Forget registration", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Environments", exact: true }),
    ).toBeVisible();
    await expect(
      page.locator(`a[href="#/environments/${task.id}/services"]`),
    ).toHaveCount(0);
  } finally {
    renameSync(`${task.path}-missing`, task.path);
  }
});

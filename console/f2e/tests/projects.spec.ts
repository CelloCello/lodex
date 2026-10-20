import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { Overview } from "../src/api";

for (const theme of ["light", "dark"] as const) {
  test(`matching display names stay distinguishable across navigation and overview in ${theme} mode`, async ({
    page,
  }) => {
    const overview: Overview = {
      projects: ["one", "two", "unique", "legacy"].map((id) => ({
        id,
        ...(id === "legacy"
          ? {}
          : { display_name: id === "unique" ? "Unique" : "Shared" }),
        source_checkout: `/projects/${id}`,
        source: `/projects/${id}/.lodex/project.toml`,
      })),
      taskenvs: ["one", "two", "unique", "legacy"].map((id) => ({
        id: `environment-${id}`,
        project: id,
        path: `/projects/${id}`,
        branch: "main",
        state: "present",
        owned: false,
        main: true,
        config_status: "valid",
        services: [{ name: "web", state: "running" }],
        operations: [],
        known_resources: [],
        cleanup: { available: false },
      })),
      secrets: [],
    };
    await page.route("**/api/state", (route) =>
      route.fulfill({ json: { ok: true, result: overview } }),
    );
    await page.goto("/#/environments?project=one");
    await page.getByLabel("Color theme").selectOption(theme);
    const sidebar = page.locator(".sidebar");
    await expect(
      sidebar.getByRole("link", {
        name: "Open project Shared (one)",
        exact: true,
      }),
    ).toContainText("one");
    await expect(
      sidebar.getByRole("link", {
        name: "Open project Shared (two)",
        exact: true,
      }),
    ).toContainText("two");
    await sidebar
      .getByRole("link", { name: "Open project Shared (two)", exact: true })
      .click();
    await expect(page).toHaveURL(/project=two$/);
    await expect(page.locator(".project-summary")).toContainText(
      "Project ID two",
    );
    await expect(page.getByLabel("Filter by project")).toHaveValue("two");
    await sidebar
      .getByLabel("Search all projects and environments")
      .fill("Shared");
    await expect(sidebar.locator(".tree-project-link")).toHaveCount(2);
    await sidebar.getByLabel("Search all projects and environments").fill("");

    await page.goto("/#/dashboard?focus=all");
    const rows = [
      {
        row: ".distribution-row",
        label: ".distribution-project",
        environment: false,
      },
      { row: ".focus-row", label: "small", environment: true },
      { row: ".project-overview-row", label: "strong", environment: false },
    ];
    for (const viewport of [
      { width: 1440, height: 1000 },
      { width: 320, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      for (const { row, label, environment } of rows) {
        for (const [id, name] of [
          ["one", "Shared (one)"],
          ["two", "Shared (two)"],
          ["unique", "Unique"],
          ["legacy", "legacy"],
        ]) {
          const href = environment
            ? `#/environments/environment-${id}/services`
            : `#/environments?project=${id}`;
          const link = page.locator(`${row}[href="${href}"]`);
          await expect(link.locator(label)).toHaveText(name);
          await expect(link.locator(label)).toBeVisible();
          await expect(link).toHaveAccessibleName(
            new RegExp(name.replace(/[()]/g, "\\$&")),
          );
        }
      }
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `test-results/project-matching-names-${theme}-${viewport.width}.png`,
        fullPage: true,
        animations: "disabled",
      });
    }
    await page
      .locator('.project-overview-row[href="#/environments?project=two"]')
      .click();
    await expect(page.getByLabel("Filter by project")).toHaveValue("two");
    await page.goBack();
    await page
      .locator('.distribution-row[href="#/environments?project=one"]')
      .click();
    await expect(page.getByLabel("Filter by project")).toHaveValue("one");
    await page.goBack();

    overview.projects.find((project) => project.id === "two")!.display_name =
      "Renamed";
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    for (const { row, label, environment } of rows) {
      for (const [id, name] of [
        ["one", "Shared"],
        ["two", "Renamed"],
      ]) {
        const href = environment
          ? `#/environments/environment-${id}/services`
          : `#/environments?project=${id}`;
        await expect(
          page.locator(`${row}[href="${href}"]`).locator(label),
        ).toHaveText(name);
      }
    }
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`project names, duplicate registration and mobile editing work in ${theme} mode`, async ({
    page,
  }) => {
    const repo = realpathSync(
      mkdtempSync(path.join(tmpdir(), "lodex-project-ui-")),
    );
    execFileSync("git", ["init", "-q"], { cwd: repo });
    const id = `project-ui-${theme}`;
    const original = `Project ${theme}`;
    const updated = `中文專案 ${theme} with a longer display name`;
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (
        /Content Security Policy|Refused to|violates.*directive/i.test(
          message.text(),
        )
      )
        errors.push(message.text());
    });
    const overview = () =>
      page.evaluate(
        async (): Promise<Overview> =>
          (
            await (
              await fetch("/api/state", {
                headers: { Authorization: "Bearer browser-fixture-token" },
              })
            ).json()
          ).result,
      );
    try {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto("/#token=browser-fixture-token");
      await page.getByLabel("Color theme").selectOption(theme);
      const sidebar = page.locator(".sidebar");
      const add = sidebar.getByRole("button", {
        name: "Add a project",
        exact: true,
      });
      await expect(add).toHaveCount(1);
      await expect(sidebar.locator(".tree-heading-row")).toContainText(
        "Projects",
      );
      await expect(
        sidebar
          .locator(".tree-footer")
          .getByRole("button", { name: "Add a project" }),
      ).toHaveCount(0);
      await add.click();
      const dialog = page.getByRole("dialog", {
        name: "Add project",
        exact: true,
      });
      await dialog.getByLabel("Path", { exact: true }).fill(repo);
      await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue(
        path.basename(repo),
      );
      await dialog.getByLabel("Name", { exact: true }).fill(original);
      await dialog.getByText("Options", { exact: true }).click();
      await dialog.getByLabel("Project ID", { exact: true }).fill(id);
      await dialog.getByText("Options", { exact: true }).click();
      await page.screenshot({
        path: `test-results/project-add-${theme}-desktop.png`,
        fullPage: true,
        animations: "disabled",
      });
      await dialog.getByRole("button", { name: "Add", exact: true }).click();
      await expect(dialog).toHaveCount(0);
      await sidebar
        .getByRole("link", {
          name: `Open project ${original} (${id})`,
          exact: true,
        })
        .click();
      await expect(
        page.getByRole("heading", { name: original, exact: true }),
      ).toBeVisible();
      await expect(page.locator(".project-summary")).toContainText(
        `Project ID ${id}`,
      );

      await add.click();
      await dialog.getByLabel("Path", { exact: true }).fill(repo);
      await dialog.getByRole("button", { name: "Add", exact: true }).click();
      await expect(dialog.getByRole("alert")).toContainText(`ID: ${id}`);
      await dialog
        .getByRole("button", { name: `Open ${original}`, exact: true })
        .click();
      await expect(dialog).toHaveCount(0);
      await expect(page).toHaveURL(new RegExp(`project=${id}$`));

      await add.click();
      await dialog.getByLabel("Path", { exact: true }).fill(repo);
      await dialog.getByText("Options", { exact: true }).click();
      await dialog.getByLabel("Project ID", { exact: true }).fill(id);
      await dialog.getByRole("button", { name: "Add", exact: true }).click();
      await expect(dialog).toContainText(
        "This repository is already registered.",
      );
      await dialog
        .getByRole("button", { name: `Open ${original}`, exact: true })
        .click();
      expect(
        (await overview()).projects.filter((project) => project.id === id),
      ).toHaveLength(1);

      await sidebar
        .getByRole("button", {
          name: `Add environment to ${original} (${id})`,
          exact: true,
        })
        .click();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Use existing", exact: false })
        .click();
      await page
        .getByRole("dialog")
        .getByLabel("Path", { exact: true })
        .fill(repo);
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Register", exact: true })
        .click();
      await expect(page.getByRole("dialog")).toHaveCount(0);
      const before = (await overview()).taskenvs.find(
        (task) => task.project === id,
      )!;
      expect(before.path).toBe(repo);
      await sidebar
        .getByRole("link", {
          name: `Open project ${original} (${id})`,
          exact: true,
        })
        .click();
      const menu = sidebar.getByRole("button", {
        name: `Project menu for ${original} (${id})`,
        exact: true,
      });
      await menu.click();
      await page.screenshot({
        path: `test-results/project-menu-${theme}-desktop.png`,
        fullPage: true,
        animations: "disabled",
      });
      await page.getByRole("menuitem", { name: "Edit", exact: true }).click();
      const edit = page.getByRole("dialog", { name: "Edit name", exact: true });
      await expect(edit.getByLabel("Name", { exact: true })).toBeFocused();
      await edit.getByLabel("Name", { exact: true }).fill(updated);
      await edit.getByRole("button", { name: "Save", exact: true }).click();
      await expect(edit).toHaveCount(0);
      await expect(page).toHaveTitle(`${updated} · Lodex`);
      await expect(page.locator(".breadcrumbs")).toHaveText(updated);
      await expect(menu).toHaveCount(0);
      const renamedMenu = sidebar.getByRole("button", {
        name: `Project menu for ${updated} (${id})`,
        exact: true,
      });
      await expect(renamedMenu).toBeFocused();
      expect(
        (await overview()).taskenvs.find((task) => task.id === before.id),
      ).toMatchObject({ id: before.id, path: before.path, project: id });
      await page.reload();
      await expect(
        page.getByRole("heading", { name: updated, exact: true }),
      ).toBeVisible();
      await sidebar
        .getByLabel("Search all projects and environments")
        .fill(updated);
      await expect(
        sidebar.getByRole("link", {
          name: `Open project ${updated} (${id})`,
          exact: true,
        }),
      ).toBeVisible();
      await sidebar.getByLabel("Search all projects and environments").fill(id);
      await expect(
        sidebar.getByRole("link", {
          name: `Open project ${updated} (${id})`,
          exact: true,
        }),
      ).toBeVisible();
      await sidebar.getByLabel("Search all projects and environments").fill("");
      await page.screenshot({
        path: `test-results/project-name-${theme}-desktop.png`,
        fullPage: true,
        animations: "disabled",
      });
      await page.setViewportSize({ width: 320, height: 844 });
      const openNavigation = page.getByRole("button", {
        name: "Open navigation",
        exact: true,
      });
      await openNavigation.click();
      const navigation = page.getByRole("dialog");
      await navigation
        .getByRole("button", {
          name: `Project menu for ${updated} (${id})`,
          exact: true,
        })
        .click();
      await page.getByRole("menuitem", { name: "Edit", exact: true }).click();
      await expect(edit.getByLabel("Name", { exact: true })).toBeFocused();
      await expect(edit).toContainText(`Project ID ${id}`);
      await page.screenshot({
        path: `test-results/project-edit-${theme}-mobile.png`,
        fullPage: true,
        animations: "disabled",
      });
      await edit.getByLabel("Name", { exact: true }).fill(`${updated} mobile`);
      await edit.getByRole("button", { name: "Save", exact: true }).click();
      await expect(edit).toHaveCount(0);
      await expect(openNavigation).toBeFocused();
      await expect(
        page.getByRole("heading", { name: `${updated} mobile`, exact: true }),
      ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await openNavigation.click();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "Add a project", exact: true })
        .click();
      await expect(dialog.getByLabel("Path", { exact: true })).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(openNavigation).toBeFocused();
      expect(errors).toEqual([]);
    } finally {
      rmSync(repo, { recursive: true, force: true });
    }
  });
}

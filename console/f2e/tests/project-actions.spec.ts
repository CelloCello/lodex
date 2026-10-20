import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { Action, Overview } from "../src/api";

for (const theme of ["light", "dark"] as const) {
  test(`project edit, pin and empty-only deletion work in ${theme} mode`, async ({
    page,
  }) => {
    const repo = realpathSync(
      mkdtempSync(path.join(tmpdir(), "lodex-project-actions-")),
    );
    execFileSync("git", ["init", "-q"], { cwd: repo });
    const id = `z-actions-${theme}`;
    const label = `Actions project ${theme}`;
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
    const action = async (payload: Action) => {
      const response = await page.request.post("/api/action", {
        headers: {
          Authorization: "Bearer browser-fixture-token",
          Origin: new URL(page.url()).origin,
        },
        data: payload,
      });
      const result = await response.json();
      expect(result.ok).toBe(true);
      return result.result;
    };
    const overview = async (): Promise<Overview> =>
      (
        await (
          await page.request.get("/api/state", {
            headers: { Authorization: "Bearer browser-fixture-token" },
          })
        ).json()
      ).result;
    try {
      await page.goto("/#token=browser-fixture-token");
      await action({
        action: "project.add",
        name: id,
        path: repo,
        display_name: label,
      });
      await page.goto(`/#/environments?project=${id}`);
      await page.getByRole("button", { name: "Refresh", exact: true }).click();
      await page.getByLabel("Color theme").selectOption(theme);
      await page.setViewportSize({ width: 1440, height: 1000 });
      await expect(
        page.getByRole("heading", { name: label, exact: true }),
      ).toBeVisible();
      const header = page.locator(".page-heading");
      await expect(
        header.getByRole("button", { name: "Environment", exact: true }),
      ).toHaveCount(0);
      const editButton = header.getByRole("button", {
        name: "Edit",
        exact: true,
      });
      await expect(editButton).toBeVisible();
      await expect(
        page
          .locator(".environment-toolbar")
          .getByRole("button", { name: "Environment", exact: true }),
      ).toBeVisible();
      await editButton.click();
      const edit = page.getByRole("dialog", { name: "Edit name", exact: true });
      await expect(edit.getByLabel("Name", { exact: true })).toHaveValue(label);
      await edit.getByRole("button", { name: "Cancel", exact: true }).click();
      await expect(editButton).toBeFocused();
      const sidebar = page.locator(".sidebar");
      const menu = sidebar.getByRole("button", {
        name: `Project menu for ${label} (${id})`,
        exact: true,
      });
      const before = await sidebar
        .locator(".tree-project-link")
        .evaluateAll((links) => links.map((link) => link.getAttribute("href")));
      expect(before[0]).not.toBe(`#/environments?project=${id}`);
      await menu.click();
      await expect(
        page
          .getByRole("menuitem", { name: "Edit", exact: true })
          .locator("svg"),
      ).toHaveCount(1);
      await page.getByRole("menuitem", { name: "Pin", exact: true }).click();
      await expect(
        sidebar.locator(".tree-project-link").first(),
      ).toHaveAttribute("href", `#/environments?project=${id}`);
      await expect(menu).toBeFocused();
      await page.reload();
      await expect(
        sidebar.locator(".tree-project-link").first(),
      ).toHaveAttribute("href", `#/environments?project=${id}`);
      expect(
        (await overview()).projects.find((project) => project.id === id)
          ?.pinned,
      ).toBe(true);
      await menu.click();
      await page.screenshot({
        path: `test-results/project-actions-${theme}-desktop.png`,
        fullPage: true,
        animations: "disabled",
      });
      await page.getByRole("menuitem", { name: "Unpin", exact: true }).click();
      await expect
        .poll(async () =>
          sidebar
            .locator(".tree-project-link")
            .evaluateAll((links) =>
              links.map((link) => link.getAttribute("href")),
            ),
        )
        .toEqual(before);
      await expect
        .poll(
          async () =>
            (await overview()).projects.find((project) => project.id === id)
              ?.pinned,
        )
        .toBe(false);
      await expect(menu).toBeFocused();

      const environment = await action({
        action: "worktree.attach",
        project: id,
        path: repo,
      });
      await page.getByRole("button", { name: "Refresh", exact: true }).click();
      await menu.click();
      await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
      await expect(page.getByRole("alert")).toContainText(
        "still has 1 environment",
      );
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expect(menu).toBeFocused();
      expect(
        (await overview()).projects.some((project) => project.id === id),
      ).toBe(true);
      await action({
        action: "worktree.forget",
        target: environment.id,
        yes: true,
      });
      await page.getByRole("button", { name: "Refresh", exact: true }).click();
      await page.setViewportSize({ width: 320, height: 844 });
      await expect(editButton).toBeVisible();
      await editButton.click();
      await expect(edit.getByLabel("Name", { exact: true })).toBeFocused();
      await edit.getByRole("button", { name: "Cancel", exact: true }).click();
      await expect(editButton).toBeFocused();
      const openNavigation = page.getByRole("button", {
        name: "Open navigation",
        exact: true,
      });
      const openDelete = async () => {
        await openNavigation.click();
        await page
          .getByRole("dialog")
          .getByRole("button", {
            name: `Project menu for ${label} (${id})`,
            exact: true,
          })
          .click();
        await page
          .getByRole("menuitem", { name: "Delete", exact: true })
          .click();
      };
      await openDelete();
      const deletion = page.getByRole("dialog", {
        name: "Delete project",
        exact: true,
      });
      await expect(deletion).toContainText(
        "Deletes only the project registration",
      );
      await expect(deletion).toContainText(repo);
      await page.screenshot({
        path: `test-results/project-delete-${theme}-mobile.png`,
        fullPage: true,
        animations: "disabled",
      });
      await deletion
        .getByRole("button", { name: "Cancel", exact: true })
        .click();
      await expect(openNavigation).toBeFocused();
      expect(
        (await overview()).projects.some((project) => project.id === id),
      ).toBe(true);
      await openDelete();
      await deletion
        .getByRole("button", { name: "Delete project", exact: true })
        .click();
      await expect(page).toHaveURL(/#\/dashboard$/);
      await expect(deletion).toHaveCount(0);
      expect(
        (await overview()).projects.some((project) => project.id === id),
      ).toBe(false);
      expect(existsSync(path.join(repo, ".git"))).toBe(true);
      expect(existsSync(path.join(repo, ".lodex/project.toml"))).toBe(true);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(errors).toEqual([]);
    } finally {
      rmSync(repo, { recursive: true, force: true });
    }
  });
}

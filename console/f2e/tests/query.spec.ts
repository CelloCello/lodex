import { expect, test, type Page, type Route } from "@playwright/test";
import type { Action, Detail } from "../src/api";

function task(id: string): Detail {
  return {
    id,
    project: "query-fixture",
    branch: id,
    path: `/fixture/${id}`,
    state: "present",
    owned: true,
    main: false,
    config_status: "valid",
    configuration_path: `/fixture/${id}/.lodex/project.toml`,
    configured_services: ["api"],
    services: [{ name: "api", state: "running" }],
    operations: [],
    known_resources: [],
    cleanup: { available: false },
  };
}

async function installClock(page: Page) {
  const time = new Date("2026-10-14T00:00:00Z");
  await page.clock.install({ time });
}

test("polling keeps Logs and removal previews as explicitly requested snapshots", async ({
  page,
}) => {
  await installClock(page);
  const environment = task("snapshots");
  const actions: Action[] = [];
  let reads = 0;
  await page.route("**/api/state", (route) => {
    reads++;
    return route.fulfill({
      json: {
        ok: true,
        result: { projects: [], taskenvs: [environment], secrets: [] },
      },
    });
  });
  await page.route("**/api/task/*", (route) =>
    route.fulfill({ json: { ok: true, result: environment } }),
  );
  await page.route("**/api/action", (route) => {
    actions.push(route.request().postDataJSON());
    return route.fulfill({
      json: {
        ok: true,
        result: { tail: `snapshot ${actions.length}`, path: environment.path },
      },
    });
  });
  await page.goto("/#/environments/snapshots/services");
  await expect(
    page.getByRole("heading", { name: "snapshots", exact: true }),
  ).toBeVisible();
  expect(actions).toEqual([]);
  await page.getByRole("button", { name: "Logs", exact: true }).click();
  await expect(page.getByRole("region", { name: "api logs" })).toContainText(
    "snapshot 1",
  );
  const before = reads;
  await page.clock.runFor(6500);
  await expect.poll(() => reads).toBeGreaterThan(before);
  await expect(page.getByRole("region", { name: "api logs" })).toContainText(
    "snapshot 1",
  );
  expect(actions.map((a) => a.action)).toEqual(["service.logs"]);
  await page.getByRole("button", { name: "Logs", exact: true }).click();
  await expect(page.getByRole("region", { name: "api logs" })).toContainText(
    "snapshot 2",
  );
  await page
    .getByRole("tab", { name: "Cleanup & removal", exact: true })
    .click();
  expect(actions).toHaveLength(2);
  await page.getByRole("button", { name: "Preview removal" }).click();
  await expect(page.getByRole("dialog")).toContainText(environment.path);
  await page.clock.runFor(6500);
  expect(actions.map((a) => a.action)).toEqual([
    "service.logs",
    "service.logs",
    "worktree.remove",
  ]);
  expect(actions[2].yes).toBeUndefined();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "snapshots", exact: true }),
  ).toBeVisible();
  expect(actions).toHaveLength(3);
});

test("failed writes refresh observed state without retrying or queuing offline", async ({
  page,
}) => {
  await installClock(page);
  const environment = task("failed-write");
  let reads = 0;
  let writes = 0;
  await page.route("**/api/state", (route) => {
    reads++;
    return route.fulfill({
      json: {
        ok: true,
        result: { projects: [], taskenvs: [environment], secrets: [] },
      },
    });
  });
  await page.route("**/api/task/*", (route) =>
    route.fulfill({ json: { ok: true, result: environment } }),
  );
  await page.route("**/api/action", (route) => {
    writes++;
    // A failed response does not imply the operation had no side effects.
    environment.services[0].state = "unknown";
    return route.fulfill({
      status: 500,
      json: { ok: false, error: { message: "Outcome unknown" } },
    });
  });
  await page.goto("/#/environments/failed-write/services");
  await expect(page.locator(".service-row .state")).toHaveText("running");
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  const before = reads;
  // Two synchronous submissions must still send just one request.
  await page
    .getByRole("button", { name: "Stop", exact: true })
    .evaluate((button) => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  await expect(page.getByRole("alert")).toContainText("Outcome unknown");
  await expect(page.locator(".service-row .state")).toHaveText("unknown");
  expect(reads).toBeGreaterThan(before);
  expect(writes).toBe(1);
  const after = reads;
  await page.clock.runFor(10000);
  await expect.poll(() => reads).toBeGreaterThan(after);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect.poll(() => reads).toBeGreaterThan(after + 1);
  expect(writes).toBe(1);
});

test("failed queries wait for polling or explicit refresh and errors can be dismissed", async ({
  page,
}) => {
  await installClock(page);
  let reads = 0;
  let failing = true;
  await page.route("**/api/state", (route) => {
    reads++;
    return route.fulfill({
      json: failing
        ? { ok: false, error: { message: "Read unavailable" } }
        : { ok: true, result: { projects: [], taskenvs: [], secrets: [] } },
    });
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Read unavailable");
  await page.clock.runFor(1500);
  expect(reads).toBe(1);
  await page.getByRole("button", { name: "Dismiss error" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.clock.runFor(2000);
  await expect(page.getByRole("alert")).toContainText("Read unavailable");
  expect(reads).toBe(2);
  failing = false;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect.poll(() => reads).toBe(3);
  await expect(
    page.getByRole("heading", { name: "No projects yet" }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("switching targets cancels an old detail request and keeps the new target isolated", async ({
  page,
}) => {
  const environments = [task("target-a"), task("target-b")];
  let pending: Route | undefined;
  await page.route("**/api/state", (route) =>
    route.fulfill({
      json: {
        ok: true,
        result: { projects: [], taskenvs: environments, secrets: [] },
      },
    }),
  );
  await page.route("**/api/task/*", async (route) => {
    const id = route.request().url().split("/").at(-1);
    if (id === "target-a") {
      pending = route;
      return;
    }
    await route.fulfill({ json: { ok: true, result: environments[1] } });
  });
  await page.goto("/#/environments/target-a/services");
  await expect.poll(() => !!pending).toBe(true);
  await expect(page.locator(".sync-label")).toHaveText("Connecting…");
  const canceled = page.waitForEvent("requestfailed", (request) =>
    request.url().endsWith("/api/task/target-a"),
  );
  await page
    .locator(".sidebar")
    .getByRole("link", {
      name: "Open target-b in query-fixture",
      exact: true,
    })
    .click();
  await canceled;
  await expect(
    page.getByRole("heading", { name: "target-b", exact: true }),
  ).toBeVisible();
  await pending!.fulfill({ json: { ok: true, result: environments[0] } });
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "target-b", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "target-a", exact: true }),
  ).toHaveCount(0);
});

test("forgetting an environment does not report its removed detail as a query failure", async ({
  page,
}) => {
  const environment = task("forget-query");
  let registered = true;
  let removedDetailReads = 0;
  await page.route("**/api/state", async (route) => {
    if (!registered) await new Promise((resolve) => setTimeout(resolve, 150));
    await route.fulfill({
      json: {
        ok: true,
        result: {
          projects: [],
          taskenvs: registered ? [environment] : [],
          secrets: [],
        },
      },
    });
  });
  await page.route("**/api/task/*", (route) => {
    if (!registered) removedDetailReads++;
    return route.fulfill({
      json: registered
        ? { ok: true, result: environment }
        : { ok: false, error: { message: "Unknown taskenv: forget-query" } },
    });
  });
  await page.route("**/api/action", (route) => {
    const action = route.request().postDataJSON() as Action;
    if (action.yes) registered = false;
    return route.fulfill({
      json: { ok: true, result: { path: environment.path } },
    });
  });
  await page.goto("/#/environments/forget-query/cleanup");
  await page.getByRole("button", { name: "Unregister", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Unregister", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Environments", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("status")).toContainText("completed");
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(removedDetailReads).toBe(0);
});

test("detail query errors follow the selected target and clear after recovery", async ({
  page,
}) => {
  const environments = [task("error-target"), task("healthy-target")];
  let failing = true;
  await page.route("**/api/state", (route) =>
    route.fulfill({
      json: {
        ok: true,
        result: { projects: [], taskenvs: environments, secrets: [] },
      },
    }),
  );
  await page.route("**/api/task/*", (route) => {
    const id = route.request().url().split("/").at(-1);
    return route.fulfill({
      json:
        id === "error-target" && failing
          ? { ok: false, error: { message: "Detail unavailable" } }
          : {
              ok: true,
              result: environments.find((environment) => environment.id === id),
            },
    });
  });
  await page.goto("/#/environments/error-target/services");
  await expect(page.getByRole("alert")).toContainText("Detail unavailable");
  await page
    .locator(".sidebar")
    .getByRole("link", {
      name: "Open healthy-target in query-fixture",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", { name: "healthy-target", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  failing = false;
  await page
    .locator(".sidebar")
    .getByRole("link", {
      name: "Open error-target in query-fixture",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", { name: "error-target", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("ordinary writes stay pending through refresh and do not update services optimistically", async ({
  page,
}) => {
  const environment = task("mutation-pending");
  let pendingWrite: Route | undefined;
  let pendingRefresh: Route | undefined;
  let written = false;
  let writes = 0;
  await page.route("**/api/state", (route) => {
    if (written) {
      pendingRefresh = route;
      return;
    }
    return route.fulfill({
      json: {
        ok: true,
        result: { projects: [], taskenvs: [environment], secrets: [] },
      },
    });
  });
  await page.route("**/api/task/*", (route) =>
    route.fulfill({ json: { ok: true, result: environment } }),
  );
  await page.route("**/api/action", (route) => {
    writes++;
    pendingWrite = route;
  });
  await page.goto("/#/environments/mutation-pending/services");
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect.poll(() => !!pendingWrite).toBe(true);
  const progress = page
    .getByRole("status")
    .filter({ hasText: "Operation in progress" });
  await expect(progress).toBeVisible();
  await expect(page.locator(".service-row .state")).toHaveText("running");
  environment.services[0].state = "stopped";
  written = true;
  await pendingWrite!.fulfill({
    json: { ok: true, result: { updated: true } },
  });
  await expect.poll(() => !!pendingRefresh).toBe(true);
  await expect(progress).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start", exact: true }),
  ).toBeDisabled();
  await pendingRefresh!.fulfill({
    json: {
      ok: true,
      result: { projects: [], taskenvs: [environment], secrets: [] },
    },
  });
  await expect(page.locator(".service-row .state")).toHaveText("stopped");
  await expect(progress).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Start", exact: true }),
  ).toBeEnabled();
  expect(writes).toBe(1);
});

for (const writeFails of [false, true]) {
  test(`a failed post-write read preserves the ${writeFails ? "failed" : "successful"} mutation outcome`, async ({
    page,
  }) => {
    const environment = task("mutation-read-error");
    let written = false;
    let writes = 0;
    await page.route("**/api/state", (route) =>
      route.fulfill({
        json: written
          ? { ok: false, error: { message: "State read unavailable" } }
          : {
              ok: true,
              result: { projects: [], taskenvs: [environment], secrets: [] },
            },
      }),
    );
    await page.route("**/api/task/*", (route) =>
      route.fulfill({ json: { ok: true, result: environment } }),
    );
    await page.route("**/api/action", (route) => {
      writes++;
      written = true;
      return route.fulfill({
        json: writeFails
          ? { ok: false, error: { message: "Write outcome unknown" } }
          : { ok: true, result: { updated: true } },
      });
    });
    await page.goto("/#/environments/mutation-read-error/services");
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    if (writeFails) {
      await expect(page.getByRole("alert")).toContainText(
        "Write outcome unknown",
      );
      await expect(
        page.getByRole("status").filter({ hasText: "completed" }),
      ).toHaveCount(0);
    } else {
      await expect(
        page.getByRole("status").filter({ hasText: "Stop api completed" }),
      ).toBeVisible();
      await expect(page.getByRole("alert")).toContainText(
        "State read unavailable",
      );
    }
    await expect(
      page.getByRole("status").filter({ hasText: "Operation in progress" }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    expect(writes).toBe(1);
    await page.reload();
    await expect(page.getByRole("alert")).toContainText(
      "State read unavailable",
    );
    expect(writes).toBe(1);
  });
}

test("secret failures clear input and remain explicit across polling and reconnect", async ({
  page,
}) => {
  await installClock(page);
  const actions: Action[] = [];
  await page.route("**/api/state", (route) =>
    route.fulfill({
      json: { ok: true, result: { projects: [], taskenvs: [], secrets: [] } },
    }),
  );
  await page.route("**/api/action", (route) => {
    actions.push(route.request().postDataJSON());
    return route.fulfill({
      json: { ok: false, error: { message: "Secret save failed" } },
    });
  });
  await page.goto("/#/secrets");
  await page.getByLabel("Name").fill("test-secret");
  await page
    .getByLabel("Value", { exact: true })
    .fill("synthetic-private-value");
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert")).toContainText("Secret save failed");
  await expect(page.getByLabel("Value", { exact: true })).toBeEmpty();
  await expect(page.locator("body")).not.toContainText(
    "synthetic-private-value",
  );
  await expect(page.getByRole("button", { name: "Save" })).toBeEnabled();
  await page.clock.runFor(10000);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Secrets", exact: true }),
  ).toBeVisible();
  expect(actions.map((action) => action.action)).toEqual(["secret.set"]);
});

test("changing port values uses the ordinary write lifecycle and refreshes configuration", async ({
  page,
}) => {
  const environment = task("port-write");
  environment.environment = { values: { PORT: "8400" }, secret_refs: {} };
  const actions: Action[] = [];
  await page.route("**/api/state", (route) =>
    route.fulfill({
      json: {
        ok: true,
        result: { projects: [], taskenvs: [environment], secrets: [] },
      },
    }),
  );
  await page.route("**/api/task/*", (route) =>
    route.fulfill({ json: { ok: true, result: environment } }),
  );
  await page.route("**/api/action", (route) => {
    const action = route.request().postDataJSON() as Action;
    actions.push(action);
    environment.environment = {
      values: { PORT: action.value || "" },
      secret_refs: {},
    };
    return route.fulfill({ json: { ok: true, result: { updated: true } } });
  });
  await page.goto("/#/environments/port-write/configuration");
  await page.getByLabel("Port key", { exact: true }).fill("PORT");
  await page.getByLabel("Port", { exact: true }).fill("8500");
  await page.getByRole("button", { name: "Set port", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Update port completed" }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "8500", exact: true }),
  ).toBeVisible();
  expect(actions).toEqual([
    { action: "port.set", target: "port-write", name: "PORT", value: "8500" },
  ]);
});

test("a mutation finishing after navigation refreshes the selected environment", async ({
  page,
}) => {
  const environments = [task("write-origin"), task("write-destination")];
  let pendingWrite: Route | undefined;
  const detailReads: string[] = [];
  await page.route("**/api/state", (route) =>
    route.fulfill({
      json: {
        ok: true,
        result: { projects: [], taskenvs: environments, secrets: [] },
      },
    }),
  );
  await page.route("**/api/task/*", (route) => {
    const id = route.request().url().split("/").at(-1) || "";
    detailReads.push(id);
    return route.fulfill({
      json: {
        ok: true,
        result: environments.find((environment) => environment.id === id),
      },
    });
  });
  await page.route("**/api/action", (route) => {
    pendingWrite = route;
  });
  await page.goto("/#/environments/write-origin/services");
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect.poll(() => !!pendingWrite).toBe(true);
  await page
    .locator(".sidebar")
    .getByRole("link", {
      name: "Open write-destination in query-fixture",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", { name: "write-destination", exact: true }),
  ).toBeVisible();
  const before = detailReads.length;
  environments[1].services[0].state = "failed";
  await pendingWrite!.fulfill({
    json: { ok: true, result: { updated: true } },
  });
  await expect(page.locator(".service-row .state")).toHaveText("failed");
  const refreshed = detailReads.slice(before);
  expect(refreshed.length).toBeGreaterThan(0);
  expect(refreshed.every((id) => id === "write-destination")).toBe(true);
  await expect(
    page.getByRole("status").filter({ hasText: "Operation in progress" }),
  ).toHaveCount(0);
});

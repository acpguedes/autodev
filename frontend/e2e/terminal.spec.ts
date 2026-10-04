import { expect, test, type Page } from "playwright/test";

// E65-S3: the Terminal tab appears only when the server enables it; output from
// the socket renders and typing emits an `input` frame.

const API_ORIGIN = "http://localhost:8000";

async function mockShell(page: Page, enabled: boolean): Promise<void> {
  await page.route(`${API_ORIGIN}/v2/terminal/status`, (route) =>
    route.fulfill({ json: { enabled } })
  );
  await page.route(`${API_ORIGIN}/v2/projects`, (route) =>
    route.fulfill({
      json: {
        schemaVersion: "v2",
        items: [{ projectId: "p1", name: "demo", rootPath: "/work/demo", active: true }],
        activeProjectId: "p1",
      },
    })
  );
}

test("Terminal tab is absent when the feature is disabled", async ({ page }) => {
  await mockShell(page, false);
  await page.goto("/plans");
  await page.getByRole("banner").getByRole("button", { name: "Execution" }).click();
  await expect(page.getByRole("complementary", { name: "Execution panel" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Terminal" })).toHaveCount(0);
});

test("terminal renders output and typing emits an input frame", async ({ page }) => {
  await mockShell(page, true);
  const received: unknown[] = [];
  await page.routeWebSocket(/\/v2\/terminal\/[^/]+$/, (ws) => {
    ws.onMessage((message) => {
      received.push(JSON.parse(String(message)));
    });
    ws.send(JSON.stringify({ type: "info", projectRoot: "/work/demo", terminalId: "t" }));
    ws.send(JSON.stringify({ type: "output", data: "hello-from-shell\r\n" }));
  });

  await page.goto("/plans");
  await page.getByRole("banner").getByRole("button", { name: "Execution" }).click();
  await page.getByRole("tab", { name: "Terminal" }).click();

  const host = page.getByTestId("terminal-host");
  await expect(host).toBeVisible();
  await expect(host).toContainText("hello-from-shell");

  await host.click();
  await page.keyboard.type("ls");
  await expect
    .poll(() =>
      received.some((f) => (f as { type?: string; data?: string }).type === "input")
    )
    .toBe(true);
});

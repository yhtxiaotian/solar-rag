import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function waitForServer(url, output) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
    } catch {
      // The production server may still be binding its port.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Next.js server did not start:\n${output()}`);
}

test("production server renders public and admin pages", async (context) => {
  const port = 34000 + (process.pid % 1000);
  let logs = "";
  const server = spawn(
    process.execPath,
    [path.join(root, "node_modules", "next", "dist", "bin", "next"), "start", "-p", String(port)],
    { cwd: root, env: { ...process.env, NODE_ENV: "production" }, stdio: ["ignore", "pipe", "pipe"] },
  );
  server.stdout.on("data", (chunk) => { logs += chunk; });
  server.stderr.on("data", (chunk) => { logs += chunk; });
  context.after(() => server.kill());

  const homeResponse = await waitForServer(`http://127.0.0.1:${port}/`, () => logs);
  const home = await homeResponse.text();
  assert.match(home, /<title>光伏智库｜分布式光伏知识问答<\/title>/);
  assert.match(home, /专业知识问答/);
  assert.match(home, /从资料中找到/);
  assert.match(home, /可靠答案/);
  assert.doesNotMatch(home, /codex-preview|react-loading-skeleton|Your site is taking shape/);

  const adminResponse = await fetch(`http://127.0.0.1:${port}/admin`);
  assert.equal(adminResponse.status, 200);
  assert.match(await adminResponse.text(), /正在连接知识库/);
});

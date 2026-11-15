"use strict";
const { chromium } = require("playwright");
const { createServer } = require("node:http");
const { readFile, mkdir } = require("node:fs/promises");
const { join, extname, resolve } = require("node:path");

const webRoot = resolve(__dirname, "..");
const output = resolve(process.env.SCREENSHOT_DIR || "build/website-screenshots");
const github = "https://github.com/maillunex-lang/LunexEconom/releases/latest";
const manifest = {
  version_code: 2000001, version_name: "2.0.1", min_version_code: 1,
  apk_url: "https://rikagro.ru/lunexeconom/download/lunex.apk", size: 74631872,
  sha256: "c".repeat(64), notes: "Улучшена карта и экран компании.", released: "2026-11-15T11:00:00Z"
};
const types = {".html":"text/html; charset=utf-8", ".css":"text/css", ".js":"text/javascript", ".json":"application/json"};
const shots = new Set(["latest", "manifest", "none", "test"]);
const json = (body, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify(body) });
const server = createServer(async (req, res) => {
  const path = new URL(req.url, "http://localhost").pathname;
  const relative = path.replace(/^\/lunexeconom\/?/, "") || "index.html";
  if (relative === "latest.json" || relative === "update.json") { res.writeHead(404); res.end("missing"); return; }
  if (!/^[\w.\/-]+$/.test(relative) || relative.includes("..")) { res.writeHead(403); res.end(); return; }
  try { const bytes = await readFile(join(webRoot, relative)); res.writeHead(200, {"content-type": types[extname(relative)] || "application/octet-stream"}); res.end(bytes); }
  catch { res.writeHead(404); res.end("missing"); }
});
(async () => {
  const latest = JSON.parse(await readFile(join(__dirname, "fixtures/latest.example.json"), "utf8"));
  const testBuild = { ...latest, channel: "test", notes: "Тестовая сборка для проверки канала, не для игроков." };
  await mkdir(output, { recursive: true });
  const roadmap = JSON.parse(await readFile(join(webRoot, "roadmap.json"), "utf8"));
  const expectedProgress = `${Math.round(roadmap.phases.reduce((sum, phase) => sum + phase.progress, 0) / roadmap.phases.length)}%`;
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}/lunexeconom/`;
  const browser = await chromium.launch({ headless: true });
  const expectDate = (text) => { if (!text.includes("2026") || !text.toLowerCase().includes("ноябр")) throw Error(`Bad Russian date: ${text}`); };
  const ignored404 = (scenario, url, text) => {
    if (!text.includes("404")) return false;
    if (url.endsWith("/latest.json") && scenario !== "latest" && scenario !== "test") return true;
    if (url.endsWith("/update.json") && (scenario === "none" || scenario === "test")) return true;
    return false;
  };
  const stub = async (page, scenario) => {
    await page.route("**/latest.json", route => {
      if (scenario === "latest") return route.fulfill(json(latest));
      if (scenario === "test") return route.fulfill(json(testBuild));
      if (scenario === "bad") return route.fulfill(json({ schema: 1, channel: "debug", notes: "нет" }));
      return route.fulfill({ status: 404, body: "missing" });
    });
    await page.route("**/update.json", route => {
      if (scenario === "latest") return route.fulfill(json({ ...manifest, version_name: "9.9.9" }));
      if (scenario === "manifest" || scenario === "bad") return route.fulfill(json(manifest));
      if (scenario === "foreign") return route.fulfill(json({ ...manifest, apk_url: "https://evil.example/hello.apk" }));
      return route.fulfill({ status: 404, body: "missing" });
    });
  };
  const check = async (page, scenario) => {
    const href = await page.locator("#apk-link").getAttribute("href");
    const label = (await page.locator("#apk-link").innerText()).trim();
    const version = (await page.locator("#apk-version").innerText()).trim();
    const banner = page.locator("#channel-banner");
    const testLink = page.locator("#test-apk-link");
    const previous = page.locator("#previous-release");
    if (scenario === "latest") {
      if (href !== latest.apk_url || label !== "Скачать для Android") throw Error(`latest button ${label} ${href}`);
      if (version !== latest.version_name) throw Error(`latest version ${version}`);
      if ((await page.locator("#apk-code").innerText()).trim() !== String(latest.version_code)) throw Error("latest code");
      if ((await page.locator("#apk-channel").innerText()).trim() !== "альфа") throw Error("latest channel");
      if ((await page.locator("#apk-size").innerText()).trim() !== "71,2 МиБ") throw Error("latest size");
      expectDate(await page.locator("#apk-date").innerText());
      if ((await page.locator("#apk-hash").innerText()).trim() !== latest.sha256) throw Error("latest sha");
      if (!(await page.locator("#whats-new").innerText()).includes("альфа")) throw Error("latest notes");
      if (!(await page.locator("#release-status").innerText()).includes("latest.json")) throw Error("latest status");
      if (await banner.isVisible() || await testLink.isVisible()) throw Error("alpha must not look like a test build");
      if (await previous.isHidden()) throw Error("previous hidden");
      if (await page.locator("#previous-link").getAttribute("href") !== latest.previous.apk_url) throw Error("previous url");
      if ((await page.locator("#previous-link").innerText()).trim() !== latest.previous.version_name) throw Error("previous label");
      if ((await page.locator("#previous-hash").innerText()).trim() !== latest.previous.sha256) throw Error("previous sha");
      if (await page.locator("#copy-sha").isHidden()) throw Error("copy hidden");
    }
    if (scenario === "manifest") {
      if (href !== manifest.apk_url || label !== "Скачать для Android" || version !== manifest.version_name) throw Error(`manifest fallback ${label} ${href} ${version}`);
      if (await banner.isVisible() || await testLink.isVisible() || await previous.isVisible()) throw Error("manifest showed latest chrome");
    }
    if (scenario === "none" || scenario === "foreign") {
      if (href !== github || label !== "Последний релиз на GitHub" || version !== "Нет данных") throw Error(`${scenario} fallback ${label} ${href} ${version}`);
      if (!(await page.locator("#release-status").innerText()).includes("GitHub")) throw Error(`${scenario} status`);
      if (await banner.isVisible() || await previous.isVisible()) throw Error(`${scenario} invented a build`);
    }
    if (scenario === "test") {
      if ((await banner.innerText()).trim() !== "тестовая сборка, не для обычной игры") throw Error("test plaque");
      if (await testLink.isHidden()) throw Error("test button hidden");
      if (await testLink.getAttribute("href") !== testBuild.apk_url || (await testLink.innerText()).trim() !== "Скачать тестовую сборку") throw Error("test button target");
      if (href !== github || label !== "Последний релиз на GitHub") throw Error("test build used the official button");
      if ((await page.locator("#apk-channel").innerText()).trim() !== "тест") throw Error("test channel label");
      if (version !== testBuild.version_name) throw Error("test version");
    }
    if (scenario === "bad") {
      if (href !== manifest.apk_url || version !== manifest.version_name) throw Error("invalid latest did not fall back");
      if (await banner.isVisible()) throw Error("invalid latest showed the test plaque");
    }
    if ((await page.locator("#roadmap-progress").innerText()) !== expectedProgress) throw Error(`Roadmap wrong total, expected ${expectedProgress}`);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    if (overflow) throw Error(`Horizontal overflow`);
  };
  try {
    for (const scenario of ["latest", "manifest", "none", "test", "bad", "foreign"]) {
      const viewports = shots.has(scenario) ? [{width:360,height:800}, {width:1440,height:900}] : [{width:1440,height:900}];
      const themes = shots.has(scenario) ? ["dark", "light"] : ["dark"];
      for (const {width, height} of viewports) {
        for (const theme of themes) {
          const page = await browser.newPage({ viewport: {width, height}, colorScheme: theme, deviceScaleFactor: 1, permissions: ["clipboard-read", "clipboard-write"] });
          const errors = [];
          page.on("pageerror", error => errors.push(error.message));
          page.on("console", message => {
            if (message.type() !== "error") return;
            if (!ignored404(scenario, message.location().url || "", message.text())) errors.push(message.text());
          });
          await stub(page, scenario);
          await page.goto(base, { waitUntil: "networkidle" });
          await check(page, scenario);
          if (scenario === "latest" && width === 1440 && theme === "dark") {
            await page.locator("#copy-sha").click();
            await page.waitForFunction(() => document.getElementById("copy-sha").textContent.trim() === "Скопировано");
            const clip = await page.evaluate(() => navigator.clipboard.readText());
            if (clip !== latest.sha256) throw Error(`clipboard ${clip}`);
          }
          if (errors.length) throw Error(`Browser errors: ${errors.join(" | ")}`);
          if (shots.has(scenario)) {
            const filename = `${scenario}-${width}x${height}-${theme}.png`;
            await page.screenshot({ path: join(output, filename), fullPage: true, animations: "disabled" });
            console.log(`PASS ${filename}`);
          } else console.log(`PASS ${scenario} ${width}x${height} ${theme}`);
          await page.close();
        }
      }
    }
    const page = await browser.newPage({ javaScriptEnabled: false });
    await page.goto(base);
    if (!await page.locator("#roadmap-milestones .milestone").count() || !await page.locator("#roadmap-phases .phase-card").count()) throw Error("No-JS roadmap missing");
    const note = page.locator("#download .noscript-note");
    if (await note.count() !== 1) throw Error("No-JS download note missing");
    const noteText = await note.innerText();
    if (!noteText.includes("JavaScript") || !noteText.toLowerCase().includes("релиз")) throw Error(`No-JS note: ${noteText}`);
    if (await note.locator("a").getAttribute("href") !== github) throw Error("No-JS releases link");
    if ((await page.locator("#apk-link").innerText()).trim() !== "Последний релиз на GitHub") throw Error("No-JS download link");
    if (!(await page.locator("h1").innerText()).includes("Башкирия")) throw Error("No-JS page unreadable");
    console.log("PASS no JavaScript fallback");
    await page.close();
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; server.close(); });

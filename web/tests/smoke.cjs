"use strict";
const { chromium } = require("playwright");
const { createServer } = require("node:http");
const { readFile, mkdir } = require("node:fs/promises");
const { join, extname, resolve } = require("node:path");

const webRoot = resolve(__dirname, "..");
const output = resolve(process.env.SCREENSHOT_DIR || "build/website-screenshots");
const manifest = {
  version_code: 2000001, version_name: "2.0.1", min_version_code: 1,
  apk_url: "https://rikagro.ru/lunexeconom/download/lunex.apk", size: 74631872,
  sha256: "a".repeat(64), notes: "Улучшена карта и экран компании.", released: "2026-11-15T11:00:00Z"
};
const types = {".html":"text/html; charset=utf-8", ".css":"text/css", ".js":"text/javascript", ".json":"application/json"};
const server = createServer(async (req, res) => {
  const path = new URL(req.url, "http://localhost").pathname;
  const relative = path.replace(/^\/lunexeconom\/?/, "") || "index.html";
  if (relative === "update.json") {
    if (req.headers["x-test-manifest"] === "missing" || process.env.NO_MANIFEST === "1") { res.writeHead(404); res.end("missing"); return; }
    res.writeHead(200, {"content-type":"application/json"}); res.end(JSON.stringify(manifest)); return;
  }
  if (!/^[\w.\/-]+$/.test(relative) || relative.includes("..")) { res.writeHead(403);res.end();return; }
  try { const bytes = await readFile(join(webRoot, relative)); res.writeHead(200, {"content-type":types[extname(relative)] || "application/octet-stream"}); res.end(bytes); }
  catch { res.writeHead(404);res.end("missing"); }
});
(async () => {
  await mkdir(output, {recursive:true});
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}/lunexeconom/`;
  const browser = await chromium.launch({headless:true});
  try {
    for (const scenario of ["present", "missing", "foreign"]) {
      for (const {width, height} of [{width:360,height:800}, {width:1440,height:900}]) {
        for (const theme of ["dark", "light"]) {
          const page = await browser.newPage({viewport:{width,height}, colorScheme:theme, deviceScaleFactor:1});
          const errors = [];
          page.on("pageerror", error => errors.push(error.message));
          page.on("console", message => {
            if (message.type() !== "error") return;
            const isMissingManifest = scenario === "missing" && message.location().url.endsWith("/update.json") && message.text().includes("404");
            if (!isMissingManifest) errors.push(message.text());
          });
          if (scenario === "missing") await page.route("**/update.json", route => route.fulfill({status:404,body:"missing"}));
          if (scenario === "foreign") await page.route("**/update.json", route => route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({...manifest,apk_url:"https://evil.example/hello.apk"})}));
          await page.goto(base, {waitUntil:"networkidle"});
          const expected = scenario === "present" ? manifest.apk_url : "https://github.com/maillunex-lang/LunexEconom/releases/latest";
          const href = await page.locator("#apk-link").getAttribute("href");
          if (href !== expected) throw Error(`${scenario}: wrong APK href ${href}`);
          if (scenario === "present") {
            if ((await page.locator("#apk-link").innerText()) !== "Скачать для Android") throw Error("Live APK button not enabled");
            if ((await page.locator("#apk-version").innerText()) !== manifest.version_name) throw Error("Wrong version");
          }
          if ((await page.locator("#roadmap-progress").innerText()) !== "28%") throw Error("Roadmap wrong total");
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
          if (overflow) throw Error(`Horizontal overflow at ${width}`);
          if (errors.length) throw Error(`Browser errors: ${errors.join(" | ")}`);
          const filename = `${scenario}-${width}x${height}-${theme}.png`;
          await page.screenshot({path:join(output,filename),fullPage:true,animations:"disabled"});
          console.log(`PASS ${filename} href=${href}`);
          await page.close();
        }
      }
    }
    const page = await browser.newPage({javaScriptEnabled:false});
    await page.goto(base);
    if (!await page.locator("#roadmap-milestones .milestone").count() || !await page.locator("#roadmap-phases .phase-card").count()) throw Error("No-JS fallback missing");
    console.log("PASS no JavaScript fallback"); await page.close();
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => {console.error(error);process.exitCode=1; server.close();});

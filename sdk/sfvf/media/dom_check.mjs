/**
 * Headless DOM inspection for media.graphics.check() (SDK §6.5).
 *
 * Loads the composition once (t=0) and reports outside-viewport, safe-zone,
 * text-clipped, and missing-font failures. Time-sampling of animated
 * compositions is out of scope for E-2a.
 *
 * Usage: node dom_check.mjs <toolchainPkgJsonUrl> <projectDir> <safe_zone>
 * Prints a JSON array of {kind, detail} to stdout and nothing else.
 */
import { createRequire } from "node:module";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const W = 1080;
const H = 1920;
const EPS = 2;
const SAFE_TOP = 192;
const SAFE_RIGHT = 918;
const SAFE_BOTTOM = 1632;
const SAFE_LEFT = 0;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
};

async function main() {
  const toolchainPkgJsonUrl = process.argv[2];
  const projectDir = process.argv[3];
  const safeZoneArg = process.argv[4] ?? "true";
  if (!toolchainPkgJsonUrl || !projectDir) {
    throw new Error(
      "usage: dom_check.mjs <toolchainPkgJsonUrl> <projectDir> <safe_zone>"
    );
  }
  const safeZone = safeZoneArg !== "0" && safeZoneArg !== "false";
  const pkgUrl = toolchainPkgJsonUrl.includes("://")
    ? toolchainPkgJsonUrl
    : pathToFileURL(path.resolve(toolchainPkgJsonUrl)).href;
  const require = createRequire(pkgUrl);
  const puppeteer = require("puppeteer-core");
  const browsers = require("@puppeteer/browsers");

  const executablePath = await resolveChrome(browsers);
  let server;
  let browser;
  try {
    server = await startStaticServer(path.resolve(projectDir));
    browser = await puppeteer.launch({
      headless: true,
      executablePath,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
    const page = await browser.newPage();
    await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
    await page.goto(`http://127.0.0.1:${server.port}/index.html`, {
      waitUntil: "networkidle0",
    });
    await page.evaluateHandle("document.fonts.ready");
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(() =>
      Promise.all(
        [...document.images].map((img) => {
          img.loading = "eager";
          if (img.complete) {
            return undefined;
          }
          return new Promise((resolve) => {
            const done = () => {
              clearTimeout(timer);
              resolve();
            };
            const timer = setTimeout(done, 10_000);
            img.addEventListener("load", done, { once: true });
            img.addEventListener("error", done, { once: true });
          });
        })
      )
    );
    await page.evaluate(() => {
      for (const animation of document.getAnimations()) {
        animation.pause();
        animation.currentTime = 0;
      }
    });
    await page.evaluate(
      () =>
        new Promise((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        })
    );
    const violations = await page.evaluate(measure, {
      safeZone,
      W,
      H,
      EPS,
      SAFE_TOP,
      SAFE_RIGHT,
      SAFE_BOTTOM,
      SAFE_LEFT,
    });
    process.stdout.write(`${JSON.stringify(violations)}\n`);
  } finally {
    await Promise.allSettled([
      browser ? browser.close() : undefined,
      server ? server.close() : undefined,
    ]);
  }
}

async function resolveChrome(browsers) {
  for (const name of [
    "PUPPETEER_EXECUTABLE_PATH",
    "HYPERFRAMES_BROWSER_PATH",
    "PRODUCER_HEADLESS_SHELL_PATH",
  ]) {
    const envPath = process.env[name];
    if (envPath && fs.existsSync(envPath)) {
      return envPath;
    }
  }
  const home = os.homedir();
  const cacheDirs = [
    process.env.PUPPETEER_CACHE_DIR || path.join(home, ".cache", "puppeteer"),
    path.join(home, ".cache", "hyperframes", "chrome"),
  ];
  const preferred = ["chrome-headless-shell", "chrome"];
  for (const cacheDir of cacheDirs) {
    if (!fs.existsSync(cacheDir)) {
      continue;
    }
    let installed;
    try {
      installed = await browsers.getInstalledBrowsers({ cacheDir });
    } catch {
      continue;
    }
    for (const name of preferred) {
      const matches = installed.filter(
        (entry) =>
          String(entry.browser) === name && fs.existsSync(entry.executablePath)
      );
      if (matches.length === 0) {
        continue;
      }
      matches.sort((a, b) => String(a.buildId).localeCompare(String(b.buildId)));
      return matches[matches.length - 1].executablePath;
    }
  }
  for (const systemPath of systemChromePaths()) {
    if (fs.existsSync(systemPath)) {
      return systemPath;
    }
  }
  throw new Error(
    `No Chrome binary found. Set PUPPETEER_EXECUTABLE_PATH or HYPERFRAMES_BROWSER_PATH, ` +
      `or install Chrome into one of: ${cacheDirs.join(", ")}.`
  );
}

function systemChromePaths() {
  if (process.platform === "win32") {
    return [
      process.env["PROGRAMFILES"],
      process.env["PROGRAMFILES(X86)"],
      process.env["LOCALAPPDATA"],
    ]
      .filter(Boolean)
      .map((base) =>
        path.join(base, "Google", "Chrome", "Application", "chrome.exe")
      );
  }
  if (process.platform === "darwin") {
    return ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"];
  }
  return [
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ];
}

function startStaticServer(root) {
  const resolvedRoot = path.resolve(root);
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      try {
        const rawPath = decodeURIComponent((req.url ?? "/").split("?")[0]);
        const rel = rawPath.replace(/^\/+/, "") || "index.html";
        const abs = path.resolve(resolvedRoot, rel);
        const relative = path.relative(resolvedRoot, abs);
        if (relative.startsWith("..") || path.isAbsolute(relative)) {
          res.writeHead(403);
          res.end("forbidden");
          return;
        }
        if (!fs.existsSync(abs) || fs.statSync(abs).isDirectory()) {
          res.writeHead(404);
          res.end("not found");
          return;
        }
        const ext = path.extname(abs).toLowerCase();
        const type = MIME[ext] ?? "application/octet-stream";
        res.writeHead(200, { "Content-Type": type });
        const stream = fs.createReadStream(abs);
        stream.on("error", () => {
          res.destroy();
        });
        stream.pipe(res);
      } catch (err) {
        res.writeHead(500);
        res.end(err instanceof Error ? err.message : String(err));
      }
    });
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (addr === null || typeof addr === "string") {
        reject(new Error("static server did not bind a TCP port"));
        return;
      }
      resolve({
        port: addr.port,
        close: () =>
          new Promise((done, fail) => {
            server.close((err) => (err ? fail(err) : done()));
          }),
      });
    });
  });
}

function measure({
  safeZone,
  W,
  H,
  EPS,
  SAFE_TOP,
  SAFE_RIGHT,
  SAFE_BOTTOM,
  SAFE_LEFT,
}) {
  const REPLACED = new Set(["IMG", "SVG", "CANVAS", "VIDEO", "PICTURE"]);
  const SKIP_TAGS = new Set([
    "SCRIPT",
    "STYLE",
    "HEAD",
    "LINK",
    "META",
    "TITLE",
    "NOSCRIPT",
  ]);
  const CLIP_OVERFLOW = new Set(["hidden", "clip", "scroll", "auto"]);
  const violations = [];
  const root = document.getElementById("root");
  if (root === null) {
    throw new Error("composition is missing #root");
  }
  const erroredFamilies = new Set();
  document.fonts.forEach((face) => {
    if (face.status === "error") {
      erroredFamilies.add(normalizeFamily(face.family));
    }
  });

  for (const el of [root, ...root.querySelectorAll("*")]) {
    if (SKIP_TAGS.has(el.tagName)) {
      continue;
    }
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      continue;
    }
    const hasText = hasDirectText(el);
    const isReplaced = REPLACED.has(el.tagName);
    if (!hasText && !isReplaced) {
      continue;
    }
    const fullFrame =
      rect.left <= EPS &&
      rect.top <= EPS &&
      rect.right >= W - EPS &&
      rect.bottom >= H - EPS;
    const name = describe(el);
    const box = `(${Math.round(rect.left)},${Math.round(rect.top)},${Math.round(rect.right)},${Math.round(rect.bottom)})`;

    let outside = false;
    // Full-frame exemption is for backgrounds (full-bleed replaced elements),
    // not for text that fills the frame and sits under reserved margins.
    if (!fullFrame || hasText) {
      if (
        rect.left < -EPS ||
        rect.top < -EPS ||
        rect.right > W + EPS ||
        rect.bottom > H + EPS
      ) {
        outside = true;
        violations.push({
          kind: "outside-viewport",
          detail: `${name} extends to ${box} outside ${W}x${H}`,
        });
      }
      if (
        safeZone &&
        !outside &&
        (rect.top < SAFE_TOP - EPS ||
          rect.right > SAFE_RIGHT + EPS ||
          rect.bottom > SAFE_BOTTOM + EPS ||
          rect.left < SAFE_LEFT - EPS)
      ) {
        violations.push({
          kind: "safe-zone",
          detail: `${name} intersects the reserved safe zone at ${box}`,
        });
      }
    }

    if (hasText) {
      const style = getComputedStyle(el);
      if (
        (CLIP_OVERFLOW.has(style.overflowX) || CLIP_OVERFLOW.has(style.overflowY)) &&
        (el.scrollWidth - el.clientWidth > EPS ||
          el.scrollHeight - el.clientHeight > EPS)
      ) {
        violations.push({
          kind: "text-clipped",
          detail:
            `${name} clips text (scroll ${el.scrollWidth}x${el.scrollHeight} ` +
            `vs client ${el.clientWidth}x${el.clientHeight})`,
        });
      }
      const family = primaryFamily(style.fontFamily);
      if (family && erroredFamilies.has(family)) {
        violations.push({
          kind: "missing-font",
          detail: `${name} font-family '${family}' failed to load`,
        });
      }
    }
  }
  return violations;

  function hasDirectText(el) {
    for (const node of el.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && (node.textContent ?? "").trim() !== "") {
        return true;
      }
    }
    return false;
  }

  function describe(el) {
    const tag = el.tagName.toLowerCase();
    if (el.id) {
      return `${tag}#${el.id}`;
    }
    const raw = el.getAttribute("class");
    if (raw && raw.trim()) {
      return `${tag}.${raw.trim().split(/\s+/).join(".")}`;
    }
    return tag;
  }

  function normalizeFamily(value) {
    return value.replace(/['"]/g, "").trim().toLowerCase();
  }

  function primaryFamily(fontFamily) {
    return normalizeFamily(fontFamily.split(",")[0] ?? "");
  }
}

main().catch((err) => {
  const message = err instanceof Error ? err.message : String(err);
  process.stderr.write(`${message}\n`);
  process.exit(1);
});

# TASK E-2a fixes — apply EXACTLY these two edits to `sdk/sfvf/media/dom_check.mjs`

Apply ONLY the two edits below. Do NOT change anything else in any file — leave `measure()`, the
image-wait loop, `_parse_violations`, the `finally` block, and every test exactly as they are now.

## EDIT A — replace the whole `resolveChrome` function (add hyperframes-cache + system-Chrome fallbacks)

Find this exact function:

```js
async function resolveChrome(browsers) {
  for (const name of ["PUPPETEER_EXECUTABLE_PATH", "HYPERFRAMES_BROWSER_PATH"]) {
    const envPath = process.env[name];
    if (envPath && fs.existsSync(envPath)) {
      return envPath;
    }
  }
  const cacheDir =
    process.env.PUPPETEER_CACHE_DIR ||
    path.join(os.homedir(), ".cache", "puppeteer");
  const installed = await browsers.getInstalledBrowsers({ cacheDir });
  const preferred = ["chrome-headless-shell", "chrome"];
  for (const name of preferred) {
    const matches = installed.filter((entry) => String(entry.browser) === name);
    if (matches.length === 0) {
      continue;
    }
    matches.sort((a, b) => String(a.buildId).localeCompare(String(b.buildId)));
    return matches[matches.length - 1].executablePath;
  }
  throw new Error(
    `No Chrome binary found. Set PUPPETEER_EXECUTABLE_PATH or HYPERFRAMES_BROWSER_PATH, ` +
      `or install Chrome into ${cacheDir}.`
  );
}
```

Replace it with exactly this (two functions):

```js
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
```

## EDIT B — give the static-server read stream an error handler

Find this exact line (inside `startStaticServer`):

```js
        fs.createReadStream(abs).pipe(res);
```

Replace it with exactly:

```js
        const stream = fs.createReadStream(abs);
        stream.on("error", () => {
          res.destroy();
        });
        stream.pipe(res);
```

## EDIT C — image-wait must degrade, not hard-fail, on a slow image

An image that never settles within the bound must fall through to measuring the current DOM, not
fail the whole check (a legitimate slow remote asset should not turn `check()` into a `RuntimeError`).
In the image-wait loop, find this exact block:

```js
          return new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
              reject(
                new Error(
                  `image wait timed out: ${img.currentSrc || img.src || img.tagName}`
                )
              );
            }, 10_000);
            const done = () => {
              clearTimeout(timer);
              resolve();
            };
            img.addEventListener("load", done, { once: true });
            img.addEventListener("error", done, { once: true });
          });
```

Replace it with exactly:

```js
          return new Promise((resolve) => {
            const done = () => {
              clearTimeout(timer);
              resolve();
            };
            const timer = setTimeout(done, 10_000);
            img.addEventListener("load", done, { once: true });
            img.addEventListener("error", done, { once: true });
          });
```

## Verify (from the worktree)
Run all and make them pass/clean:
- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_graphics.py tests/integration/test_composition_check.py -q`
- `./.venv/Scripts/python.exe -m ruff check .`
- `./.venv/Scripts/python.exe -m ruff format --check .`
- `./.venv/Scripts/python.exe -m mypy sdk app`
- `node --check sdk/sfvf/media/dom_check.mjs`

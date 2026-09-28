import { build } from "esbuild";
import { cp, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(fileURLToPath(import.meta.url));
const dist = path.join(root, "dist");

// Content scripts cannot use ES module imports, so every entry point is
// bundled to a self-contained IIFE (KTD8). The service worker and options
// page share the same bundled lib modules.
const entries = ["background.js", "content.js", "options.js"].map((file) =>
  path.join(root, "src", file)
);

await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });

await build({
  entryPoints: entries,
  outdir: dist,
  bundle: true,
  format: "iife",
  target: ["chrome116"],
  platform: "browser",
  sourcemap: false,
  logLevel: "info",
});

await cp(path.join(root, "manifest.json"), path.join(dist, "manifest.json"));
await cp(path.join(root, "src", "options.html"), path.join(dist, "options.html"));

console.log(`Built extension to ${dist}`);

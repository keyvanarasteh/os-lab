// os-lab dashboard. Static output only: android-lab/lab/web_ui.py serves dist/ and stays the
// single backend (console/oslab.py), so there is no Astro server or adapter.
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "astro/config";
import { realpathSync } from "node:fs";

const api = process.env.OSLAB_API ?? "http://127.0.0.1:5050";
// scripts/deploy-page.sh builds for GitHub Pages under /<repo>/; everything else serves from /
const base = process.env.SITE_BASE || undefined;
// node_modules may be a link into the shared worktree cache; Vite serves its files by real path,
// so that folder must be allowed too or the dev server answers 403 for React and Astro client code.
let nodeModulesReal = "node_modules";
try { nodeModulesReal = realpathSync("node_modules"); } catch { /* not installed: dev cannot run anyway */ }

export default defineConfig({
  output: "static",
  // Per-worktree caches (plan item I): node_modules may be a link into a cache shared by every
  // worktree, so Astro and Vite must not write their caches inside it.
  cacheDir: "./.vite-cache/astro",
  base,
  integrations: [react()],
  build: { format: "directory" },
  devToolbar: { enabled: false },
  vite: {
    cacheDir: "./.vite-cache/vite",
    plugins: [tailwindcss()],
    // `npm run dev` talks to a running console (python3 android-lab/lab/web_ui.py)
    server: {
      // The legal pages render ../docs/legal/*.md (the repository's own copy)
      fs: { allow: ["..", nodeModulesReal] },
      proxy: {
        "/api": { target: api, changeOrigin: false },
        "/artifacts": { target: api, changeOrigin: false }
      }
    }
  }
});

#!/usr/bin/env node
// Plan item G: turn a list of changed files into the e2e specs, routes and locales that cover
// them, using e2e/affected.json.
//
// Usage:
//   node scripts/affected.mjs [--json] [file…]     files relative to the repository root
//   git diff --name-only … | node scripts/affected.mjs --stdin
//   node scripts/affected.mjs --check               fail when a spec is missing from the map
//
// Output (--json): { mode: "none" | "some" | "full", specs, routes, locales, unmapped }.
// Without --json it prints the spec paths, one per line ("e2e/x.spec.ts"), or nothing for "none".
// scripts/e2e.sh --changed and the dashboard-e2e workflow call it with the files from
// scripts/lib/changed-files.sh.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const dashboard = join(dirname(fileURLToPath(import.meta.url)), "..");
const e2eDir = join(dashboard, "e2e");
const LOCALES = ["ar", "de", "es", "fa", "fr", "it", "tr"];

export function loadMap(path = join(e2eDir, "affected.json")) {
  return JSON.parse(readFileSync(path, "utf8"));
}

export function listSpecs(dir = e2eDir) {
  return readdirSync(dir).filter((name) => name.endsWith(".spec.ts") && name !== "crawl.spec.ts").sort();
}

export function globToRegExp(glob) {
  let out = "";
  for (let i = 0; i < glob.length; i++) {
    const char = glob[i];
    if (char === "*" && glob[i + 1] === "*") {
      out += ".*";
      i++;
      if (glob[i + 1] === "/") i++;
    } else if (char === "*") out += "[^/]*";
    else out += char.replace(/[.+?^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp(`^${out}$`);
}

const matches = (patterns, file) => patterns.some((pattern) => globToRegExp(pattern).test(file));

/** files: paths relative to the repository root; outside dashboard/ only files a rule names count. */
export function affected(files, map = loadMap(), specs = listSpecs()) {
  const result = { mode: "none", specs: new Set(), routes: new Set(), locales: new Set(), unmapped: [] };
  const expand = (pattern) => specs.filter((spec) => globToRegExp(pattern).test(spec));
  const addSmoke = () => {
    map.smoke.specs.forEach((spec) => result.specs.add(spec));
    map.smoke.routes.forEach((route) => result.routes.add(route));
  };
  for (const file of files) {
    // Files outside dashboard/ count only when a rule names them ("../docs/legal/**").
    const inside = file.startsWith("dashboard/");
    const path = inside ? file.slice("dashboard/".length) : `../${file}`;
    if (!inside && !map.rules.some((rule) => matches(rule.paths, path))) continue;
    if (matches(map.ignore, path)) continue;
    if (matches(map.full, path)) {
      result.mode = "full";
      continue;
    }
    const rule = map.rules.find((candidate) => matches(candidate.paths, path));
    if (!rule) {
      result.unmapped.push(path);
      addSmoke();
      continue;
    }
    if (rule.self) {
      const name = path.slice("e2e/".length);
      if (specs.includes(name)) result.specs.add(name);
      continue;
    }
    if (rule.smoke) addSmoke();
    for (const pattern of rule.specs ?? []) expand(pattern).forEach((spec) => result.specs.add(spec));
    for (const route of rule.routes ?? []) result.routes.add(route);
    if (rule.locales === "from-file-name") {
      const locale = path.split("/").pop().replace(/\.json$/, "");
      if (LOCALES.includes(locale)) result.locales.add(locale);
    }
  }
  if (result.mode !== "full" && result.specs.size) result.mode = "some";
  if (result.mode === "full") {
    specs.forEach((spec) => result.specs.add(spec));
  }
  return {
    mode: result.mode,
    specs: [...result.specs].sort(),
    routes: [...result.routes].sort(),
    locales: [...result.locales].sort(),
    unmapped: result.unmapped
  };
}

/** Specs that no rule and no smoke entry names. */
export function unlistedSpecs(map = loadMap(), specs = listSpecs()) {
  const named = new Set(map.smoke.specs);
  for (const rule of map.rules) {
    for (const pattern of rule.specs ?? []) {
      specs.filter((spec) => globToRegExp(pattern).test(spec)).forEach((spec) => named.add(spec));
    }
  }
  return specs.filter((spec) => !named.has(spec));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const args = process.argv.slice(2);
  if (args.includes("--check")) {
    const missing = unlistedSpecs();
    if (missing.length) {
      console.error(`e2e/affected.json does not name these specs: ${missing.join(", ")}`);
      process.exit(1);
    }
    console.log(`e2e/affected.json names all ${listSpecs().length} specs`);
    process.exit(0);
  }
  let files = args.filter((arg) => !arg.startsWith("--"));
  if (args.includes("--stdin")) {
    files = files.concat(readFileSync(0, "utf8").split("\n").map((line) => line.trim()).filter(Boolean));
  }
  const result = affected(files);
  if (args.includes("--json")) console.log(JSON.stringify(result, null, 2));
  else result.specs.forEach((spec) => console.log(`e2e/${spec}`));
}

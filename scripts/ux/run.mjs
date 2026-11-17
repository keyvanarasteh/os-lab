#!/usr/bin/env node
// Run UX suites against a running dev stack (scripts/ux/dev-stack.sh start).
//   node scripts/ux/run.mjs [--suite shell,cleanup] [--base http://localhost:4321] [--out dir] [--headed] [--list]
// Exit code 0 only when every check passed. Screenshots and report.json go to --out.
// @lat: [[development#UX check library]]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { REPO, UxSession } from "./lib/ux.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const flag = (name, fallback) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : fallback; };
const available = fs.readdirSync(path.join(here, "suites")).filter((f) => f.endsWith(".mjs")).map((f) => f.replace(/\.mjs$/, ""));

if (argv.includes("--list")) { console.log(available.join("\n")); process.exit(0); }
const wanted = (flag("--suite", available.join(",")) ?? "").split(",").filter(Boolean);
const unknown = wanted.filter((name) => !available.includes(name));
if (unknown.length) { console.error(`unknown suite: ${unknown.join(", ")} (available: ${available.join(", ")})`); process.exit(2); }

const base = flag("--base", process.env.OSLAB_UX_BASE ?? "http://localhost:4321");
const out = path.resolve(flag("--out", path.join(REPO, "test-results/ux")));
try { await fetch(base, { signal: AbortSignal.timeout(5000) }); }
catch { console.error(`nothing answers at ${base}; start the stack with scripts/ux/dev-stack.sh start`); process.exit(2); }

let code = 0;
for (const name of wanted) {
  const suite = await import(pathToFileURL(path.join(here, "suites", `${name}.mjs`)).href);
  console.log(`\n== ${suite.name} ==`);
  const ux = await UxSession.open({ base, out: path.join(out, suite.name), headless: !argv.includes("--headed") });
  try { await suite.run(ux); }
  catch (error) { ux.check(`suite ${suite.name} ran to the end`, false, error.message); }
  code ||= await ux.close();
}
process.exit(code);

// The dashboard (src/firewall/devices.ts) and the MCP engine (console/firewall_catalog.py) must give
// every firewall the same id, vendor, model and category: MCP results link to dashboard pages by id.
import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, existsSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const dashboard = dirname(dirname(fileURLToPath(import.meta.url)));
const repo = dirname(dashboard);

async function loadDevices() {
  const rules = pathToFileURL(join(repo, "firewall-lab/normalize.json")).href;
  const source = readFileSync(join(dashboard, "src/firewall/devices.ts"), "utf8")
    .replace('import rules from "../../../firewall-lab/normalize.json";', `import rules from "${rules}" with { type: "json" };`);
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
  const folder = mkdtempSync(join(tmpdir(), "fw-devices-"));
  try {
    const file = join(folder, "devices.mjs");
    writeFileSync(file, outputText);
    return await import(pathToFileURL(file).href);
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
}

const companies = readdirSync(join(repo, "firewall-lab/companies")).sort()
  .map((slug) => join(repo, "firewall-lab/companies", slug, "company.json"))
  .filter((path) => existsSync(path))
  .map((path) => JSON.parse(readFileSync(path, "utf8")));

test("the pages and the MCP tools describe the same firewalls", async () => {
  const { listDevices } = await loadDevices();
  const script = [
    "import json, sys",
    "sys.path.insert(0, 'console')",
    "import firewall_catalog as f",
    "rules = f.load_rules('.')",
    "companies = json.load(sys.stdin)",
    "keys = ('deviceId', 'vendor', 'model', 'category', 'ha', 'openSource', 'productKey')",
    "print(json.dumps([{k: d[k] for k in keys} for d in f.Catalog(companies, rules).devices]))"
  ].join("\n");
  const python = process.platform === "win32" ? "python" : "python3";
  const engine = JSON.parse(execFileSync(python, ["-B", "-c", script], { cwd: repo, input: JSON.stringify(companies), encoding: "utf8", maxBuffer: 32 * 1024 * 1024 }));
  const pages = listDevices(companies).map((d) => ({
    deviceId: d.id, vendor: d.vendor, model: d.model, category: d.category, ha: d.ha, openSource: d.openSource, productKey: d.productKey
  }));
  assert.deepEqual(pages, engine);
  assert.equal(new Set(pages.map((d) => d.deviceId)).size, pages.length, "ids are unique");
});

test("search, filters and sorting", async () => {
  const { listDevices, filterDevices, matchedAlternative, readFilters, writeFilters, NO_FILTERS } = await loadDevices();
  const devices = listDevices(companies);
  const find = (patch) => filterDevices(devices, { ...NO_FILTERS, ...patch });
  assert.equal(find({}).length, devices.length);
  assert.ok(find({ vendor: "Fortinet" }).every((d) => d.vendor === "Fortinet"));
  assert.ok(find({ q: "acme fortigate" }).every((d) => d.company.slug === "acme-academy"));
  const cheap = find({ maxPrice: "1000", sort: "price-desc" });
  assert.ok(cheap.length && cheap.every((d) => d.firewall.chosen.priceUsd <= 1000));
  assert.ok(cheap.every((d, i) => !i || cheap[i - 1].firewall.chosen.priceUsd >= d.firewall.chosen.priceUsd));
  const plain = find({ q: "mikrotik" });
  const widened = find({ q: "mikrotik", alternatives: "1" });
  assert.ok(widened.length > plain.length);
  assert.ok(widened.some((d) => matchedAlternative(d, { ...NO_FILTERS, q: "mikrotik", alternatives: "1" })?.vendor === "MikroTik"));
  const filters = { ...NO_FILTERS, q: "a b", openSource: "1", sort: "price-asc" };
  assert.deepEqual(readFilters(`?${writeFilters(filters)}`), filters);
  assert.equal(readFilters("?sort=nonsense").sort, "company");
});

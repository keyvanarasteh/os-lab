// Tests for scripts/affected.mjs and e2e/affected.json (plan item G).
import assert from "node:assert/strict";
import { test } from "node:test";
import { affected, globToRegExp, listSpecs, unlistedSpecs } from "./affected.mjs";

test("every e2e spec is named in e2e/affected.json", () => {
  assert.deepEqual(unlistedSpecs(), []);
});

test("a cleanup view change runs only cleanup specs and routes", () => {
  const result = affected(["dashboard/src/views/cleanup/overview.tsx"]);
  assert.equal(result.mode, "some");
  assert.ok(result.specs.length > 0);
  assert.ok(result.specs.every((spec) => spec.startsWith("cleanup")), result.specs.join());
  assert.ok(result.routes.every((route) => route.startsWith("/cleanup/")), result.routes.join());
});

test("a specific card maps to its own spec", () => {
  assert.deepEqual(affected(["dashboard/src/views/cleanup/space-explorer.tsx"]).specs, ["cleanup-space.spec.ts"]);
});

test("a changed spec runs itself", () => {
  assert.deepEqual(affected(["dashboard/e2e/winapps.spec.ts"]).specs, ["winapps.spec.ts"]);
});

test("shared shell files run the smoke set, not the whole suite", () => {
  const result = affected(["dashboard/src/shell/app-shell.tsx"]);
  assert.equal(result.mode, "some");
  assert.ok(result.specs.length < listSpecs().length);
  assert.ok(result.specs.includes("health-and-content.spec.ts"));
});

test("a locale file adds its locale", () => {
  const result = affected(["dashboard/src/i18n/generated/tr.json"]);
  assert.deepEqual(result.locales, ["tr"]);
  assert.ok(result.specs.length > 0);
});

test("dependency and config changes run everything", () => {
  const result = affected(["dashboard/package-lock.json"]);
  assert.equal(result.mode, "full");
  assert.deepEqual(result.specs, listSpecs());
});

test("files outside dashboard, dist and docs run nothing", () => {
  const result = affected(["cleanup-lab/engine/x.py", "dashboard/dist/index.html", "dashboard/README.md"]);
  assert.equal(result.mode, "none");
  assert.deepEqual(result.specs, []);
});

test("an unmapped source file falls back to the smoke set and is reported", () => {
  const result = affected(["dashboard/src/brand-new-thing.ts"]);
  assert.deepEqual(result.unmapped, ["src/brand-new-thing.ts"]);
  assert.ok(result.specs.length > 0);
});

test("glob patterns", () => {
  assert.ok(globToRegExp("src/views/cleanup/**").test("src/views/cleanup/a/b.tsx"));
  assert.ok(globToRegExp("cleanup*.spec.ts").test("cleanup-space.spec.ts"));
  assert.ok(!globToRegExp("src/views/*.tsx").test("src/views/a/b.tsx"));
  assert.ok(globToRegExp("src/pages/[locale]/**").test("src/pages/[locale]/firewall/x.astro"));
});

test("legal documents outside dashboard/ select the legal routes", () => {
  const result = affected(["docs/legal/PRIVACY.md"]);
  assert.equal(result.mode, "some");
  assert.ok(result.routes.includes("/legal/privacy/"));
});

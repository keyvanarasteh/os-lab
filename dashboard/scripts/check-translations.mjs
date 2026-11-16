#!/usr/bin/env node
// Keep every locale in step when visible English copy is added to the catalog.
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import ts from "typescript";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const locales = ["tr", "de", "fr", "es", "it", "fa", "ar"];
const dictionaries = Object.fromEntries(locales.map((locale) => [
  locale,
  JSON.parse(readFileSync(join(root, "src/i18n/generated", `${locale}.json`), "utf8")),
]));
const expected = new Set(Object.keys(dictionaries.tr));
let errors = 0;
for (const [locale, dictionary] of Object.entries(dictionaries)) {
  const actual = new Set(Object.keys(dictionary));
  const missing = [...expected].filter((key) => !actual.has(key));
  const extra = [...actual].filter((key) => !expected.has(key));
  const empty = [...actual].filter((key) => typeof dictionary[key] !== "string" || !dictionary[key].trim());
  for (const [kind, keys] of [["missing", missing], ["extra", extra], ["empty", empty]]) {
    if (!keys.length) continue;
    errors += keys.length;
    console.error(`${locale}: ${kind} ${keys.length} translation(s): ${keys.slice(0, 10).join(" | ")}`);
  }
}
if (errors) process.exit(1);

// The existing catalog predates this check. Track its known source gaps so new visible TSX
// strings cannot silently join them: a new string needs a locale key or an explicit baseline
// review. This catches JSX text, accessible labels and common view-model copy fields.
const textFields = /^(?:title|label|description|summary|detail|message|hint|fix|error|status|empty|placeholder|alt|aria-label)$/i;
const source = join(root, "src");
const strings = new Set();
function visitFiles(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) visitFiles(path);
    else if (entry.name.endsWith(".tsx")) {
      const file = ts.createSourceFile(path, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      const walk = (node) => {
        let value;
        if (ts.isJsxText(node)) value = node.getText(file);
        else if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
          const parent = node.parent;
          if (ts.isJsxAttribute(parent) && textFields.test(parent.name.getText(file))) value = node.text;
          else if (ts.isPropertyAssignment(parent) && textFields.test(parent.name.getText(file))) value = node.text;
          else if (ts.isVariableDeclaration(parent) && textFields.test(parent.name.getText(file))) value = node.text;
        }
        const normalized = value?.replace(/\s+/g, " ").trim();
        if (normalized && /[A-Za-z]{3}/.test(normalized)) strings.add(normalized);
        ts.forEachChild(node, walk);
      };
      walk(file);
    }
  }
}
visitFiles(source);
const missing = [...strings].filter((value) => !expected.has(value)).sort();
const baselinePath = join(root, "scripts/translation-source-baseline.json");
if (process.argv.includes("--write-baseline")) {
  writeFileSync(baselinePath, `${JSON.stringify(missing, null, 2)}\n`);
  console.log(`Wrote ${missing.length} known TSX source gaps for review.`);
} else {
  const baseline = new Set(JSON.parse(readFileSync(baselinePath, "utf8")));
  const added = missing.filter((value) => !baseline.has(value));
  if (added.length) {
    console.error(`New UI strings without translations (${added.length}):\n${added.slice(0, 30).join("\n")}`);
    process.exit(1);
  }
  console.log(`${expected.size} keys match across ${locales.length} locales; no new untranslated TSX strings.`);
}

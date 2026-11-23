#!/usr/bin/env node
// Git merge driver for dashboard/src/i18n/generated/*.json (plan item C).
//
// Every feature adds keys at the end of the same seven locale files, so line-based merges
// conflicted on every rebase. This driver merges the files as JSON objects, key by key:
// a key changed on one side takes that side; a key added on both sides with the same text
// is kept once; only a key given different texts on the two sides is a real conflict.
// Key order: ours, then the keys only the other side added, in its order. Output uses the
// files' own format (2-space JSON, trailing newline), so a clean merge leaves no noise.
//
// Git calls it as: i18n-merge-driver.mjs %O %A %B %P  (base, ours, theirs, path); the result
// goes into %A. Exit 0 = merged, 1 = conflict (ours is left unchanged and the keys are listed).
// Enabled by .gitattributes plus the local git config that scripts/worktree.sh doctor writes:
//   git config merge.oslab-i18n.name "os-lab locale JSON merge"
//   git config merge.oslab-i18n.driver "node scripts/lib/i18n-merge-driver.mjs %O %A %B %P"
import { readFileSync, writeFileSync } from "node:fs";

export function mergeDictionaries(base, ours, theirs) {
  const result = {};
  const conflicts = [];
  const keys = [...Object.keys(ours), ...Object.keys(theirs).filter((key) => !(key in ours))];
  for (const key of keys) {
    const b = base[key], o = ours[key], t = theirs[key];
    let value;
    if (o === t) value = o;
    else if (o === b) value = t;
    else if (t === b) value = o;
    else {
      conflicts.push(key);
      value = o;
    }
    if (value !== undefined) result[key] = value;
  }
  // Keys deleted on both sides, or deleted on one side and unchanged on the other, stay out.
  return { result, conflicts };
}

const isMain = process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href;
if (isMain) {
  const [basePath, oursPath, theirsPath, name = oursPath] = process.argv.slice(2);
  let base, ours, theirs;
  try {
    base = basePath ? JSON.parse(readFileSync(basePath, "utf8") || "{}") : {};
    ours = JSON.parse(readFileSync(oursPath, "utf8"));
    theirs = JSON.parse(readFileSync(theirsPath, "utf8"));
  } catch (error) {
    console.error(`i18n merge: ${name} is not valid JSON on one side (${error.message}); resolve it by hand`);
    process.exit(1);
  }
  const { result, conflicts } = mergeDictionaries(base, ours, theirs);
  if (conflicts.length) {
    console.error(`i18n merge: ${name}: ${conflicts.length} key(s) have different texts on both sides:`);
    for (const key of conflicts.slice(0, 20)) console.error(`  ${JSON.stringify(key)}`);
    process.exit(1);
  }
  writeFileSync(oursPath, `${JSON.stringify(result, null, 2)}\n`);
}
